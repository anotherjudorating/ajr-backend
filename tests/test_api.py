"""The `api` schema the site reads, called as the site's role (anon)."""

from datetime import date, timedelta

import psycopg
import pytest
from sqlalchemy import text, update
from sqlmodel import Session

from ajr.core.db import engine
from ajr.core.job_run import job_run
from ajr.core.models import Athlete, Competition, Contest, Country, WrlRanking
from ajr.rating.job import run_rating

pytestmark = pytest.mark.usefixtures("clean_db")

TODAY = date.today()


def add_data() -> None:
    """-73: athlete 1 beats 2 and 3 recently; 4 beat 5 two years ago (both hidden now)."""
    recent = TODAY - timedelta(days=30)
    long_ago = TODAY - timedelta(days=730)
    with Session(engine) as session:
        session.add(Country(id=1, name="Japan", ioc="JPN"))
        session.add(Competition(id=10, name="Grand Slam", date_from=recent))
        session.add(Competition(id=20, name="Old Open", date_from=long_ago))
        session.flush()
        session.add_all(
            Athlete(id=i, family_name=f"NAME{i}", given_name="Given", country_id=1)
            for i in range(1, 6)
        )
        session.flush()
        session.add_all(
            [
                Contest(id=101, competition_id=10, blue_id=1, white_id=2, winner_id=1,
                        weight="-73", round=1, round_name="Semi-Final"),
                Contest(id=102, competition_id=10, blue_id=1, white_id=3, winner_id=1,
                        weight="-73", round=0, round_name="Final"),
                Contest(id=201, competition_id=20, blue_id=4, white_id=5, winner_id=4,
                        weight="-73", round=0, round_name="Final"),
            ]
        )  # fmt: skip
        session.commit()
    with job_run("rating"):
        run_rating()


def call(sql: str, **params) -> list:
    """Run a query as the site does: role anon."""
    with engine.begin() as connection:
        connection.execute(text("set local role anon"))
        return connection.execute(text(sql), params).mappings().all()


def test_leaderboard():
    add_data()

    rows = call("select * from api.leaderboard('-73')")

    # 2 and 3 both lost to 1: their order between them depends on the draw.
    assert rows[0]["athlete_id"] == 1
    assert {row["athlete_id"] for row in rows} == {1, 2, 3}  # 4 and 5 are hidden
    leader = rows[0]
    assert (leader["place"], leader["family_name"], leader["country"]) == (1, "NAME1", "JPN")
    assert leader["score"] == pytest.approx(leader["rating"] - 3 * leader["rd"], abs=2)
    assert leader["last_contest"] == TODAY - timedelta(days=30)
    # 90 days ago nobody of them had fought yet: no changes to show.
    assert leader["places_up_90d"] is None
    assert leader["score_change_90d"] is None


def test_leaderboard_on_a_past_day_shows_who_was_active_then():
    add_data()

    rows = call("select * from api.leaderboard('-73', :day)", day=TODAY - timedelta(days=700))

    assert [row["athlete_id"] for row in rows] == [4, 5]


def test_leaderboard_change_over_90_days():
    add_data()
    later = TODAY + timedelta(days=100)

    rows = call("select * from api.leaderboard('-73', :day)", day=later)

    leader = rows[0]
    assert leader["places_up_90d"] == 0
    # RD grew for 90 more days without contests: the score went down.
    assert leader["score_change_90d"] < 0


def test_athlete():
    add_data()

    [athlete] = call("select * from api.athlete(1)")

    assert (athlete["id"], athlete["family_name"], athlete["country"]) == (1, "NAME1", "JPN")
    assert (athlete["weight"], athlete["place"], athlete["contests"]) == ("-73", 1, 2)


def test_hidden_athlete_has_no_place():
    add_data()

    [athlete] = call("select * from api.athlete(4)")

    assert athlete["place"] is None
    assert athlete["rating"] is not None


