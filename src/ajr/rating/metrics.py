"""How good the predictions are.

Every prediction is made before the contest from earlier results only, so any
contest can be used to judge it. Byes and walkovers are not judged: nobody fought.
"""

import math
from dataclasses import dataclass
from datetime import date

from ajr.rating.engine import ContestOutcome

# Probabilities are kept away from 0 and 1 so one confident miss can't be infinite.
EPSILON = 1e-9


@dataclass(frozen=True)
class Scores:
    contests: int
    log_loss: float  # lower is better; 0.693 is a coin toss
    accuracy: float  # share of contests won by the favourite
    brier: float  # mean squared error of the probability; 0.25 is a coin toss


@dataclass(frozen=True)
class Duel:
    """Contests where two models picked different favourites: whose favourite won."""

    contests: int
    first_right: int
    p_value: float  # chance of a split at least this uneven if both models were equal

    @property
    def first_share(self) -> float:
        return self.first_right / self.contests if self.contests else 0.5


def judged(outcomes: list[ContestOutcome], start: date, end: date) -> list[ContestOutcome]:
    """Real fights between `start` and `end` (both included)."""
    return [
        outcome
        for outcome in outcomes
        if start <= outcome.contest.day <= end
        and not outcome.contest.bye
        and not outcome.contest.walkover
    ]


def with_temperature(probability: float, temperature: float) -> float:
    """Make probabilities sharper (temperature < 1) or softer (> 1)."""
    probability = min(max(probability, EPSILON), 1 - EPSILON)
    logit = math.log(probability / (1 - probability))
    return 1 / (1 + math.exp(-logit / temperature))


def scores(outcomes: list[ContestOutcome], temperature: float = 1.0) -> Scores:
    log_loss = brier = right = 0.0
    for outcome in outcomes:
        probability = with_temperature(outcome.blue_win_probability, temperature)
        won = outcome.contest.blue_won
        chance_of_result = probability if won else 1 - probability
        log_loss -= math.log(max(chance_of_result, EPSILON))
        brier += (probability - won) ** 2
        if probability == 0.5:
            right += 0.5
        elif (probability > 0.5) == won:
            right += 1
    count = len(outcomes)
    return Scores(
        contests=count,
        log_loss=log_loss / count,
        accuracy=right / count,
        brier=brier / count,
    )


def duel(first: list[ContestOutcome], second: list[ContestOutcome]) -> Duel:
    """Both lists must hold the same contests in the same order."""
    contests = first_right = 0
    for a, b in zip(first, second, strict=True):
        a_picks_blue = a.blue_win_probability > 0.5
        b_picks_blue = b.blue_win_probability > 0.5
        if a_picks_blue == b_picks_blue:
            continue
        contests += 1
        if a_picks_blue == a.contest.blue_won:
            first_right += 1
    return Duel(contests, first_right, two_sided_p_value(first_right, contests))


def two_sided_p_value(successes: int, trials: int) -> float:
    """Binomial test against 50/50, normal approximation (fine for dozens of trials and up)."""
    if trials == 0:
        return 1.0
    z = (abs(successes - trials / 2) - 0.5) / math.sqrt(trials / 4)
    return math.erfc(max(z, 0) / math.sqrt(2))


def best_temperature(outcomes: list[ContestOutcome]) -> float:
    """The temperature with the lowest log loss (golden-section search on 0.5..2)."""
    low, high = 0.5, 2.0
    ratio = (math.sqrt(5) - 1) / 2
    while high - low > 0.001:
        left = high - ratio * (high - low)
        right = low + ratio * (high - low)
        if scores(outcomes, left).log_loss < scores(outcomes, right).log_loss:
            high = right
        else:
            low = left
    return round((low + high) / 2, 3)
