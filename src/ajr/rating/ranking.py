"""The leaderboard: who stands where in a weight category on a given day.

The rating says how strong an athlete is. The leaderboard also accounts for how
sure we are and asks athletes to keep competing:

    score = rating - rd_factor * RD on that day

RD grows every day without contests, but slower and slower (like the square
root of the time), so a strong athlete who stops fighting would stay on top for
years. So, like FIDE: after `hide_after_days` without contests the athlete leaves
the table until the next contest.

The site gets the same table from the database function ajr.board_at (see the
"api for the site" migration); tests/test_leaderboard_parity.py keeps them equal.
"""

from dataclasses import dataclass
from datetime import date

from ajr.rating.engine import ContestOutcome, RatingParams
from ajr.rating.glicko2 import grow_rd

WEIGHTS = [
    "-60", "-66", "-73", "-81", "-90", "-100", "+100",
    "-48", "-52", "-57", "-63", "-70", "-78", "+78",
]  # fmt: skip


@dataclass(frozen=True)
class RankingParams:
    rd_factor: float = 3  # picked with `python -m ajr.rating.tune_ranking`
    hide_after_days: int | None = 365


@dataclass(frozen=True)
class AthleteState:
    """The athlete after the latest contest."""

    rating: float
    rd: float
    last_day: date
    weight: str  # the weight category of the latest contest in one of WEIGHTS


@dataclass(frozen=True)
class Standing:
    athlete_id: int
    score: float
    rating: float
    rd: float  # on the day of the table
    days_inactive: int


def standing(
    athlete_id: int,
    state: AthleteState,
    day: date,
    rating_params: RatingParams,
    ranking_params: RankingParams,
) -> Standing | None:
    """The athlete's place data on `day`, or None when hidden for inactivity."""
    days_inactive = (day - state.last_day).days
    hide_after = ranking_params.hide_after_days
    if hide_after is not None and days_inactive > hide_after:
        return None
    rd = grow_rd(state.rd, days_inactive, rating_params.rd_growth, rating_params.max_rd)
    return Standing(
        athlete_id=athlete_id,
        score=state.rating - ranking_params.rd_factor * rd,
        rating=state.rating,
        rd=rd,
        days_inactive=days_inactive,
    )


def update_states(states: dict[int, AthleteState], outcome: ContestOutcome) -> None:
    """Both athletes after the contest. An open-weight contest keeps their category."""
    contest = outcome.contest
    for athlete_id, after in (
        (contest.blue_id, outcome.blue_after),
        (contest.white_id, outcome.white_after),
    ):
        weight = contest.weight if contest.weight in WEIGHTS else None
        if weight is None and athlete_id in states:
            weight = states[athlete_id].weight
        if weight is not None:
            states[athlete_id] = AthleteState(after.rating, after.rd, contest.day, weight)


def leaderboards(
    states: dict[int, AthleteState],
    day: date,
    rating_params: RatingParams,
    ranking_params: RankingParams,
) -> dict[str, list[Standing]]:
    """Every weight's table on `day`, best first."""
    tables: dict[str, list[Standing]] = {weight: [] for weight in WEIGHTS}
    for athlete_id, state in states.items():
        if state.last_day > day:
            continue
        place = standing(athlete_id, state, day, rating_params, ranking_params)
        if place is not None:
            tables[state.weight].append(place)
    for table in tables.values():
        table.sort(key=lambda place: place.score, reverse=True)
    return tables
