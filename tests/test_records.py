"""ajr.record and the api that reads it."""

from datetime import date, timedelta

import pytest
from sqlalchemy import update
from sqlmodel import Session

from ajr.core.db import engine
from ajr.core.models import Athlete, Competition, Contest
from ajr.records import weekly
from ajr.records.job import run_records
from tests.test_api import add_data, add_moves, call

pytestmark = pytest.mark.usefixtures("clean_db")


def prepare() -> None:
    """add_data and add_moves, with competition 10 a Grand Slam and years of birth."""
    add_data()
    add_moves()
    with Session(engine) as session:
        session.execute(
            update(Competition).where(Competition.id == 10).values(rank_name="Grand Slam")
        )
        session.execute(
            update(Athlete).where(Athlete.id == 1).values(dob_year=date.today().year - 19)
        )
        session.execute(update(Athlete).where(Athlete.id == 3).values(gender="female"))
        session.commit()


def by_record(rows: list) -> dict[str, list]:
    result: dict[str, list] = {}
    for row in rows:
        result.setdefault(row["record"], []).append(row)
    return result


def test_records():
    prepare()
    run_records()

    records = by_record(call("select * from api.records(10)"))

    medals = records["most_world_tour_medals"]
    assert [(row["athlete_id"], row["detail"]) for row in medals] == [
        (1, {"gold": 1, "silver": 0, "bronze": 0}),
        (3, {"gold": 0, "silver": 1, "bronze": 0}),
    ]
    assert records["youngest_grand_slam_medal"][0]["athlete_id"] == 1
    assert records["youngest_grand_slam_medal"][0]["value"] == 19
    [streak] = [row for row in records["longest_winning_streak"] if row["athlete_id"] == 1]
    assert streak["value"] == 2
    assert records["highest_rating"][0]["family_name"].startswith("NAME")
    rivalry = records["most_frequent_rivalry"][0]
    assert rivalry["value"] == 1 and rivalry["opponent_id"] is not None
    # too few athletes in a table for the weekly records
    assert "longest_at_1" not in records


def test_record_filters():
    prepare()
    run_records()

    everyone = call("select * from api.record('highest_rating')")
    women = call("select * from api.record('highest_rating', 'female')")
    in_81 = call("select * from api.record('highest_rating', null, '-81')")

    assert [row["athlete_id"] for row in women] == [3]
    assert len(everyone) > len(women)
    assert {row["weight"] for row in in_81} == {"-81"}
    # nations' records are the same for men and women
    assert call("select * from api.records(10, 'female')") != []


def test_weekly_records(monkeypatch):
    monkeypatch.setattr(weekly, "MIN_TABLE", 1)
    prepare()
    run_records()

    records = by_record(call("select * from api.records(10)"))

    at_1 = {row["athlete_id"]: row for row in records["longest_at_1"]}
    assert 1 in at_1 and at_1[1]["weight"] == "-73"
    assert records["youngest_1"][0]["athlete_id"] == 1
    assert "highest_team_rating" not in records  # needs a table in every weight


def test_records_replace_the_old_ones():
    prepare()
    run_records()
    with Session(engine) as session:
        session.add(Contest(id=999, competition_id=10, blue_id=2, white_id=3, winner_id=2,
                            weight="-73", round=2, round_name="Quarter-Final"))  # fmt: skip
        session.commit()
    run_records()

    rows = call("select * from api.record('most_frequent_rivalry')")
    assert len({(row["athlete_id"], row["opponent_id"]) for row in rows}) == len(rows)


def test_ranked_ties_share_a_place():
    rows = [
        {"value": 5, "day": date(2020, 1, 1)},
        {"value": 7, "day": date(2021, 1, 1)},
        {"value": 5, "day": date(2019, 1, 1)},
    ]

    result = weekly.ranked(rows, best="high")

    assert [(row["value"], row["place"]) for row in result] == [(7, 1), (5, 2), (5, 2)]
    assert result[1]["day"] == date(2019, 1, 1)  # the earlier one first
    assert (
        weekly.ranked([{"value": 1, "day": date.today() - timedelta(days=1)}], "low")[0]["place"]
        == 1
    )


def test_team_ratings_count_an_empty_weight_as_last_place():
    def table(*rows):
        return [weekly.Standing(athlete_id, score, score, 50, 0) for athlete_id, score in rows]

    tables = {"-60": table((1, 2000), (2, 1900), (3, 1500)), "-66": table((4, 1800), (5, 1600))}
    country = {1: 10, 2: 20, 3: 10, 4: 20, 5: 30}

    ratings = weekly.team_ratings(tables, country)

    # 10: 2000 and nobody in -66 (its last place: 1600); 20: 1900 and 1800
    assert ratings == {10: 1800, 20: 1850, 30: (1500 + 1600) / 2}


def test_no_rating_no_weekly_records():
    with engine.connect() as connection:
        assert weekly.weekly_records(connection, None, None, date.today()) == {}


def test_command_line():
    from ajr.records.__main__ import main

    prepare()
    main()

    assert call("select * from api.records(1)") != []
