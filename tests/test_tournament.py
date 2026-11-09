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


def without_rank(rows: list[dict]) -> list[dict]:
    """athlete_history's rows less the tournament's level (the medal table's; the
    contest page does not show it)."""
    return [{k: v for k, v in r.items() if k != "competition_rank"} for r in rows]


def test_contest_context_is_what_the_contest_page_shows():
    """Each athlete's contests at the tournament and their meetings, as in their histories."""
    add_data()
    add_moves()
    [one] = call("select contest_id from api.competition_contests(40) limit 1")
    [c] = call(f"select * from api.contest({one['contest_id']})")

    rows = call(f"select * from api.contest_context({c['contest_id']})")

    for side in ("white", "blue"):
        history = without_rank(call(f"select * from api.athlete_history({c[side + '_id']})"))
        road = [r for r in history if r["competition_id"] == c["competition_id"]]
        got = [{k: v for k, v in r.items() if k not in ("side", "kind")}
               for r in rows if r["side"] == side and r["kind"] == "road"]  # fmt: skip
        assert got == road
    white = without_rank(call(f"select * from api.athlete_history({c['white_id']})"))
    meetings = [r for r in white if r["opponent_id"] == c["blue_id"]]
    got = [{k: v for k, v in r.items() if k not in ("side", "kind")}
           for r in rows if r["kind"] == "meeting"]  # fmt: skip
    assert got == meetings and got
