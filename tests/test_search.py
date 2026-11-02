"""api.search: the header's search box."""

from datetime import date, timedelta

import pytest
from sqlalchemy import update
from sqlmodel import Session

from ajr.core.db import engine
from ajr.core.models import Athlete, Competition, Country
from tests.test_api import add_data, add_moves, call

pytestmark = pytest.mark.usefixtures("clean_db")

TODAY = date.today()


def search(q: str) -> list:
    return call("select * from api.search(:q)", q=q)


def test_athletes_by_the_start_of_their_names():
    add_data()
    with Session(engine) as session:
        session.execute(
            update(Athlete)
            .where(Athlete.id == 1)
            .values(family_name="HEYDAROV", given_name="Hidayat")
        )
        session.commit()

    assert [(r["kind"], r["id"]) for r in search("heyd")] == [("athlete", 1)]
    assert [r["id"] for r in search("hid hey")] == [1]  # every word, in any order
    assert search("darov") == []  # the middle of a name is not searched
    found = search("heydarov")[0]
    assert (found["country"], found["weight"]) == ("JPN", "-73")


def test_athletes_in_a_table_first_and_at_most_five():
    add_data()
    add_moves()

    rows = [r for r in search("name") if r["kind"] == "athlete"]

    assert len(rows) == 5
    board = [row["athlete_id"] for row in call("select * from api.leaderboard('-73')")]
    assert rows[0]["id"] == board[0]


def test_tournaments():
    add_data()
    with Session(engine) as session:
        session.add(Competition(id=90, name="Tokyo Grand Slam 2026", rank_name="Grand Slam",
                                date_from=TODAY + timedelta(days=30)))  # fmt: skip
        session.add(Competition(id=91, name="Tokyo Open", rank_name="Continental Open",
                                date_from=TODAY + timedelta(days=30)))  # fmt: skip
        session.commit()

    # the coming one first, then those with contests; not the Open with neither
    assert [r["id"] for r in search("grand")] == [90, 10]
    assert [r["id"] for r in search("tokyo slam")] == [90]  # coming World Tour, not the Open
    assert search("rand") == []


def test_nations():
    add_data()
    with Session(engine) as session:
        session.add(Country(id=2, name="Jamaica", ioc="JAM"))  # no rated athletes
        session.commit()

    assert [(r["kind"], r["country"]) for r in search("jap")] == [("nation", "JPN")]
    assert [r["name"] for r in search("JPN") if r["kind"] == "nation"] == ["Japan"]
    assert search("jam") == []


def test_nothing_to_search():
    add_data()

    assert search("") == []
    assert search("   ") == []


def test_search_athletes_puts_the_weight_picked_first():
    add_data()
    add_moves()  # -73: 1, 2, 3, 4 (back) and 6 (moved); -81: 7; 5 is hidden

    def ids(weight: str | None) -> list[int]:
        rows = call("select * from api.search_athletes('name', :weight, 8)", weight=weight)
        return [row["id"] for row in rows]

    board_73 = [row["athlete_id"] for row in call("select * from api.leaderboard('-73')")]
    board_81 = [row["athlete_id"] for row in call("select * from api.leaderboard('-81')")]
    found = ids("-81")
    assert found[: len(board_81)] == board_81  # the weight's table first, by place
    assert set(found) >= set(board_73)  # every athlete can be found
    assert ids("-73")[: len(board_73)] == board_73
    assert call("select * from api.search_athletes('', null, 8)") == []


def test_search_index():
    add_data()
    add_moves()
    with Session(engine) as session:
        session.add(Competition(id=90, name="Tokyo Grand Slam 2026", rank_name="Grand Slam",
                                date_from=TODAY + timedelta(days=30)))  # fmt: skip
        session.commit()

    [index] = call("select api.search_index() as index")
    index = index["index"]

    athletes = index["athletes"]
    in_tables = [row for row in athletes if row[6] is not None]
    assert athletes[: len(in_tables)] == in_tables  # those in a table first
    assert [row[7] for row in in_tables] == sorted((row[7] for row in in_tables), reverse=True)
    one = next(row for row in athletes if row[0] == 1)
    assert one[1:6] == ["NAME1", "Given", "JPN", None, "-73"]
    assert [t[0] for t in index["tournaments"]][0] == 90  # the coming one first
    assert {t[0] for t in index["tournaments"]} == {90, 10, 20, 30, 40}
    assert index["nations"] == [["JPN", "Japan"]]
