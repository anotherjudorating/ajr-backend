"""ajr.record and the api that reads it."""

from datetime import date, timedelta

import pytest
from sqlalchemy import func, update
from sqlmodel import Session

from ajr.core.db import engine
from ajr.core.job_run import job_run
from ajr.core.models import Athlete, Competition, Contest
from ajr.rating.job import run_rating
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
    # records without a weight of their own carry the athlete's main weight
    assert {row["weight"] for row in medals} == {"-73"}
    assert {row["weight"] for row in records["longest_winning_streak"]} <= {"-73", "-81"}
    assert records["youngest_grand_slam_medal"][0]["value"] == 19
    [streak] = [row for row in records["longest_winning_streak"] if row["athlete_id"] == 1]
    assert streak["value"] == 2
    assert records["highest_rating"][0]["family_name"].startswith("NAME")
    # over a top-10 athlete only: the tables are too thin here (see test_weekly_records)
    assert "biggest_upsets" not in records
    assert records["most_world_tour_golds"][0]["athlete_id"] == 1
    assert records["youngest_grand_slam_gold"][0]["athlete_id"] == 1
    # the names come with every row, written by the job
    athletes = [row for rows in records.values() for row in rows if row["athlete_id"]]
    assert all(row["family_name"] and row["country"] for row in athletes)

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
    # a nation's and a tournament's records for both genders and for each: both
    # genders' rows without a filter, one gender's with it
    medals = call("select * from api.record('most_medals_nation')")
    women_medals = call("select * from api.record('most_medals_nation', 'female')")
    assert medals and all(row["gender"] is None for row in medals)
    assert all(row["gender"] == "female" for row in women_medals)
    assert sum(r["value"] for r in women_medals) < sum(r["value"] for r in medals)
    assert call("select * from api.records(10, 'female')") != []


def test_weekly_records(monkeypatch):
    monkeypatch.setattr(weekly, "MIN_TABLE", 1)
    prepare()
    run_records()

    records = by_record(call("select * from api.records(10)"))

    at_1 = {row["athlete_id"]: row for row in records["longest_at_1"]}
    assert 1 in at_1 and at_1[1]["weight"] == "-73"
    assert records["youngest_1"][0]["athlete_id"] == 1
    # pound for pound #1 is always one of the weights' leaders
    assert {row["athlete_id"] for row in records["longest_p4p_1"]} <= set(at_1)
    assert records["biggest_p4p_lead"][0]["value"] > 0
    # in a row never more than in total
    total = {row["athlete_id"]: row["value"] for row in records["longest_at_1"]}
    assert all(row["value"] <= total[row["athlete_id"]] for row in records["longest_at_1_run"])
    top_8 = {row["athlete_id"]: row["value"] for row in records["most_weeks_in_top_8"]}
    assert set(at_1) <= set(top_8)
    assert all(row["value"] <= top_8[row["athlete_id"]]
               for row in records["most_weeks_in_top_8_run"])  # fmt: skip
    assert records["deepest_team"][0]["country"] == "JPN"
    # the upsets over a top-10 athlete, from those tables
    assert all(row["detail"]["opponent_place"] <= 10 for row in records.get("biggest_upsets", []))
    assert "biggest_lead" not in records
    assert "highest_team_rating" not in records  # needs a table in every weight
    # a record's second athlete comes with their nation, as with their name
    opponents = [row for rows in records.values() for row in rows if row["opponent_id"]]
    assert opponents and all(row["opponent_country"] for row in opponents)
    # the rows computed in Python get their names too
    assert at_1[1]["family_name"].startswith("NAME") and at_1[1]["country"]


def test_records_replace_the_old_ones():
    prepare()
    run_records()
    with Session(engine) as session:
        session.add(Contest(id=999, competition_id=30, blue_id=1, white_id=3, winner_id=3,
                            weight="-73", round=2, round_name="Quarter-Final"))  # fmt: skip
        session.commit()
    with job_run("rating"):
        run_rating(full=True)
    run_records()

    rows = call("select * from api.record('longest_rivalry')")
    assert rows and len({(row["athlete_id"], row["opponent_id"]) for row in rows}) == len(rows)


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
    main([])

    assert call("select * from api.records(1)") != []


def test_records_only_when_results_changed(caplog):
    from ajr.records.__main__ import main

    prepare()
    main(["--if-changed"])  # never computed: computed
    assert call("select * from api.records(1)") != []

    with caplog.at_level("INFO"):
        main(["--if-changed"])
    assert "nothing to do" in caplog.text

    caplog.clear()
    with Session(engine) as session:  # new results somewhere
        session.execute(update(Competition).values(results_changed_at=func.now()))
        session.commit()
    with caplog.at_level("INFO"):
        main(["--if-changed"])
    assert "nothing to do" not in caplog.text


def test_weekly_records_count_from_when_the_ratings_settled(monkeypatch):
    monkeypatch.setattr(weekly, "MIN_TABLE", 1)
    monkeypatch.setattr(weekly, "SINCE", date.today() + timedelta(days=30))
    prepare()
    run_records()

    records = by_record(call("select * from api.records(10)"))

    assert "longest_at_1" not in records and "longest_p4p_1" not in records