def test_athlete_history_latest_first():
    add_data()

    rows = call("select * from api.athlete_history(1)")

    assert [row["round"] for row in rows] == ["Final", "Semi-Final"]
    final = rows[0]
    assert (final["opponent_id"], final["opponent_family_name"], final["won"]) == (3, "NAME3", True)
    assert final["competition"] == "Grand Slam"
    assert final["rating_after"] > final["rating_before"]


def test_last_update():
    add_data()

    [row] = call("select api.last_update() as updated")

    assert row["updated"] is not None


def test_site_role_cannot_read_our_tables():
    with pytest.raises(Exception) as error:
        call("select * from ajr.athlete")
    assert isinstance(error.value.orig, psycopg.errors.InsufficientPrivilege)


def test_wrl_place_today_only():
    add_data()
    with Session(engine) as session:
        session.add(WrlRanking(athlete_id=1, weight="-73", place=4, points=3000))
        session.commit()

    today = {
        row["athlete_id"]: row["wrl_place"] for row in call("select * from api.leaderboard('-73')")
    }
    past = call("select * from api.leaderboard('-73', :day)", day=TODAY - timedelta(days=10))

    assert today[1] == 4
    assert today[2] is None  # not in the WRL
    assert all(row["wrl_place"] is None for row in past)
    [athlete] = call("select * from api.athlete(1)")
    assert athlete["wrl_place"] == 4


def test_leaderboard_details():
    add_data()
    with Session(engine) as session:
        session.execute(update(Athlete).where(Athlete.id == 1).values(dob_year=2000))
        session.execute(
            update(Competition)
            .where(Competition.id == 10)
            .values(rank_name="Grand Slam", city="Abu Dhabi")
        )
        session.commit()

    [leader] = [r for r in call("select * from api.leaderboard('-73')") if r["athlete_id"] == 1]

    assert leader["birth_year"] == 2000
    assert leader["places_up_6m"] is None  # not in the table 6 months ago
    # trend: 150 .. 30 days ago nothing (the contests were 30 days ago), then today's score
    assert leader["trend"][-1] == leader["score"]
    assert len(leader["trend"]) == 6
    assert (leader["last_competition_id"], leader["last_competition_rank"]) == (10, "Grand Slam")
    assert (leader["last_competition_name"], leader["last_competition_city"]) == (
        "Grand Slam",
        "Abu Dhabi",
    )


