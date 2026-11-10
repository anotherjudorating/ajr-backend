"""The country page (api.country, api.country_leaders, api.country_tournaments, the
nation's weeks the tables job puts in R2), the nations rankings behind it and the
contests before a tournament."""

from datetime import date, timedelta

import pytest
from sqlalchemy import text, update
from sqlmodel import Session

import ajr.tables as tables
from ajr.core.db import engine
from ajr.core.models import Athlete, Country
from ajr.records import weekly
from ajr.records.job import run_records
from tests.test_api import add_data, add_moves, call, refresh

pytestmark = pytest.mark.usefixtures("clean_db")

TODAY = date.today()


def prepare() -> None:
    """add_data and add_moves; athlete 3 is French."""
    add_data()
    add_moves()
    with Session(engine) as session:
        session.add(Country(id=2, name="France", ioc="FRA"))
        session.execute(update(Athlete).where(Athlete.id == 3).values(country_id=2))
        session.commit()
    refresh()


def add_history(*rows: tuple[date, int, int, int]) -> None:
    with engine.begin() as connection:
        for day, country_id, place, rating in rows:
            connection.execute(
                text("insert into ajr.nation_history values (:day, :country, :place, :rating)"),
                {"day": day, "country": country_id, "place": place, "rating": rating},
            )


def test_nation_snapshot_ranks_as_teams_does():
    prepare()

    with engine.connect() as connection:
        snapshot = connection.execute(
            text("""select kind, co.ioc, s.place, s.rating
                    from ajr.nation_snapshot s join ajr.country co on co.id = s.country_id""")
        ).all()

    for kind in ("men", "women", "mixed"):
        teams = {(row["country"], row["place"], row["rating"])
                 for row in call("select * from api.teams(:kind)", kind=kind)}  # fmt: skip
        assert {(ioc, place, rating) for k, ioc, place, rating in snapshot if k == kind} == teams


def test_country():
    prepare()
    add_history(
        (TODAY - timedelta(days=100), 1, 2, 1500),
        (TODAY - timedelta(days=93), 1, 1, 1600),  # the latest week 90 days back
        (TODAY - timedelta(days=93), 2, 2, 1400),
        (TODAY - timedelta(days=200), 1, 3, 1300),
    )
    refresh()  # the page's numbers come from the rating job's run

    [japan] = call("select * from api.country('JPN')")

    assert (japan["name"], japan["athletes"]) == ("Japan", 6)
    assert (japan["place"], japan["place_men"], japan["place_women"]) == (1, 1, None)
    assert (japan["place_90d"], japan["rating_90d"]) == (1, 1600)
    assert (japan["place_6m"], japan["rating_6m"]) == (3, 1300)
    scores = sorted(
        row["score"]
        for weight in ("-73", "-81")
        for row in call("select * from api.leaderboard(:weight)", weight=weight)
        if row["country"] == "JPN"
    )[-8:]
    assert japan["top1"] == max(scores)
    assert japan["top8"] == round(sum(scores) / len(scores))
    assert call("select * from api.country('XXX')") == []


def test_country_without_a_table_today():
    prepare()

    [france] = call("select * from api.country('FRA')")

    assert france["athletes"] == 1
    assert france["place_90d"] is None and france["rating_6m"] is None


def test_country_leaders():
    prepare()

    rows = call("select * from api.country_leaders('JPN')")

    weights = [row["weight"] for row in rows]
    assert list(dict.fromkeys(weights)) == ["-73", "-81"]  # the site's order
    leader_73 = call("select * from api.leaderboard('-73')")[0]
    assert (rows[0]["athlete_id"], rows[0]["place"]) == (leader_73["athlete_id"], 1)
    assert rows[0]["score"] == leader_73["score"]
    for weight in ("-73", "-81"):  # the nation's best first, at most five
        scores = [row["score"] for row in rows if row["weight"] == weight]
        assert scores == sorted(scores, reverse=True) and 1 <= len(scores) <= 5


def test_nation_documents():
    prepare()
    add_history((TODAY - timedelta(days=7), 1, 1, 1600), (TODAY - timedelta(days=14), 1, 2, 1500),
                (TODAY - timedelta(days=7), 2, 2, 1400))  # fmt: skip

    with engine.connect() as connection:
        documents = tables.nation_documents(connection.connection.driver_connection)

    assert [week[1:] for week in documents["JPN"]["weeks"]] == [[2, 1500], [1, 1600]]
    assert documents["FRA"]["weeks"] == [[(TODAY - timedelta(days=7)).isoformat(), 2, 1400]]


def test_country_tournaments():
    prepare()

    rows = call("select * from api.country_tournaments('JPN', 3)")

    # the latest first: Comeback (10 days ago), Grand Slam (30), Old -81 (100)
    assert [row["id"] for row in rows] == [40, 10, 30]
    medals = {row["id"]: (row["gold"], row["silver"], row["bronze"]) for row in rows}
    assert medals[40] == (1, 1, 0)  # 4 beat 6 in the final; 2 and 3 lost semi-finals
    assert medals[10] == (1, 0, 0)  # 3, beaten in the final, is French now
    assert rows[0]["athletes"] == 3  # 2, 4 and 6
    assert [row["id"] for row in call("select * from api.country_tournaments('FRA')")] == [40, 10]


def test_contests_before():
    prepare()

    first = {row["athlete_id"]: row["contests_before"]
             for row in call("select * from api.competition_results(10)")}  # fmt: skip
    later = {row["athlete_id"]: row["contests_before"]
             for row in call("select * from api.competition_results(40)")}  # fmt: skip

    assert first == {1: 0, 2: 0, 3: 0}  # debuts
    # 2 and 3 fought once at 10, 4 once at 20, 6 once at 30
    assert later == {2: 1, 3: 1, 4: 1, 6: 1}


def test_nations_ranking_ties_share_a_place():
    rows = weekly.nations_ranking({10: 1800.2, 20: 1850, 30: 1799.8}, date(2026, 1, 4))

    assert [(row["country_id"], row["place"], row["rating"]) for row in rows] == [
        (20, 1, 1850),
        (10, 2, 1800),
        (30, 2, 1800),
    ]


def test_records_job_replaces_the_nation_history():
    prepare()
    add_history((TODAY - timedelta(days=7), 1, 1, 1600))

    run_records()

    # the test tables are too thin for team ratings: nothing comes back
    with engine.connect() as connection:
        assert connection.execute(text("select count(*) from ajr.nation_history")).scalar() == 0
