"""Medal chances: the bracket (ajr/rating/chances.py) and api.competition_chances."""

import random
from datetime import date, timedelta

import pytest
from sqlmodel import Session

from ajr.core.db import engine
from ajr.core.models import Athlete, Competition, Contest
from ajr.rating.chances import Fight, feeders, is_bracket, simulate
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


def chances_of(fights: list[Fight]) -> dict[int, tuple[float, float]]:
    athletes = range(1, 9)
    chance = {(a, b): 0.8 for a in athletes for b in athletes if a < b}  # the lower id wins
    return simulate(fights, chance, 2000, random.Random(1))


def test_simulate_hands_out_one_gold_and_four_medals():
    result = chances_of(eight())

    assert sum(gold for gold, _ in result.values()) == pytest.approx(1)
    assert sum(medal for _, medal in result.values()) == pytest.approx(4)
    assert max(result, key=lambda a: result[a][0]) == 1
    assert result[1][1] > result[8][1]


def test_simulate_keeps_the_decided_contests():
    # 2 beat 1 in their quarter-final, then won the semi-final and the final
    result = chances_of(eight({1: 2, 7: 2, 11: 2}))

    assert result[2] == (1.0, 1.0)
    assert result[1][0] == 0  # 1 can still win bronze through the repechage
    assert 0 < result[1][1] < 1


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
