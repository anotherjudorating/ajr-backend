"""The leaderboard is built twice: in Python (ranking.py, for tuning) and in the
database (ajr.board_at, for the site). Both must give the same table."""

import random
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlmodel import Session

from ajr.core.db import engine
from ajr.core.models import Athlete, Competition, Contest, Country
from ajr.rating.engine import RatingParams, load_contests, run
from ajr.rating.job import run_rating
from ajr.rating.ranking import AthleteState, RankingParams, leaderboards, update_states

pytestmark = pytest.mark.usefixtures("clean_db")

START = date(2022, 1, 10)


def add_history() -> None:
    """Three years of monthly competitions in -73 and -81, with athletes moving up a
    category, one open-weight event, and half of -81 retiring after the first year."""
    rng = random.Random(1)
    with Session(engine) as session:
        session.add(Country(id=1, name="Japan", ioc="JPN"))
        session.flush()
        session.add_all(Athlete(id=i, family_name=f"NAME{i}", country_id=1) for i in range(1, 41))
        session.flush()

        contest_id = 1
        for month in range(36):
            competition_id = month + 1
            day = START + timedelta(days=30 * month)
            open_weight = month == 20
            session.add(Competition(id=competition_id, name=f"Event {month}", date_from=day))
            session.flush()
            for weight, athletes in (("-73", range(1, 21)), ("-81", range(21, 41))):
                pool = list(athletes)
                if weight == "-81" and month >= 12:
                    pool = pool[:10]  # the others retired
                if weight == "-81" and month >= 18:
                    pool += [1, 2]  # moved up from -73
                for _ in range(8):
                    blue, white = rng.sample(pool, 2)
                    session.add(
                        Contest(
                            id=contest_id,
                            competition_id=competition_id,
                            blue_id=blue,
                            white_id=white,
                            winner_id=rng.choice([blue, white]),
                            weight="Open" if open_weight else weight,
                            round=0,
                            fight_no=contest_id,
                        )
                    )
                    contest_id += 1
        session.commit()


def python_table(day: date, weight: str) -> list[tuple[int, int]]:
    with engine.connect() as connection:
        outcomes = run(load_contests(connection), RatingParams())
    states: dict[int, AthleteState] = {}
    for outcome in outcomes:
        if outcome.contest.day > day:
            break
        update_states(states, outcome)
    table = leaderboards(states, day, RatingParams(), RankingParams())[weight]
    return [(place.athlete_id, round(place.score)) for place in table]


def database_table(day: date, weight: str) -> list[tuple[int, int]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("select athlete_id, score from api.leaderboard(:weight, :day)"),
            {"weight": weight, "day": day},
        ).all()
    return [(row.athlete_id, row.score) for row in rows]


@pytest.mark.parametrize("weight", ["-73", "-81"])
@pytest.mark.parametrize(
    "day",
    [
        START + timedelta(days=200),  # early: big RDs
        START + timedelta(days=600),  # right after the open-weight event
        START + timedelta(days=30 * 12 + 400),  # retired -81 athletes are hidden by now
        START + timedelta(days=30 * 35),  # a competition day: its contests count
        START + timedelta(days=30 * 35 + 300),  # long after the last contest
    ],
)
def test_python_and_database_tables_match(day, weight):
    add_history()
    run_rating()

    python, database = python_table(day, weight), database_table(day, weight)

    assert python  # the case is not empty
    assert [athlete for athlete, _ in python] == [athlete for athlete, _ in database]
    for (_, python_score), (_, database_score) in zip(python, database, strict=True):
        assert abs(python_score - database_score) <= 1  # rounding of .5 differs
