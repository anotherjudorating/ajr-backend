"""Medal chances: the bracket (ajr/rating/chances.py) and api.competition_chances."""

import random
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlmodel import Session

from ajr.core.db import engine
from ajr.core.models import Athlete, Competition, Contest
from ajr.rating.chances import (
    Fight,
    complete,
    feeders,
    first_round,
    is_bracket,
    round_of,
    simulate,
)
from ajr.rating.glicko2 import grow_rd
from ajr.rating.snapshot import refresh_chances
from tests.test_api import add_data, call

TODAY = date.today()


def test_feeders_follow_the_ijf_bracket():
    # Baku 2026, men -73: a bracket of 64, the final is contest 67
    final = 67
    assert feeders(1, final) == []  # the first round
    assert feeders(33, final) == [(1, True), (2, True)]  # round of 32
    assert feeders(48, final) == [(31, True), (32, True)]
    assert feeders(49, final) == [(33, True), (34, True)]  # round of 16
    assert feeders(57, final) == [(49, True), (50, True)]  # quarter-finals
    assert feeders(60, final) == [(55, True), (56, True)]
    assert feeders(61, final) == [(57, False), (58, False)]  # repechage
    assert feeders(62, final) == [(59, False), (60, False)]
    assert feeders(63, final) == [(57, True), (58, True)]  # semi-finals
    assert feeders(64, final) == [(59, True), (60, True)]
    # bronze: a repechage winner against the loser of the other semi-final
    assert feeders(65, final) == [(61, True), (64, False)]
    assert feeders(66, final) == [(62, True), (63, False)]
    assert feeders(67, final) == [(63, True), (64, True)]


def test_is_bracket():
    assert is_bracket(set(range(1, 68)), 67)
    assert is_bracket(set(range(3, 68)) - {5, 9}, 67)  # byes in the first round
    assert is_bracket(set(range(1, 12)), 11)  # 8 athletes: quarter-finals first
    assert not is_bracket(set(range(1, 7)), 6)  # a pool
    assert not is_bracket(set(range(1, 68)) - {63}, 67)  # a semi-final missing


def eight(winners: dict[int, int] | None = None) -> list[Fight]:
    """A bracket of 8 athletes (1-8, 1 strongest): quarter-finals 1-4 … final 11."""
    winners = winners or {}
    quarters = [Fight(n, (2 * n - 1, 2 * n), winners.get(n)) for n in range(1, 5)]
    return quarters + [Fight(n, (), winners.get(n)) for n in range(5, 12)]


def chances_of(fights: list[Fight], byes=None, n: int = 9):
    athletes = range(1, n)
    chance = {(a, b): 0.8 for a in athletes for b in athletes if a < b}  # the lower id wins
    odds = simulate(fights, chance, 2000, random.Random(1), byes)
    return {a: (odds.gold[a] / 2000, odds.medal[a] / 2000) for a in athletes}, odds


def test_simulate_hands_out_one_gold_and_four_medals():
    result, _ = chances_of(eight())

    assert sum(gold for gold, _ in result.values()) == pytest.approx(1)
    assert sum(medal for _, medal in result.values()) == pytest.approx(4)
    assert max(result, key=lambda a: result[a][0]) == 1
    assert result[1][1] > result[8][1]


def test_simulate_keeps_the_decided_contests():
    # 2 beat 1 in their quarter-final, then won the semi-final and the final
    result, _ = chances_of(eight({1: 2, 7: 2, 11: 2}))

    assert result[2] == (1.0, 1.0)
    assert result[1][0] == 0  # 1 can still win bronze through the repechage
    assert 0 < result[1][1] < 1


def test_rounds_of_the_bracket():
    assert list(first_round(35)) == list(range(1, 17))
    assert list(first_round(11)) == [1, 2, 3, 4]
    assert [round_of(n, 35) for n in (1, 16, 17, 25, 29, 31, 33, 35)] == [
        "1/16",
        "1/16",
        "1/8",
        "1/4",
        "REP",
        "1/2",
        "BR",
        "F",
    ]


