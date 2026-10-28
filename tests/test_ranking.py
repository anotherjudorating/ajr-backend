from datetime import date

import pytest

from ajr.rating.engine import RatingParams
from ajr.rating.ranking import AthleteState, RankingParams, leaderboards, standing

PARAMS = RatingParams()
RANKING = RankingParams()
DAY = date(2026, 10, 28)


def test_score_is_rating_minus_three_rd_on_the_day():
    state = AthleteState(rating=2000, rd=100, last_day=DAY, weight="-73")

    place = standing(1, state, DAY, PARAMS, RANKING)

    assert place.score == pytest.approx(2000 - 3 * 100)
    assert place.days_inactive == 0


def test_rd_grows_while_not_fighting():
    state = AthleteState(rating=2000, rd=100, last_day=date(2026, 4, 28), weight="-73")

    place = standing(1, state, DAY, PARAMS, RANKING)

    assert place.rd > 100
    assert place.score < 2000 - 3 * 100


def test_hidden_after_a_year_without_contests():
    year_ago = date(2025, 10, 28)  # exactly 365 days: still shown
    state = AthleteState(rating=2000, rd=100, last_day=year_ago, weight="-73")

    assert standing(1, state, DAY, PARAMS, RANKING) is not None
    assert standing(1, state, date(2026, 10, 29), PARAMS, RANKING) is None
    assert standing(1, state, date(2030, 1, 1), PARAMS, RankingParams(hide_after_days=None))


def test_leaderboards_by_weight_best_first():
    states = {
        1: AthleteState(rating=1900, rd=80, last_day=DAY, weight="-73"),
        2: AthleteState(rating=2100, rd=80, last_day=DAY, weight="-73"),
        3: AthleteState(rating=2500, rd=80, last_day=DAY, weight="-81"),
        4: AthleteState(rating=2600, rd=80, last_day=date(2020, 1, 1), weight="-73"),  # hidden
        5: AthleteState(rating=2600, rd=80, last_day=date(2027, 1, 1), weight="-73"),  # future
    }

    tables = leaderboards(states, DAY, PARAMS, RANKING)

    assert [place.athlete_id for place in tables["-73"]] == [2, 1]
    assert [place.athlete_id for place in tables["-81"]] == [3]
    assert tables["+100"] == []
