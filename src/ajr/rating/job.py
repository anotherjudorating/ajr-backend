"""Compute the rating and save it in rating_change.

The rating after a contest depends on every earlier contest, so a change in the
past makes everything after it out of date. There are two ways to bring
rating_change up to date:

- Full run: every contest from scratch, about a minute, all ~455k rows rewritten.
  Done with --full (nightly, as a safety net), when there is no rating yet, and
  when the parameters in the code differ from rating_settings.

- From a day: the sync marks a competition (competition.results_changed_at) when
  one of its results appears, changes or vanishes. Contests are rated in order of
  their competition's start day, so we take the earliest competition marked since
  the last successful rating run and recompute every contest from it on, starting
  from each athlete's state just before it; earlier rows stay. On a tournament day
  that is a few hundred rows, which is what lets the job run every 15 minutes.
  Nothing marked: nothing to do.

Either way the rows are replaced in one transaction, so the site never sees a
half-written history, and both ways give the same rows (tests/test_rating_job.py).
"""

import logging
from dataclasses import asdict
from datetime import date, datetime

from sqlalchemy import delete, func, select, text, update
from sqlmodel import Session

from ajr.core.db import engine
from ajr.core.models import Competition, JobRun, RatingChange, RatingSettings
from ajr.rating.engine import ContestOutcome, RatingParams, load_contests, run
from ajr.rating.glicko2 import Rating
from ajr.rating.ranking import WEIGHTS, RankingParams

logger = logging.getLogger(__name__)

PARAMS = RatingParams()
RANKING = RankingParams()
LATEST = date(9999, 12, 31)  # next_fought_on of an athlete's latest contest
COLUMNS = [
    "contest_id", "athlete_id", "seq", "opponent_id", "fought_on", "next_fought_on",
    "weight", "won", "win_probability",
    "rating_before", "rd_before", "volatility_before",
    "rating_after", "rd_after", "volatility_after",
]  # fmt: skip


def run_rating(
    full: bool = False, params: RatingParams = PARAMS, ranking: RankingParams = RANKING
) -> None:
    with Session(engine) as session:
        if full or needs_full_run(session, params, ranking):
            rate_everything(session, params)
        else:
            since = first_changed_competition_day(session)
            if since is None:
                logger.info("No results changed since the last rating run")
                return
            rate_since(session, since, params)
        session.merge(settings(params, ranking))
        session.commit()
    logger.info("Rating saved")


def settings(params: RatingParams, ranking: RankingParams) -> RatingSettings:
    return RatingSettings(
        id=1,
        **asdict(params),
        rd_factor=ranking.rd_factor,
        hide_after_days=ranking.hide_after_days,
    )


def needs_full_run(session: Session, params: RatingParams, ranking: RankingParams) -> bool:
    saved = session.get(RatingSettings, 1)
    if saved is None or saved.model_dump() != settings(params, ranking).model_dump():
        logger.info("Rating parameters changed: full run")
        return True
    if session.scalar(select(RatingChange.contest_id).limit(1)) is None:
        logger.info("No rating yet: full run")
        return True
    if last_rating_start(session) is None:
        logger.info("No successful rating run yet: full run")
        return True
    return False


def last_rating_start(session: Session) -> datetime | None:
    """Start of the last successful run: changes made while it ran are taken again."""
    return session.scalar(
        select(func.max(JobRun.started_at))
        .where(JobRun.type.in_(["rating", "rating_full"]))
        .where(JobRun.status == "success")
    )


def first_changed_competition_day(session: Session) -> date | None:
    return session.scalar(
        select(func.min(Competition.date_from)).where(
            Competition.results_changed_at >= last_rating_start(session)
        )
    )


def rate_everything(session: Session, params: RatingParams) -> None:
    contests = load_contests(session.connection())
    rows = rating_change_rows(run(contests, params))
    logger.info("Full run: %d rating changes from %d contests", len(rows), len(contests))
    session.execute(delete(RatingChange))
    copy_rows(session, rows)


# The rows from the first competition starting on `since` on (they all come after
# the earlier ones in rating order, so they are the rows with seq >= first).
FIRST_SEQ_QUERY = text("""
    select coalesce(
        (select min(rc.seq)
         from ajr.rating_change rc
         join ajr.contest ct on ct.id = rc.contest_id
         join ajr.competition cm on cm.id = ct.competition_id
         where cm.date_from >= :since),
        (select coalesce(max(seq), -1) + 1 from ajr.rating_change)
    )
""")

