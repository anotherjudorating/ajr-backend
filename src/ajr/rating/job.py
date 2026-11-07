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
Before it commits, a run checks what it leaves (check_rating): a failed check rolls
it back and fails the job.
"""

import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime

from sqlalchemy import delete, func, select, text, update
from sqlmodel import Session

from ajr.core.db import engine
from ajr.core.models import Competition, JobRun, RatingChange, RatingListing, RatingSettings
from ajr.rating.engine import MEN, WOMEN, ContestOutcome, RatingParams, load_contests, run
from ajr.rating.glicko2 import Rating
from ajr.rating.ranking import WEIGHTS, RankingParams, Tournament, listed_weights, recent
from ajr.rating.snapshot import refresh_contest_list, refresh_snapshot

logger = logging.getLogger(__name__)

PARAMS = RatingParams()
RANKING = RankingParams()
LATEST = date(9999, 12, 31)  # next_fought_on of an athlete's latest contest
COLUMNS = [
    "contest_id", "athlete_id", "seq", "opponent_id", "fought_on", "next_fought_on",
    "weight", "won", "win_probability",
    "rating_before", "rd_before", "volatility_before",
    "rating_after", "rd_after", "volatility_after", "listed_here",
]  # fmt: skip
LISTING_COLUMNS = [
    "contest_id", "athlete_id", "weight", "fought_on", "next_fought_on", "rating_after", "rd_after",
]  # fmt: skip


@dataclass(frozen=True)
class RatingRun:
    # what the site shows may have changed: the site is then told to refresh
    changed: bool
    # a full run asked for (the nightly safety net): rows of the history it found
    # different from what the runs since changes had left; 0 is how it should be
    corrected: int = 0


def run_rating(
    full: bool = False, params: RatingParams = PARAMS, ranking: RankingParams = RANKING
) -> RatingRun:
    """python -m ajr.rating writes the outcome for the update workflow."""
    with Session(engine) as session:
        corrected = 0
        if needs_full_run(session, params, ranking):
            rate_everything(session, params, ranking)
            refresh_contest_list(session, None)
        elif full:
            corrected = rate_everything(session, params, ranking, compare=True)
            refresh_contest_list(session, None)
        else:
            since = first_changed_competition_day(session)
            if since is None:
                logger.info("No results changed since the last rating run")
                # the rating is the same, but names, IJF places or the day may not be
                before = site_visible_state(session)
                refresh_snapshot(session)
                check_rating(session)
                session.commit()
                return RatingRun(changed=site_visible_state(session) != before)
            rate_since(session, since, params, ranking)
            refresh_contest_list(session, since.year)
        session.merge(settings(params, ranking))
        refresh_snapshot(session)
        check_rating(session)
        session.commit()
    logger.info("Rating saved")
    return RatingRun(changed=True, corrected=corrected)


# What a run without new results can still change on the site: the day of today's
# tables (a new day: who drops out, the 90-day changes, names and IJF places, which
# the sync updates) and the medal chances (a draw published). Small tables.
STATE_DAY = text("select max(day) from ajr.leaderboard_snapshot")
STATE_CHANCES = text("""
    select competition_id, weight, athlete_id, gold, medal from ajr.medal_chance
    order by competition_id, weight, athlete_id
""")


def site_visible_state(session: Session) -> tuple:
    return (
        session.execute(STATE_DAY).scalar(),
        [tuple(row) for row in session.execute(STATE_CHANCES)],
    )


class RatingCheckError(RuntimeError):
    """The run left the rating inconsistent: it is rolled back, the site keeps the last."""


# What every run must leave, checked before it commits (two passes over the history,
# well under a second on a copy of production).
CONTEST_CHECK = text("""
    select count(*) from (
        select contest_id from ajr.rating_change group by contest_id having count(*) <> 2
    ) wrong
""")
ATHLETE_CHECK = text("""
    select count(*) filter (where latest <> 1) as without_one_latest,
           count(*) filter (where backwards) as out_of_order,
           count(*) as athletes,
           (select count(*) from ajr.athlete_summary) as summaries
    from (
        select athlete_id,
               count(*) filter (where next_fought_on = date '9999-12-31') as latest,
               bool_or(next_fought_on < fought_on) as backwards
        from ajr.rating_change
        group by athlete_id
    ) a
