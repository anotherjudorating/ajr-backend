"""Run the rating through every contest in order, in memory.

Each contest is a rating period of its own. Before it, both athletes' RD grows for
the days they did not fight; the chance of a blue win is recorded as the
prediction; then both ratings are updated. Every contest counts.

A move to another weight category moves the rating too (see RatingParams): the
athlete's first contest in a heavier weight starts from a rating lower by
move_handicap of it, and back in a lighter one higher by as much, so a try-on of a
heavier weight costs nothing on return. Strong athletes moving up win less than their
rating says until about their 10th contest there
(docs/audits/2026-11-06-weight-ratings.md).

The defaults were picked with `python -m ajr.rating.tune` (see its docstring).
"""

from dataclasses import dataclass, replace
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
    move_handicap: float = 0.05  # share of the rating, on a change of weight category


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
# the final, which is 0), then by fight number. A contest's day is when it started,
# unless judobase gives a time outside its competition's days (a day's slack either
# side): then the competition's first day. Contests are rated in the order of their
# competitions' days, so a contest dated months away from its competition (Gaia
# European Cup 2023: August, its contests dated June) would put an athlete's
# history out of order, two rows holding at once.
CONTESTS_QUERY = text("""
    select ct.id,
           case when ct.started_at::date
                     between cm.date_from - 1 and coalesce(cm.date_to, cm.date_from) + 1
                then ct.started_at::date
                else cm.date_from
           end as day,
           ct.weight,
           ct.blue_id, ct.white_id, ct.winner_id = ct.blue_id as blue_won,
           coalesce(ct.bye, false) as bye, ct.duration = '00:00:00' as walkover
    from ajr.contest ct
    join ajr.competition cm on cm.id = ct.competition_id
    where ct.winner_id is not null and ct.blue_id is not null and ct.white_id is not null
      and ct.blue_id <> ct.white_id  -- never one athlete against themself (athlete_alias)
      and cm.date_from is not null
      and (cast(:since as date) is null or cm.date_from >= :since)
    order by cm.date_from, cm.id, ct.weight, ct.round desc nulls last, ct.fight_no, ct.id
""")


# Lightest to heaviest, men then women: a move's direction (judobase's other
# categories, the open one among them, are no move).
MEN = ("-60", "-66", "-73", "-81", "-90", "-100", "+100")
WOMEN = ("-48", "-52", "-57", "-63", "-70", "-78", "+78")


def move_shift(
    rating: float, from_weight: str | None, to_weight: str | None, params: RatingParams
) -> float:
    """Rating points added on a contest in `to_weight` after the latest one in
    `from_weight`: negative up, positive down, 0 for no move."""
    for weights in (MEN, WOMEN):
        if from_weight in weights and to_weight in weights and from_weight != to_weight:
            step = params.move_handicap * rating
            return -step if weights.index(to_weight) > weights.index(from_weight) else step
    return 0.0  # the same weight, another kind of category, or men's to women's (a data error)


def load_contests(connection: Connection, since: date | None = None) -> list[ContestRecord]:
    """Decided contests in rating order.

    With `since`, only those of competitions starting that day or later.
    """
    return [ContestRecord(*row) for row in connection.execute(CONTESTS_QUERY, {"since": since})]


def run(
    contests: list[ContestRecord],
    params: RatingParams,
    start: dict[int, tuple[Rating, date, str | None]] | None = None,
) -> list[ContestOutcome]:
    """`start`: athletes' rating, last contest day and the weight of their latest
    contest in a weight category before the first contest, when continuing a previous
    run instead of starting from nothing."""
    ratings: dict[int, Rating] = {}
    last_day: dict[int, date] = {}
    last_weight: dict[int, str] = {}
    for athlete_id, (rating, day, weight) in (start or {}).items():
        ratings[athlete_id], last_day[athlete_id] = rating, day
        if weight is not None:
            last_weight[athlete_id] = weight
    outcomes = []

    for contest in contests:
        # In rating order an athlete's contests run forward in time: a contest dated
        # before either athlete's previous one (no start time in judobase, so its
        # competition's first day) counts on that later day.
        day = max(
            contest.day,
            last_day.get(contest.blue_id, contest.day),
            last_day.get(contest.white_id, contest.day),
        )
        if day != contest.day:
            contest = replace(contest, day=day)
        blue = current_rating(ratings, last_day, contest.blue_id, contest.day, params)
        white = current_rating(ratings, last_day, contest.white_id, contest.day, params)
        blue = moved(blue, last_weight.get(contest.blue_id), contest.weight, params)
        white = moved(white, last_weight.get(contest.white_id), contest.weight, params)
        blue_score = 1.0 if contest.blue_won else 0.0
        blue_after = update(blue, [(white, blue_score)], params.tau)
        white_after = update(white, [(blue, 1 - blue_score)], params.tau)

        ratings[contest.blue_id], ratings[contest.white_id] = blue_after, white_after
        last_day[contest.blue_id] = last_day[contest.white_id] = contest.day
        if contest.weight in MEN or contest.weight in WOMEN:
            last_weight[contest.blue_id] = last_weight[contest.white_id] = contest.weight
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


def moved(
    rating: Rating, from_weight: str | None, to_weight: str | None, params: RatingParams
) -> Rating:
    shift = move_shift(rating.rating, from_weight, to_weight, params)
    return replace(rating, rating=rating.rating + shift) if shift else rating


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