# Each athlete's latest row before those.
LATEST_ROWS_BEFORE_QUERY = text("""
    select distinct on (athlete_id)
           athlete_id, contest_id, fought_on, next_fought_on, weight,
           rating_after, rd_after, volatility_after
    from ajr.rating_change
    where seq < :first_seq
    order by athlete_id, seq desc
""")


def rate_since(session: Session, since: date, params: RatingParams) -> None:
    connection = session.connection()
    # Read ratings back exactly: with fewer digits (the Supabase pooler's default) the
    # rounding would carry on through every later contest.
    connection.execute(text("set local extra_float_digits = 3"))
    first_seq = connection.execute(FIRST_SEQ_QUERY, {"since": since}).scalar_one()
    before = {
        row.athlete_id: row
        for row in connection.execute(LATEST_ROWS_BEFORE_QUERY, {"first_seq": first_seq})
    }

    start = {
        athlete_id: (Rating(row.rating_after, row.rd_after, row.volatility_after), row.fought_on)
        for athlete_id, row in before.items()
    }
    contests = load_contests(connection, since)
    # Stand-ins for the latest rows before: they carry the weight category, and
    # get next_fought_on set when the athlete fights again.
    previous = {
        athlete_id: {"weight": row.weight, "next_fought_on": LATEST}
        for athlete_id, row in before.items()
    }
    rows = rating_change_rows(run(contests, params, start), first_seq, previous)
    logger.info("From %s: %d rating changes from %d contests", since, len(rows), len(contests))

    session.execute(delete(RatingChange).where(RatingChange.seq >= first_seq))
    copy_rows(session, rows)
    for athlete_id, row in before.items():
        next_fought_on = previous[athlete_id]["next_fought_on"]
        if next_fought_on != row.next_fought_on:
            session.execute(
                update(RatingChange)
                .where(RatingChange.contest_id == row.contest_id)
                .where(RatingChange.athlete_id == athlete_id)
                .values(next_fought_on=next_fought_on)
            )


def rating_change_rows(
    outcomes: list[ContestOutcome],
    first_seq: int = 0,
    previous: dict[int, dict] | None = None,
) -> list[dict]:
    """Two rows per contest, one per athlete, with next_fought_on filled in.

    `previous`: each athlete's row before these contests, when continuing; its
    next_fought_on is set here too.
    """
    rows: list[dict] = []
    latest_row: dict[int, dict] = dict(previous or {})  # athlete -> their latest row so far
    for seq, outcome in enumerate(outcomes, start=first_seq):
        contest = outcome.contest
        blue_chance = outcome.blue_win_probability
        sides = [
            (contest.blue_id, contest.white_id, contest.blue_won, blue_chance,
             outcome.blue_before, outcome.blue_after),
            (contest.white_id, contest.blue_id, not contest.blue_won, 1 - blue_chance,
             outcome.white_before, outcome.white_after),
        ]  # fmt: skip
        for athlete_id, opponent_id, won, chance, before, after in sides:
            previous_row = latest_row.get(athlete_id)
            if previous_row is not None:
                previous_row["next_fought_on"] = contest.day
            weight = contest.weight if contest.weight in WEIGHTS else None
            if weight is None and previous_row is not None:
                weight = previous_row["weight"]  # an open-weight contest keeps the category
            row = {
                "contest_id": contest.contest_id,
                "athlete_id": athlete_id,
                "seq": seq,
                "opponent_id": opponent_id,
                "fought_on": contest.day,
                "next_fought_on": LATEST,
                "weight": weight,
                "won": won,
                "win_probability": chance,
                "rating_before": before.rating,
                "rd_before": before.rd,
                "volatility_before": before.volatility,
                "rating_after": after.rating,
                "rd_after": after.rd,
                "volatility_after": after.volatility,
            }
            rows.append(row)
            latest_row[athlete_id] = row
    return rows


def copy_rows(session: Session, rows: list[dict]) -> None:
    """COPY is much faster than INSERT for hundreds of thousands of rows."""
    cursor = session.connection().connection.cursor()
    table = RatingChange.__table__
    with cursor.copy(f"copy {table.schema}.{table.name} ({', '.join(COLUMNS)}) from stdin") as copy:
        for row in rows:
            copy.write_row([row[column] for column in COLUMNS])
