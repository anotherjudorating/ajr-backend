"""api.competition, api.competition_results, api.competition_contests."""

import pytest
from sqlalchemy import text

from ajr.core.db import engine
from tests.test_api import add_data, add_moves, call

pytestmark = pytest.mark.usefixtures("clean_db")


def test_competition():
    add_data()
    add_moves()

    [comp] = call("select * from api.competition(40)")

    assert (comp["name"], comp["contests"], comp["weights"]) == ("Comeback", 3, ["-73"])
    assert call("select * from api.competition(424242)") == []


def test_competition_results():
    add_data()
    add_moves()

    rows = call("select * from api.competition_results(40)")

    results = {row["athlete_id"]: row["result"] for row in rows}
    assert results == {4: "gold", 6: "silver", 2: "Semi-Final", 3: "Semi-Final"}
    assert [row["athlete_id"] for row in rows][:2] == [4, 6]  # medals first
    gold = rows[0]
    assert (gold["contests"], gold["wins"]) == (2, 2)
    assert gold["score_after"] > gold["score_before"]


def test_competition_contests():
    add_data()
    add_moves()

    rows = call("select * from api.competition_contests(40)")
    final_only = call("select * from api.competition_contests(40, '-73')")

    assert [row["contest_id"] for row in rows][0] == 403  # the final first
    assert len(final_only) == 3
    final = rows[0]
    assert final["winner_id"] == 4 and final["real_fight"]
    assert final["white_chance"] + final["blue_chance"] == pytest.approx(1)
    assert final["blue_score_after"] is not None


def test_the_job_keeps_how_each_athlete_did():
    """ajr.athlete_competition, built by the rating job: the tournament's results."""
    add_data()
    add_moves()

    with engine.connect() as connection:  # our schema: not the site's role
        kept = [
            dict(row._mapping)
            for row in connection.execute(
                text(
                    "select athlete_id, weight, result, score_before, score_after, contests, "
                    "wins, contests_before from ajr.athlete_competition where competition_id = 40"
                )
            )
        ]
    results = call(
        "select athlete_id, weight, result, score_before, score_after, contests, wins, "
        "contests_before from api.competition_results(40)"
    )

    key = lambda row: row["athlete_id"]  # noqa: E731
    assert sorted(kept, key=key) == sorted(results, key=key)
