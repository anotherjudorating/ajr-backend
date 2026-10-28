"""Run the rating through every contest in order, in memory.

Each contest is a rating period of its own. Before it, both athletes' RD grows for
the days they did not fight; the chance of a blue win is recorded as the
prediction; then both ratings are updated. Every contest counts.

The defaults were picked with `python -m ajr.rating.tune` (see its docstring).
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ajr.rating.glicko2 import Rating, grow_rd, update, win_probability


@dataclass(frozen=True)
class RatingParams:
    initial_rating: float = 1500
    initial_rd: float = 350
    max_rd: float = 350
    rd_growth: float = 5  # RD² grows by rd_growth² for every day without contests
    initial_volatility: float = 0.06
    tau: float = 0.5


@dataclass(frozen=True)
class ContestRecord:
    contest_id: int
    day: date
    weight: str | None
    blue_id: int
    white_id: int
    blue_won: bool
    # Not judged when measuring predictions (nobody really fought), but still counted.
    bye: bool
    walkover: bool  # the contest lasted 0:00


@dataclass(frozen=True)
class ContestOutcome:
    contest: ContestRecord
    blue_win_probability: float  # before the contest
    blue_before: Rating
    white_before: Rating
    blue_after: Rating
    white_after: Rating


# Within a competition: by weight, then by round (judobase counts rounds down to
# the final, which is 0), then by fight number.
CONTESTS_QUERY = text("""
    select ct.id, coalesce(ct.started_at::date, cm.date_from) as day, ct.weight,
           ct.blue_id, ct.white_id, ct.winner_id = ct.blue_id as blue_won,
           coalesce(ct.bye, false) as bye, ct.duration = '00:00:00' as walkover
    from ajr.contest ct
    join ajr.competition cm on cm.id = ct.competition_id
    where ct.winner_id is not null and ct.blue_id is not null and ct.white_id is not null
      and cm.date_from is not null
      and (cast(:since as date) is null or cm.date_from >= :since)
    order by cm.date_from, cm.id, ct.weight, ct.round desc nulls last, ct.fight_no, ct.id
""")


def load_contests(connection: Connection, since: date | None = None) -> list[ContestRecord]:
    """Decided contests in rating order.

    With `since`, only those of competitions starting that day or later.
    """
    return [ContestRecord(*row) for row in connection.execute(CONTESTS_QUERY, {"since": since})]


def run(
    contests: list[ContestRecord],
    params: RatingParams,
    start: dict[int, tuple[Rating, date]] | None = None,
) -> list[ContestOutcome]:
    """`start`: athletes' rating and last contest day before the first contest, when
    continuing a previous run instead of starting from nothing."""
    ratings: dict[int, Rating] = {}
    last_day: dict[int, date] = {}
    for athlete_id, (rating, day) in (start or {}).items():
        ratings[athlete_id], last_day[athlete_id] = rating, day
    outcomes = []

    for contest in contests:
        blue = current_rating(ratings, last_day, contest.blue_id, contest.day, params)
        white = current_rating(ratings, last_day, contest.white_id, contest.day, params)
        blue_score = 1.0 if contest.blue_won else 0.0
        blue_after = update(blue, [(white, blue_score)], params.tau)
        white_after = update(white, [(blue, 1 - blue_score)], params.tau)

        ratings[contest.blue_id], ratings[contest.white_id] = blue_after, white_after
        last_day[contest.blue_id] = last_day[contest.white_id] = contest.day
        outcomes.append(
            ContestOutcome(
                contest=contest,
                blue_win_probability=win_probability(blue, white),
                blue_before=blue,
                white_before=white,
                blue_after=blue_after,
                white_after=white_after,
            )
        )

    return outcomes


def current_rating(
    ratings: dict[int, Rating],
    last_day: dict[int, date],
    athlete_id: int,
    day: date,
    params: RatingParams,
) -> Rating:
    """The athlete's rating on `day`: RD grown for the days since the last contest."""
    if athlete_id not in ratings:
        return Rating(params.initial_rating, params.initial_rd, params.initial_volatility)
    rating = ratings[athlete_id]
    days = (day - last_day[athlete_id]).days
    rd = grow_rd(rating.rd, days, params.rd_growth, params.max_rd)
    return Rating(rating.rating, rd, rating.volatility)