def test_a_bye_is_read_from_the_next_round():
    # 16 places: athlete 9 is in second-round contest 9 with nobody before them
    fights, byes = complete([Fight(2, (1, 2), 1), Fight(9, (9, 1), None)], 19)
    assert byes == {1: 9}


@pytest.mark.usefixtures("clean_db")
def test_competition_chances():
    add_data()  # ratings for athletes 1-5
    with Session(engine) as session:
        session.add(Competition(id=60, name="Coming Slam", rank_name="Grand Slam",
                                date_from=TODAY + timedelta(days=3)))  # fmt: skip
        session.add_all(Athlete(id=i, family_name=f"NAME{i}", country_id=1) for i in range(6, 9))
        session.flush()
        # the draw of 8: quarter-finals 1-4 with their athletes, later contests empty
        session.add_all(
            Contest(id=600 + n, competition_id=60, weight="-73", fight_no=n,
                    blue_id=2 * n - 1 if n <= 4 else None, white_id=2 * n if n <= 4 else None)
            for n in range(1, 12)
        )  # fmt: skip
        session.add(Competition(id=70, name="Far Away", date_from=TODAY + timedelta(days=60)))
        session.flush()
        session.add(Contest(id=701, competition_id=70, weight="-73", fight_no=1, blue_id=1,
                            white_id=2))  # fmt: skip
        session.commit()
        refresh_chances(session)
        session.commit()

    rows = call("select * from api.competition_chances(60)")

    assert {row["athlete_id"] for row in rows} == set(range(1, 9))
    assert sum(row["gold"] for row in rows) == pytest.approx(1)
    assert sum(row["medal"] for row in rows) == pytest.approx(4)
    assert rows[0]["medal"] >= rows[-1]["medal"]  # the likeliest first
    assert rows[0]["country"] == "JPN"
    assert call("select * from api.competition_chances(70)") == []  # too far ahead


@pytest.mark.usefixtures("clean_db")
def test_a_contest_to_come_with_the_athletes_ratings_on_the_day():
    add_data()  # athlete 1 beat 2 and 3 at -73 thirty days ago
    with Session(engine) as session:
        session.add(Competition(id=60, name="Coming Slam", rank_name="Grand Slam",
                                date_from=TODAY + timedelta(days=3)))  # fmt: skip
        session.flush()
        session.execute(
            text("insert into ajr.draw (competition_id, weight, fight_no, contest_id, blue_id,"
                 " white_id) values (60, '-81', 1, 6001, 1, 2)")
        )  # fmt: skip
        session.commit()
        latest = session.execute(
            text("select rating_after, rd_after from ajr.rating_change"
                 " where athlete_id = 1 and next_fought_on = date '9999-12-31'")
        ).one()  # fmt: skip

    day = TODAY + timedelta(days=3)

    def state(weight: str):
        with engine.begin() as connection:  # ajr's own function, not the site's
            sql = "select * from ajr.state_on(1, :day, :weight)"
            return connection.execute(text(sql), {"day": day, "weight": weight}).mappings().one()

    same = state("-73")
    assert same["skill"] == pytest.approx(latest.rating_after)
    assert same["rd"] == pytest.approx(grow_rd(latest.rd_after, 33, 5, 350))  # 30 + 3 days
    up = state("-81")
    assert up["skill"] == pytest.approx(latest.rating_after * 0.95)  # a move up: 5% off

    (contest,) = call("select * from api.upcoming_contest(6001)")
    assert (contest["blue_id"], contest["white_id"], contest["weight"]) == (1, 2, "-81")
    assert contest["blue_skill"] == pytest.approx(up["skill"])
    assert call("select * from api.upcoming_contest(101)") == []  # fought: the contest page
