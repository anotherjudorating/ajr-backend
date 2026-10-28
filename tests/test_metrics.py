import math
from datetime import date

import pytest

from ajr.rating import metrics
from ajr.rating.engine import ContestOutcome, ContestRecord
from ajr.rating.glicko2 import Rating

ANY_RATING = Rating(1500, 100, 0.06)


def outcome(
    blue_win_probability: float,
    blue_won: bool,
    day: date = date(2024, 1, 1),
    *,
    bye: bool = False,
    walkover: bool = False,
) -> ContestOutcome:
    contest = ContestRecord(1, day, "-73", 1, 2, blue_won, bye, walkover)
    return ContestOutcome(contest, blue_win_probability, *[ANY_RATING] * 4)


def test_scores():
    outcomes = [outcome(0.8, True), outcome(0.8, False), outcome(0.3, False), outcome(0.5, True)]

    s = metrics.scores(outcomes)

    assert s.contests == 4
    assert s.accuracy == pytest.approx((1 + 0 + 1 + 0.5) / 4)  # a 50/50 call counts half
    expected_log_loss = -(math.log(0.8) + math.log(0.2) + math.log(0.7) + math.log(0.5)) / 4
    assert s.log_loss == pytest.approx(expected_log_loss)
    assert s.brier == pytest.approx((0.2**2 + 0.8**2 + 0.3**2 + 0.5**2) / 4)


def test_coin_toss_scores():
    s = metrics.scores([outcome(0.5, True), outcome(0.5, False)])
    assert s.log_loss == pytest.approx(math.log(2))
    assert s.brier == pytest.approx(0.25)


def test_judged_skips_byes_walkovers_and_other_years():
    kept = outcome(0.6, True, date(2024, 5, 1))
    outcomes = [
        kept,
        outcome(0.6, True, date(2024, 5, 1), bye=True),
        outcome(0.6, True, date(2024, 5, 1), walkover=True),
        outcome(0.6, True, date(2023, 12, 31)),
    ]
    assert metrics.judged(outcomes, date(2024, 1, 1), date(2024, 12, 31)) == [kept]


def test_temperature():
    assert metrics.with_temperature(0.5, 0.7) == pytest.approx(0.5)
    assert metrics.with_temperature(0.8, 1) == pytest.approx(0.8)
    assert metrics.with_temperature(0.8, 0.5) > 0.8  # sharper
    assert metrics.with_temperature(0.8, 2) < 0.8  # softer


def test_best_temperature_softens_overconfident_predictions():
    # Says 90%, but the favourite wins only 70% of the time.
    outcomes = [outcome(0.9, True)] * 7 + [outcome(0.9, False)] * 3
    assert metrics.best_temperature(outcomes) > 1


def test_duel_counts_only_contests_where_favourites_differ():
    first = [outcome(0.6, True), outcome(0.6, True), outcome(0.4, True), outcome(0.4, False)]
    second = [outcome(0.7, True), outcome(0.4, True), outcome(0.6, True), outcome(0.6, False)]

    d = metrics.duel(first, second)

    # Contest 1: both picked blue. 2: first right. 3: second right. 4: first right.
    assert (d.contests, d.first_right) == (3, 2)
    assert d.first_share == pytest.approx(2 / 3)


def test_p_value():
    assert metrics.two_sided_p_value(0, 0) == 1
    assert metrics.two_sided_p_value(50, 100) == pytest.approx(1)
    assert metrics.two_sided_p_value(60, 100) == pytest.approx(0.057, abs=0.005)
    assert metrics.two_sided_p_value(600, 1000) < 1e-9


def test_best_temperature_sharpens_underconfident_predictions():
    # Says 60%, but the favourite wins 90% of the time.
    outcomes = [outcome(0.6, True)] * 9 + [outcome(0.6, False)]
    assert metrics.best_temperature(outcomes) < 1
