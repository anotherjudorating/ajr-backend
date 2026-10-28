"""Compute the rating from scratch and replace rating_change with the result.

Everything is recomputed every run: the rating of a contest depends on every
earlier contest, and a full run takes seconds. The new rows replace the old ones
in one transaction, so the site never sees a half-written history.
"""

import logging
from dataclasses import asdict
from datetime import date

from sqlalchemy import delete
from sqlmodel import Session

from ajr.core.db import engine
from ajr.core.models import RatingChange, RatingSettings
from ajr.rating.engine import ContestOutcome, RatingParams, load_contests, run
from ajr.rating.ranking import WEIGHTS, RankingParams

logger = logging.getLogger(__name__)

PARAMS = RatingParams()
RANKING = RankingParams()
LATEST = date(9999, 12, 31)  # next_fought_on of an athlete's latest contest
COLUMNS = [
    "contest_id", "athlete_id", "opponent_id", "fought_on", "next_fought_on", "weight",
    "won", "win_probability",
    "rating_before", "rd_before", "volatility_before",
    "rating_after", "rd_after", "volatility_after",
]  # fmt: skip


def run_rating(params: RatingParams = PARAMS, ranking: RankingParams = RANKING) -> None:
    with engine.connect() as connection:
        contests = load_contests(connection)
    rows = rating_change_rows(run(contests, params))
    logger.info("Computed %d rating changes from %d contests", len(rows), len(contests))

    with Session(engine) as session:
        session.execute(delete(RatingChange))
        copy_rows(session, rows)
        session.merge(
            RatingSettings(
                id=1,
                **asdict(params),
                rd_factor=ranking.rd_factor,
                hide_after_days=ranking.hide_after_days,
            )
        )
        session.commit()
    logger.info("Rating saved")


def rating_change_rows(outcomes: list[ContestOutcome]) -> list[dict]:
    """Two rows per contest, one per athlete, with next_fought_on filled in."""
    rows: list[dict] = []
    latest_row: dict[int, dict] = {}  # athlete -> their latest row so far
    for outcome in outcomes:
        contest = outcome.contest
        blue_chance = outcome.blue_win_probability
        sides = [
            (contest.blue_id, contest.white_id, contest.blue_won, blue_chance,
             outcome.blue_before, outcome.blue_after),
            (contest.white_id, contest.blue_id, not contest.blue_won, 1 - blue_chance,
             outcome.white_before, outcome.white_after),
        ]  # fmt: skip
        for athlete_id, opponent_id, won, chance, before, after in sides:
            previous = latest_row.get(athlete_id)
            if previous is not None:
                previous["next_fought_on"] = contest.day
            weight = contest.weight if contest.weight in WEIGHTS else None
            if weight is None and previous is not None:
                weight = previous["weight"]  # an open-weight contest keeps the category
            row = {
                "contest_id": contest.contest_id,
                "athlete_id": athlete_id,
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