""")


def check_rating(session: Session) -> None:
    """Every contest has two rows, every athlete one latest row and a history in time
    order, and the Explore summary has every rated athlete."""
    problems = []
    if contests := session.execute(CONTEST_CHECK).scalar_one():
        problems.append(f"{contests} contests without exactly two rating rows")
    athletes = session.execute(ATHLETE_CHECK).one()
    if athletes.without_one_latest:
        problems.append(f"{athletes.without_one_latest} athletes without exactly one latest row")
    if athletes.out_of_order:
        problems.append(f"{athletes.out_of_order} athletes whose history is out of time order")
    if athletes.summaries != athletes.athletes:
        problems.append(
            f"athlete_summary has {athletes.summaries} rows for {athletes.athletes} rated athletes"
        )
    if problems:
        raise RatingCheckError("; ".join(problems))


def settings(params: RatingParams, ranking: RankingParams) -> RatingSettings:
    return RatingSettings(
        id=1,
        **asdict(params),
        rd_factor=ranking.rd_factor,
        hide_after_days=ranking.hide_after_days,
        min_tournaments=ranking.min_tournaments,
        listing_days=ranking.listing_days,
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


def rate_everything(
    session: Session, params: RatingParams, ranking: RankingParams, compare: bool = False
) -> int:
    """With `compare`: how many rows differ from the history there was (seq aside,
    which only numbers them)."""
    contests = load_contests(session.connection(), real_fights_only=params.real_fights_only)
    rows = rating_change_rows(run(contests, params), ranking=ranking)
    logger.info("Full run: %d rating changes from %d contests", len(rows), len(contests))
    corrected = differences(session, rows) if compare else 0
    if corrected:
        logger.warning("The history differed from a full run in %d rows: corrected", corrected)
    session.execute(delete(RatingChange))  # and their rating_listing rows
    copy_rows(session, rows)
    # the planner's statistics of the new rows, for the lists built from them next
    session.execute(text("analyze ajr.rating_change"))
    return corrected


COMPARED = [column for column in COLUMNS if column != "seq"]


def differences(session: Session, rows: list[dict]) -> int:
    """Rows of the new history that are not in the saved one, plus saved rows gone."""
    connection = session.connection()
    connection.execute(text("set local extra_float_digits = 3"))  # ratings exactly
    saved = {
        (row.contest_id, row.athlete_id): tuple(row)
        for row in connection.execute(text(f"select {', '.join(COMPARED)} from ajr.rating_change"))
    }
    new = {(row["contest_id"], row["athlete_id"]): tuple(row[c] for c in COMPARED) for row in rows}
    return sum(saved.get(key) != value for key, value in new.items()) + len(saved.keys() - new)


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


# Each athlete's weight category of their latest contest in one before those (a move
# from it changes the rating: ajr/rating/engine.py).
LAST_WEIGHT_BEFORE_QUERY = text("""
    select distinct on (athlete_id) athlete_id, weight
    from ajr.rating_change
    where seq < :first_seq and weight = any(cast(:weights as text[]))
    order by athlete_id, seq desc
""")


# Each athlete's tournaments in a weight category within listing_days before those
# (which tables list them: ajr/rating/ranking.py).
TOURNAMENTS_BEFORE_QUERY = text("""
    select rc.athlete_id, rc.fought_on, ct.competition_id, ct.weight
    from ajr.rating_change rc
    join ajr.contest ct on ct.id = rc.contest_id
    where rc.seq < :first_seq and rc.fought_on > cast(:since as date) - :days
      and ct.weight = any(cast(:weights as text[]))
    order by rc.seq
