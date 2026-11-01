"""api.count_matchup and api.popular_matchups, called as the site's role."""

import pytest
from sqlalchemy import text

from ajr.core.db import engine
from tests.test_api import add_data, call

pytestmark = pytest.mark.usefixtures("clean_db")


def count(a: int, b: int, times: int = 1) -> None:
    for _ in range(times):
        call("select api.count_matchup(:a, :b)", a=a, b=b)


def views() -> dict[tuple[int, int], int]:
    with engine.connect() as connection:
        rows = connection.execute(text("select a, b, views from ajr.matchup_views")).all()
    return {(a, b): n for a, b, n in rows}


def test_counting_a_pair_in_either_order():
    add_data()

    count(2, 1)
    count(1, 2)
    count(1, 1)  # not a pair
    count(1, 999)  # no such athlete

    assert views() == {(1, 2): 2}


def test_the_fallback_while_few_pairs_were_opened():
    add_data()
    count(1, 3, times=99)

    rows = call("select * from api.popular_matchups(array[1, 2, 4, 5])")

    assert [(row["a"], row["b"]) for row in rows] == [(1, 2), (4, 5)]
    first = rows[0]
    assert (first["wins"], first["losses"]) == (1, 0)  # 1 beat 2
    assert first["a_family_name"] == "NAME1" and first["a_score"] is not None
    assert first["weight"] == "-73" and first["last_meeting"] is not None


def test_the_most_opened_pairs_once_there_are_enough():
    add_data()
    count(1, 3, times=60)
    count(2, 4, times=30)
    count(4, 5, times=10)

    rows = call("select * from api.popular_matchups(array[1, 2], 2)")

    assert [(row["a"], row["b"]) for row in rows] == [(1, 3), (2, 4)]
    assert (rows[0]["wins"], rows[0]["losses"]) == (1, 0)
    assert (rows[1]["wins"], rows[1]["losses"]) == (0, 0)  # never met