def test_previous_leaderboard_for_downgrade_loads():
    """The downgrade rebuilds the function from the earlier migration's code."""
    import importlib.util
    from pathlib import Path

    path = next(Path("migrations/versions").glob("*fbd2c1b2e12c_leaderboard_details.py"))
    spec = importlib.util.spec_from_file_location("leaderboard_details", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert "wrl_place integer" in module.previous_leaderboard()
    assert "birth_year" not in module.previous_leaderboard()


def add_moves() -> None:
    """On top of add_data: 6 fought in -81 100 days ago and moves to -73 now; 4 comes
    back to -73 after two years away."""
    with Session(engine) as session:
        session.add(Competition(id=30, name="Old -81", date_from=TODAY - timedelta(days=100)))
        session.add(Competition(id=40, name="Comeback", date_from=TODAY - timedelta(days=10)))
        session.add(Athlete(id=6, family_name="NAME6", given_name="Given", country_id=1))
        session.add(Athlete(id=7, family_name="NAME7", given_name="Given", country_id=1))
        session.flush()
        session.add_all(
            [
                Contest(id=301, competition_id=30, blue_id=6, white_id=7, winner_id=6,
                        weight="-81", round=0, round_name="Final"),
                Contest(id=401, competition_id=40, blue_id=6, white_id=2, winner_id=6,
                        weight="-73", round=1, round_name="Semi-Final"),
                Contest(id=402, competition_id=40, blue_id=4, white_id=3, winner_id=4,
                        weight="-73", round=1, round_name="Semi-Final"),
                Contest(id=403, competition_id=40, blue_id=6, white_id=4, winner_id=4,
                        weight="-73", round=0, round_name="Final"),
            ]
        )  # fmt: skip
        session.commit()
    with job_run("rating"):
        run_rating(full=True)


def test_leaderboard_counts_changes_across_weights():
    add_data()
    add_moves()

    rows = {row["athlete_id"]: row for row in call("select * from api.leaderboard('-73')")}

    # 6 was in the -81 table 90 days ago: the change is counted from that rating.
    assert rows[6]["entry"] == "new"
    assert rows[6]["places_up_90d"] is None
    assert rows[6]["score_change_90d"] is not None
    # 4 fought in -73 two years ago, then was hidden.
    assert rows[4]["entry"] == "returning"
    assert rows[4]["score_change_90d"] is not None
    # 1 had no rating 90 days ago at all.
    assert rows[1]["entry"] == "new"
    assert rows[1]["score_change_90d"] is None


def test_athlete_page_fields():
    add_data()
    add_moves()

    [athlete] = call("select * from api.athlete(6)")

    assert athlete["weights"] == ["-73", "-81"]  # the latest first
    assert athlete["peak_score"] is not None and athlete["peak_on"] is not None
    [peak_row] = [
        row
        for row in call("select * from api.leaderboard('-73', :day)", day=athlete["peak_on"])
        if row["athlete_id"] == 6
    ]
    assert (athlete["peak_score"], athlete["peak_place"]) == (peak_row["score"], peak_row["place"])
    assert athlete["score_change_90d"] is not None
    assert athlete["places_up_90d"] is None  # not in the -73 table 90 days ago


def test_athlete_history_of_one_weight_with_results():
    add_data()
    add_moves()

    everything = call("select * from api.athlete_history(6)")
    in_73 = call("select * from api.athlete_history(6, '-73')")

    assert len(everything) == 3
    assert [row["contest_id"] for row in in_73] == [403, 401]
    assert {row["result"] for row in in_73} == {"silver"}  # lost the final
    assert everything[-1]["result"] == "gold"  # won the -81 final
    final = in_73[0]
    assert final["opponent_score"] is not None
    assert final["score_after"] < final["score_before"]  # lost


def test_athlete_history_results_of_other_rounds():
    add_data()

    [semi] = call("select * from api.athlete_history(2)")

    assert semi["result"] == "Semi-Final"  # the round 2 lost in


def test_previous_functions_for_downgrade_load():
    import importlib.util
    from pathlib import Path

    path = next(Path("migrations/versions").glob("*bc0c985bd1f9_athlete_page.py"))
    spec = importlib.util.spec_from_file_location("athlete_page", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    leaderboard, athlete, history = module.previous_functions()
    assert "entry text" not in leaderboard and "birth_year" in leaderboard
    assert "wrl_place integer" in athlete and "peak_score" not in athlete
    assert "only_weight" not in history


def test_p4p():
    add_data()
    add_moves()

    rows = call("select * from api.p4p('men')")

    assert {row["weight"] for row in rows} == {"-73"}  # the only weight with a table
    assert [row["weight_place"] for row in rows] == sorted(row["weight_place"] for row in rows)
    leader = rows[0]
    assert (leader["place"], leader["weight_place"]) == (1, 1)
    assert leader["gap"] > 0 and leader["win_probability"] > 0.5
    assert [row["gap"] for row in rows] == sorted((row["gap"] for row in rows), reverse=True)
    assert len(leader["trend"]) == 6 and leader["trend"][-1] == leader["score"]
    assert call("select * from api.p4p('women')") == []


def test_teams():
    add_data()
    add_moves()
    with Session(engine) as session:
        session.add(Country(id=2, name="France", ioc="FRA"))
        session.execute(update(Athlete).where(Athlete.id == 3).values(country_id=2))
        session.commit()

    rows = call("select * from api.teams('men')")

    assert [row["country"] for row in rows] == ["JPN", "FRA"]
    japan = rows[0]
    # -73 (1 leads) and -81 (7 is still there)
    assert (japan["place"], japan["weights_led"], japan["weights_top8"]) == (1, 2, 2)
    assert japan["weights_filled"] == 2
    assert rows[1]["weights_led"] == 0
    assert [row["country"] for row in call("select * from api.teams('mixed')")] == ["JPN", "FRA"]