""")


def rate_since(session: Session, since: date, params: RatingParams, ranking: RankingParams) -> None:
    connection = session.connection()
    # Read ratings back exactly: with fewer digits (the Supabase pooler's default) the
    # rounding would carry on through every later contest.
    connection.execute(text("set local extra_float_digits = 3"))
    first_seq = connection.execute(FIRST_SEQ_QUERY, {"since": since}).scalar_one()
    before = {
        row.athlete_id: row
        for row in connection.execute(LATEST_ROWS_BEFORE_QUERY, {"first_seq": first_seq})
    }

    last_weight = dict(
        connection.execute(
            LAST_WEIGHT_BEFORE_QUERY, {"first_seq": first_seq, "weights": [*MEN, *WOMEN]}
        ).all()
    )
    start = {
        athlete_id: (
            Rating(row.rating_after, row.rd_after, row.volatility_after),
            row.fought_on,
            last_weight.get(athlete_id),
        )
        for athlete_id, row in before.items()
    }
    tournaments: dict[int, tuple[Tournament, ...]] = {}
    for row in connection.execute(
        TOURNAMENTS_BEFORE_QUERY,
        {"first_seq": first_seq, "since": since, "days": ranking.listing_days, "weights": WEIGHTS},
    ):
        tournaments[row.athlete_id] = tournaments.get(row.athlete_id, ()) + (
            (row.fought_on, row.competition_id, row.weight),
        )
    contests = load_contests(connection, since, real_fights_only=params.real_fights_only)
    # Stand-ins for the latest rows before: they carry the weight category, and
    # get next_fought_on set when the athlete fights again.
    previous = {
        athlete_id: {"weight": row.weight, "next_fought_on": LATEST}
        for athlete_id, row in before.items()
    }
    rows = rating_change_rows(
        run(contests, params, start), first_seq, previous, ranking, tournaments
    )
    logger.info("From %s: %d rating changes from %d contests", since, len(rows), len(contests))

    session.execute(delete(RatingChange).where(RatingChange.seq >= first_seq))
    copy_rows(session, rows)
    for athlete_id, row in before.items():
        next_fought_on = previous[athlete_id]["next_fought_on"]
        if next_fought_on != row.next_fought_on:
            for model in (RatingChange, RatingListing):
                session.execute(
                    update(model)
                    .where(model.contest_id == row.contest_id)
                    .where(model.athlete_id == athlete_id)
                    .values(next_fought_on=next_fought_on)
                )


def rating_change_rows(
    outcomes: list[ContestOutcome],
    first_seq: int = 0,
    previous: dict[int, dict] | None = None,
    ranking: RankingParams = RANKING,
    tournaments: dict[int, tuple[Tournament, ...]] | None = None,
) -> list[dict]:
    """Two rows per contest, one per athlete, with next_fought_on filled in, and
    which tables list the athlete from it on (listed_here, and the others in "also").

    `previous`: each athlete's row before these contests, when continuing; its
    next_fought_on is set here too. `tournaments`: their recent tournaments then.
    """
    rows: list[dict] = []
    latest_row: dict[int, dict] = dict(previous or {})  # athlete -> their latest row so far
    recent_tournaments = dict(tournaments or {})
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
            fought = recent(recent_tournaments.get(athlete_id, ()), contest.day, ranking)
            if contest.weight in WEIGHTS:
                fought += ((contest.day, contest.competition_id, contest.weight),)
            recent_tournaments[athlete_id] = fought
            listed = listed_weights(fought, contest.day, weight, ranking)
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
                "listed_here": weight in listed,
                "also": sorted(listed - {weight}),
            }
            rows.append(row)
            latest_row[athlete_id] = row
    return rows


def copy_rows(session: Session, rows: list[dict]) -> None:
    """COPY is much faster than INSERT for hundreds of thousands of rows. The rows'
    other tables ("also") go to rating_listing."""
    cursor = session.connection().connection.cursor()
    table = RatingChange.__table__
    with cursor.copy(f"copy {table.schema}.{table.name} ({', '.join(COLUMNS)}) from stdin") as copy:
        for row in rows:
            copy.write_row([row[column] for column in COLUMNS])
    listing = RatingListing.__table__
    columns = ", ".join(LISTING_COLUMNS)
    with cursor.copy(f"copy {listing.schema}.{listing.name} ({columns}) from stdin") as copy:
        for row in rows:
            for weight in row["also"]:
                copy.write_row([{**row, "weight": weight}[column] for column in LISTING_COLUMNS])
