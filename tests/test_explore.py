"""The Explore lists: api.competitions, api.contests, api.athletes, api.nations."""

from datetime import date, timedelta

import pytest
from sqlalchemy import update
from sqlmodel import Session

from ajr.core.db import engine
from ajr.core.models import Athlete, Competition
from tests.test_api import add_data, add_moves, call, refresh

pytestmark = pytest.mark.usefixtures("clean_db")

TODAY = date.today()


def test_competitions():
    add_data()
    add_moves()
    with Session(engine) as session:
        session.execute(
            update(Competition).where(Competition.id == 10).values(rank_name="Grand Slam")
        )
        session.commit()

    rows = call("select * from api.competitions()")
    slams = call("select * from api.competitions(null, array['Grand Slam'])")

    assert [row["date_from"] for row in rows] == sorted(
        (row["date_from"] for row in rows), reverse=True
    )
    gs = next(row for row in rows if row["id"] == 10)
    assert gs["contests"] == 2
    assert 0 <= gs["accuracy"] <= 1
    assert [row["id"] for row in slams] == [10]


def test_contests_page_and_total():
    add_data()
    add_moves()

    first = call("select * from api.contests(top => 2)")
    second = call("select * from api.contests(top => 2, skip => 2)")
    in_comp = call("select * from api.contests(competition_id => 40)")

    # the decided real fights of this year (add_data has one from two years ago)
    days = [30, 30, 100, 10, 10, 10]  # how long ago, in add_data and add_moves
    assert first[0]["total"] == sum((TODAY - timedelta(days=d)).year == TODAY.year for d in days)
    assert len(first) == 2 and len(second) == 2
    assert first[0]["day"] >= first[1]["day"] >= second[0]["day"]
    assert {row["contest_id"] for row in in_comp} == {401, 402, 403}
    final = next(row for row in in_comp if row["contest_id"] == 403)
    assert final["winner_id"] == 4 and final["white_chance"] + final[
        "blue_chance"
    ] == pytest.approx(1)


def test_contests_upsets_only_and_least_likely_first():
    add_data()
    add_moves()

    rows = call("select * from api.contests(upsets => true, sort => 'chance-asc')")
    winner_chance = [
        r["white_chance"] if r["winner_id"] == r["white_id"] else r["blue_chance"] for r in rows
    ]

    assert all(chance <= 0.35 for chance in winner_chance)
    assert winner_chance == sorted(winner_chance)


def test_athletes():
    add_data()
    add_moves()
    with Session(engine) as session:
        session.execute(update(Athlete).where(Athlete.id == 1).values(gender="male", dob_year=2000))
        session.commit()
    refresh()

    everyone = call("select * from api.athletes()")
    found = call("select * from api.athletes(q => 'name1 giv')")
    in_81 = call("select * from api.athletes(only_weight => '-81')")
    men = call("select * from api.athletes(gender => 'male')")

    assert everyone[0]["total"] == 7
    assert [row["id"] for row in found] == [1]
    one = found[0]
    assert (one["weight"], one["birth_year"]) == ("-73", 2000)
    assert one["place"] is not None and one["score"] is not None
    assert one["last_competition"] == "Grand Slam"
    assert {row["id"] for row in in_81} == {7}
    assert [row["id"] for row in men] == [1]


def test_nations():
    add_data()

    [japan] = call("select * from api.nations()")

    assert (japan["country"], japan["athletes"]) == ("JPN", 5)
    assert japan["active"] == 3  # 4 and 5 are hidden
