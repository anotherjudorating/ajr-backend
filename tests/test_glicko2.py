import pytest

from ajr.rating.glicko2 import Rating, grow_rd, update, win_probability


def test_example_from_the_paper():
    """Glickman, "Example of the Glicko-2 system": the worked example, tau = 0.5."""
    player = Rating(rating=1500, rd=200, volatility=0.06)
    results = [
        (Rating(1400, 30, 0.06), 1.0),
        (Rating(1550, 100, 0.06), 0.0),
        (Rating(1700, 300, 0.06), 0.0),
    ]

    new = update(player, results, tau=0.5)

    assert new.rating == pytest.approx(1464.06, abs=0.01)
    assert new.rd == pytest.approx(151.52, abs=0.01)
    assert new.volatility == pytest.approx(0.05999, abs=0.00001)


def test_win_probability_is_symmetric():
    strong = Rating(1700, 80, 0.06)
    weak = Rating(1500, 150, 0.06)

    assert win_probability(strong, weak) + win_probability(weak, strong) == pytest.approx(1)
    assert win_probability(strong, weak) > 0.5
    assert win_probability(strong, strong) == pytest.approx(0.5)


def test_uncertainty_pulls_the_probability_to_one_half():
    sure = win_probability(Rating(1700, 50, 0.06), Rating(1500, 50, 0.06))
    unsure = win_probability(Rating(1700, 300, 0.06), Rating(1500, 300, 0.06))

    assert 0.5 < unsure < sure


def test_win_raises_and_loss_lowers_the_rating():
    player = Rating(1500, 200, 0.06)
    opponent = Rating(1500, 200, 0.06)

    won = update(player, [(opponent, 1.0)], tau=0.5)
    lost = update(player, [(opponent, 0.0)], tau=0.5)

    assert won.rating > 1500 > lost.rating
    assert won.rd < 200 and lost.rd < 200


def test_rd_grows_with_time_up_to_the_limit():
    assert grow_rd(60, 0, growth=3.5, max_rd=350) == 60
    assert grow_rd(60, 365, growth=3.5, max_rd=350) == pytest.approx(89.8, abs=0.1)
    assert grow_rd(300, 10_000, growth=3.5, max_rd=350) == 350


def test_big_upset_raises_volatility():
    """A certain favourite losing to a much weaker opponent: the surprise is large."""
    favourite = Rating(2400, 40, 0.06)
    underdog = Rating(1200, 40, 0.06)

    new = update(favourite, [(underdog, 0.0)], tau=0.5)

    assert new.volatility > 0.06
    assert new.rating < 2400
