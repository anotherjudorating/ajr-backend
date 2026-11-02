"""The home page: api.home_leaders, api.biggest_movers, api.recent_upsets, api.upcoming."""

from datetime import date, timedelta

import pytest
from sqlmodel import Session

from ajr.core.db import engine
from ajr.core.job_run import job_run
from ajr.core.models import Competition, Contest
from ajr.rating.job import run_rating
from tests.test_api import add_data, add_moves, call

pytestmark = pytest.mark.usefixtures("clean_db")

TODAY = date.today()


def test_home_leaders():
    add_data()
    add_moves()

    rows = call("select * from api.home_leaders(2)")

    assert [(row["weight"], row["place"]) for row in rows] == [
        ("-73", 1),
        ("-73", 2),
        ("-81", 1),
    ]
    board = call("select * from api.leaderboard('-73')")
    assert rows[0]["athlete_id"] == board[0]["athlete_id"]
    assert rows[0]["score_change_90d"] == board[0]["score_change_90d"]


def test_biggest_movers():
    add_data()
    add_moves()

    rows = call("select * from api.biggest_movers(5, 20)")

    # only athletes who were in their table 90 days ago: 7 (-81), not the -73 newcomers
    assert [row["athlete_id"] for row in rows] == [7]
    assert rows[0]["places_up_90d"] is not None


def test_recent_upsets():
    add_data()
    with Session(engine) as session:
        # the favourite (1, who won both contests before) loses to 2 ten days ago
        session.add(Competition(id=50, name="Upset Open", date_from=TODAY - timedelta(days=10)))
        session.flush()
        session.add(Contest(id=501, competition_id=50, blue_id=1, white_id=2, winner_id=2,
                            weight="-73", round=0, round_name="Final"))  # fmt: skip
        session.commit()
    with job_run("rating"):
        run_rating(full=True)

    [upset] = call("select * from api.recent_upsets(30, 4)")

    assert (upset["contest_id"], upset["winner_id"], upset["loser_id"]) == (501, 2, 1)
    assert upset["winner_chance"] <= 0.35
    assert upset["loser_score"] > upset["winner_score"]
    assert call("select * from api.recent_upsets(5, 4)") == []  # it started 10 days ago


def test_upcoming():
    with Session(engine) as session:
        session.add_all(
            [
                Competition(id=1, name="Paris Grand Slam", rank_name="Grand Slam",
                            date_from=TODAY + timedelta(days=30)),
                Competition(id=2, name="Tokyo Grand Slam", rank_name="Grand Slam",
                            date_from=TODAY + timedelta(days=10)),
                Competition(id=3, name="Going On", rank_name="Grand Prix",
                            date_from=TODAY - timedelta(days=1), date_to=TODAY + timedelta(days=1)),
                Competition(id=4, name="Over", rank_name="Grand Prix",
                            date_from=TODAY - timedelta(days=9), date_to=TODAY - timedelta(days=8)),
                Competition(id=5, name="European Open", rank_name="Continental Open",
                            date_from=TODAY + timedelta(days=5)),
                Competition(id=6, name="Mixed Teams", rank_name="World Championships",
                            date_from=TODAY + timedelta(days=5), is_teams=True),
            ]
        )  # fmt: skip
        session.commit()

    rows = call("select * from api.upcoming(3)")

    assert [row["id"] for row in rows] == [3, 2, 1]
