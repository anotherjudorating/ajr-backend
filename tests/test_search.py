"""api.search_index (searched in the browser) and api.sitemap."""

from datetime import date, timedelta

import pytest
from sqlmodel import Session

from ajr.core.db import engine
from ajr.core.models import Competition
from tests.test_api import add_data, add_moves, call

pytestmark = pytest.mark.usefixtures("clean_db")

TODAY = date.today()


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


def test_sitemap():
    add_data()
    add_moves()

    [doc] = call("select api.sitemap() as doc")
    doc = doc["doc"]

    summaries = call("select id, last_contest, contests from api.athletes(top => 1000)")
    assert {a[0]: (a[1], a[2]) for a in doc["athletes"]} == {
        s["id"]: (str(s["last_contest"]), s["contests"]) for s in summaries
    }
    assert {t[0] for t in doc["tournaments"]} == {10, 20, 30, 40}
    assert doc["nations"] == ["JPN"]
