"""The leaderboard: who stands where in a weight category on a given day.

The rating says how strong an athlete is. The leaderboard also accounts for how
sure we are and asks athletes to keep competing:

    score = rating - rd_factor * RD on that day

RD grows every day without contests, but slower and slower (like the square
root of the time), so a strong athlete who stops fighting would stay on top for
years. So, like FIDE: after `hide_after_days` without contests the athlete leaves
the table until the next contest.

Which weights' tables list an athlete: every weight in which they fought at least
`min_tournaments` tournaments in the `listing_days` before their latest contest. When
there is none (an athlete who fights rarely), one weight: the one of their latest
Olympics, Worlds or continental championships in those days; without one, the weight
of most tournaments then; of equals, the one fought in last. So an athlete who fights
in two weights stands in both, and a try-on of another weight (a single Grand Prix
there) leaves them in their own. Open-category contests count for no weight.

The site gets the same table from the database function ajr.board_at (see the
"api for the site" migration); tests/test_leaderboard_parity.py keeps them equal.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

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
    min_tournaments: int = 3  # in a weight within listing_days, to stand in its table
    listing_days: int = 365
    # with no weight of min_tournaments: the latest major's weight, else the weight of
    # most tournaments (False: the latest contest's, as before 2026-11-11)
    listing_majors: bool = True


@dataclass(frozen=True)
class AthleteState:
    """The athlete after the latest contest."""

    rating: float
    rd: float
    last_day: date
    weight: str  # the weight category of the latest contest in one of WEIGHTS
    weights: frozenset[str] | None = None  # the tables listing them (None: weight's)
    # (day, competition, weight) of their recent contests in one of WEIGHTS
    tournaments: tuple[tuple[date, int | None, str], ...] = field(default=(), compare=False)


Tournament = tuple[date, int | None, str, bool]  # (day, competition, weight, major)


def listed_weights(
    tournaments: tuple[Tournament, ...] | list[Tournament],
    day: date,
    weight: str | None,
    ranking_params: RankingParams,
) -> frozenset[str]:
    """The weights whose tables list the athlete after their contest on `day` (see the
    module's docstring); `weight`: their latest contest's category."""
    since = day - timedelta(days=ranking_params.listing_days)
    window = [t for t in tournaments if since < t[0] <= day]
    competitions: dict[str, set] = {}
    for _, competition_id, fought_in, _ in window:
        competitions.setdefault(fought_in, set()).add(competition_id)
    listed = frozenset(
        w for w, c in competitions.items() if len(c) >= ranking_params.min_tournaments
    )
    if listed:
        return listed
    if ranking_params.listing_majors and window:
        majors = [t for t in window if t[3]]
        if majors:
            return frozenset([max(majors, key=lambda t: t[0])[2]])
        last = {w: max(t[0] for t in window if t[2] == w) for w in competitions}
        return frozenset([max(competitions, key=lambda w: (len(competitions[w]), last[w]))])
    return frozenset([weight]) if weight else frozenset()


def recent(
    tournaments: tuple[Tournament, ...], day: date, ranking_params: RankingParams
) -> tuple[Tournament, ...]:
    """The tournaments still within listing_days of `day`."""
    since = day - timedelta(days=ranking_params.listing_days)
    return tuple(t for t in tournaments if t[0] > since)


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


def update_states(
    states: dict[int, AthleteState],
    outcome: ContestOutcome,
    ranking_params: RankingParams | None = None,
) -> None:
    """Both athletes after the contest. An open-weight contest keeps their category."""
    ranking_params = ranking_params or RankingParams()
    contest = outcome.contest
    for athlete_id, after in (
        (contest.blue_id, outcome.blue_after),
        (contest.white_id, outcome.white_after),
    ):
        weight = contest.weight if contest.weight in WEIGHTS else None
        before = states.get(athlete_id)
        tournaments = recent(before.tournaments, contest.day, ranking_params) if before else ()
        if weight is not None:
            tournaments += ((contest.day, contest.competition_id, weight, contest.major),)
        else:
            weight = before.weight if before else None
        if weight is not None:
            weights = listed_weights(tournaments, contest.day, weight, ranking_params)
            states[athlete_id] = AthleteState(
                after.rating, after.rd, contest.day, weight, weights, tournaments
            )


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
            for weight in state.weights or (state.weight,):
                tables[weight].append(place)
    for table in tables.values():
        table.sort(key=lambda place: place.score, reverse=True)
    return tables
