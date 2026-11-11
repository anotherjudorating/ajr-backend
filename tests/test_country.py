"""The country page (api.country, api.country_leaders, api.country_tournaments), the
nations rankings behind it and the contests before a tournament."""

from datetime import date

import pytest
from sqlalchemy import text, update
from sqlmodel import Session

from ajr.core.db import engine
from ajr.core.models import Athlete, Country
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


def test_nation_snapshot_ranks_as_teams_does():
    prepare()

    with engine.connect() as connection:
        snapshot = connection.execute(
            text("""select kind, co.ioc, s.place, s.rating
                    from ajr.nation_snapshot s join ajr.country co on co.id = s.country_id""")
        ).all()

    # the places the same; the rating within a point (the snapshot averages the table's
    # rounded scores, api.teams the exact ones)
    for kind in ("men", "women", "mixed"):
        teams = {row["country"]: (row["place"], row["rating"])
                 for row in call("select * from api.teams(:kind)", kind=kind)}  # fmt: skip
        mine = {ioc: (place, rating) for k, ioc, place, rating in snapshot if k == kind}
        assert mine.keys() == teams.keys()
        for ioc, (place, rating) in mine.items():
            assert place == teams[ioc][0] and abs(rating - teams[ioc][1]) <= 1


def test_country():
    prepare()

    [japan] = call("select * from api.country('JPN')")

    assert (japan["name"], japan["athletes"]) == ("Japan", 6)
    assert (japan["place"], japan["place_men"], japan["place_women"]) == (1, 1, None)
    # then: the mixed nations table of that week's Monday, as the country page's chart
    [weeks] = call("""select date_trunc('week', current_date - 90)::date d90,
                             date_trunc('week', current_date - interval '6 months')::date m6""")
    for day, place, rating in (("d90", "place_90d", "rating_90d"), ("m6", "place_6m", "rating_6m")):
        then = {r["country"]: r for r in call("select * from api.teams('mixed', :d)", d=weeks[day])}
        expected = (then["JPN"]["place"], then["JPN"]["rating"]) if "JPN" in then else (None, None)
        assert (japan[place], japan[rating]) == expected
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
