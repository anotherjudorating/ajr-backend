"""Glicko-2 math (Mark Glickman, "Example of the Glicko-2 system", 2013).

Ratings are kept on the familiar Glicko scale (1500, RD up to 350). The formulas
work on the Glicko-2 scale: mu = (rating - 1500) / 173.7178, phi = RD / 173.7178.
"""

import math
from dataclasses import dataclass

SCALE = 173.7178
BASE_RATING = 1500
CONVERGENCE = 0.000001


@dataclass(frozen=True)
class Rating:
    rating: float
    rd: float
    volatility: float


def g(phi: float) -> float:
    """Weight of a result: the less certain the opponent's rating, the less it counts."""
    return 1 / math.sqrt(1 + 3 * phi**2 / math.pi**2)


def win_probability(player: Rating, opponent: Rating) -> float:
    """Chance that `player` beats `opponent`, counting the uncertainty of both.

    Symmetric: win_probability(a, b) + win_probability(b, a) == 1.
    """
    phi = math.hypot(player.rd, opponent.rd) / SCALE
    return 1 / (1 + math.exp(-g(phi) * (player.rating - opponent.rating) / SCALE))


def grow_rd(rd: float, days: int, growth: float, max_rd: float) -> float:
    """RD after `days` without contests: RD² grows by growth² a day, up to max_rd."""
    return min(math.sqrt(rd**2 + growth**2 * days), max_rd)


def update(player: Rating, results: list[tuple[Rating, float]], tau: float) -> Rating:
    """New rating after a rating period.

    `results` are (opponent, score) pairs, score 1 for a win and 0 for a loss.
    We use one contest per period, so there is a single pair, but the function
    follows the paper in full so it can be checked against the paper's example.
    """
    mu = (player.rating - BASE_RATING) / SCALE
    phi = player.rd / SCALE

    variance_sum = 0.0
    improvement_sum = 0.0
    for opponent, score in results:
        opponent_mu = (opponent.rating - BASE_RATING) / SCALE
        opponent_g = g(opponent.rd / SCALE)
        expected = 1 / (1 + math.exp(-opponent_g * (mu - opponent_mu)))
        variance_sum += opponent_g**2 * expected * (1 - expected)
        improvement_sum += opponent_g * (score - expected)

    v = 1 / variance_sum  # how much the period tells about the player
    delta = v * improvement_sum  # how far the results are from the expectation

    volatility = new_volatility(player.volatility, phi, v, delta, tau)
    phi_before = math.sqrt(phi**2 + volatility**2)
    new_phi = 1 / math.sqrt(1 / phi_before**2 + 1 / v)
    new_mu = mu + new_phi**2 * improvement_sum

    return Rating(
        rating=BASE_RATING + SCALE * new_mu,
        rd=SCALE * new_phi,
        volatility=volatility,
    )


def new_volatility(volatility: float, phi: float, v: float, delta: float, tau: float) -> float:
    """Step 5 of the paper: solve for the new volatility (Illinois algorithm)."""
    a = math.log(volatility**2)

    def f(x: float) -> float:
        ex = math.exp(x)
        return (ex * (delta**2 - phi**2 - v - ex)) / (2 * (phi**2 + v + ex) ** 2) - (x - a) / tau**2

    upper = a
    if delta**2 > phi**2 + v:
        lower = math.log(delta**2 - phi**2 - v)
    else:
        k = 1
        while f(a - k * tau) < 0:
            k += 1
        lower = a - k * tau

    f_upper, f_lower = f(upper), f(lower)
    while abs(lower - upper) > CONVERGENCE:
        middle = upper + (upper - lower) * f_upper / (f_lower - f_upper)
        f_middle = f(middle)
        if f_middle * f_lower <= 0:
            upper, f_upper = lower, f_lower
        else:
            f_upper = f_upper / 2
        lower, f_lower = middle, f_middle

    return math.exp(upper / 2)
