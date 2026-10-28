"""The rating step against a real (test) database."""

from datetime import date

import pytest
from sqlalchemy import delete
from sqlmodel import Session, select

from ajr.core.db import engine
from ajr.core.models import (
    Athlete,
    Competition,
    Contest,
    Country,
    JobRun,
    RatingChange,
    RatingSettings,
)
from ajr.rating.__main__ import main
from ajr.rating.engine import RatingParams
from ajr.rating.job import LATEST, run_rating

pytestmark = pytest.mark.usefixtures("clean_db")


def contest(contest_id: int, competition_id: int, blue: int, white: int, winner: int | None,
            weight: str) -> Contest:  # fmt: skip
    return Contest(
        id=contest_id,
        competition_id=competition_id,
        blue_id=blue,
        white_id=white,
        winner_id=winner,
        weight=weight,
        round=0,
    )


def add_contests() -> None:
    """Athletes 1, 2, 3: two contests in March at -73, one open-weight contest in June."""
    with Session(engine) as session:
        session.add(Country(id=1, name="Japan", ioc="JPN"))
        session.add(Competition(id=10, name="Grand Slam", date_from=date(2026, 3, 1)))
        session.add(Competition(id=20, name="Open", date_from=date(2026, 6, 1)))
        session.flush()
        session.add_all(Athlete(id=i, family_name=f"A{i}", country_id=1) for i in (1, 2, 3))
        session.flush()
        session.add_all(
            [
                contest(101, 10, blue=1, white=2, winner=1, weight="-73"),
                contest(102, 10, blue=1, white=3, winner=3, weight="-73"),
                contest(201, 20, blue=2, white=3, winner=2, weight="Open"),
                contest(202, 20, blue=1, white=2, winner=None, weight="Open"),  # not fought yet
            ]
        )
        session.commit()


def changes() -> dict[tuple[int, int], RatingChange]:
    with Session(engine) as session:
        return {(c.contest_id, c.athlete_id): c for c in session.exec(select(RatingChange))}


def test_two_rows_per_decided_contest():
    add_contests()

    run_rating()

    rows = changes()
    assert set(rows) == {(101, 1), (101, 2), (102, 1), (102, 3), (201, 2), (201, 3)}
    winner, loser = rows[(101, 1)], rows[(101, 2)]
    assert (winner.won, loser.won) == (True, False)
    assert (winner.opponent_id, loser.opponent_id) == (2, 1)
    assert winner.win_probability + loser.win_probability == pytest.approx(1)
    assert winner.rating_after > winner.rating_before
    assert loser.rating_after < loser.rating_before


def test_next_fought_on_links_each_athlete_history():
    add_contests()

    run_rating()

    rows = changes()
    # Athlete 1 fought twice on March 1st: the first row is "closed" the same day.
    assert rows[(101, 1)].next_fought_on == date(2026, 3, 1)
    assert rows[(102, 1)].next_fought_on == LATEST
    assert rows[(101, 2)].next_fought_on == date(2026, 6, 1)
    assert rows[(201, 2)].next_fought_on == LATEST
    # The second contest starts from the state after the first one.
    assert rows[(102, 1)].rating_before == pytest.approx(rows[(101, 1)].rating_after)


def test_open_weight_contest_keeps_the_category():
    add_contests()

    run_rating()

    rows = changes()
    assert rows[(201, 2)].weight == "-73"
    assert rows[(201, 3)].weight == "-73"


def test_settings_are_saved():
    add_contests()

    run_rating()

    with Session(engine) as session:
        settings = session.get(RatingSettings, 1)
    assert settings.rd_growth == RatingParams().rd_growth
    assert settings.rd_factor == 3


def test_running_again_replaces_the_rows():
    add_contests()
    run_rating()
    first = changes()

    run_rating()

    assert changes() == first


def test_sync_can_delete_a_rated_contest():
    add_contests()
    run_rating()

    with Session(engine) as session:
        session.execute(delete(Contest).where(Contest.id == 101))
        session.commit()

    assert (101, 1) not in changes()


def test_command_line_run_is_logged():
    add_contests()

    main()

    with Session(engine) as session:
        [run] = session.exec(select(JobRun)).all()
    assert (run.type, run.status) == ("rating", "success")
    assert len(changes()) == 6
