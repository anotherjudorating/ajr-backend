"""Pick leaderboard rules: does the table reward competing and still mean something?

    python -m ajr.rating.tune_ranking

The strength rating (layer 1) is fixed; here only the table on top of it changes.
Metrics, from monthly snapshots of every weight's top 10 and from all contests:

- fresh: share of top-10 places held by athletes who fought in the last 12 months
- stay: months an athlete stays in the top 10 after starting a break of 12+ months
  (median and 90th percentile)
- table: when two athletes in the table meet, how often the higher one wins
- gain: score points a typical top-10 athlete gets from 4 contests in half a year
  with expected results, compared to resting
"""

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from ajr.core.db import engine
from ajr.rating.engine import ContestOutcome, RatingParams, load_contests, run
from ajr.rating.glicko2 import Rating, grow_rd, update
from ajr.rating.ranking import WEIGHTS, AthleteState, RankingParams, leaderboards, standing

CHOSEN = RatingParams()  # layer 1 is fixed
PERIOD = (date(2015, 1, 1), date(2026, 10, 1))
TOP = 10
BREAK = timedelta(days=365)

# Chosen on 2026-10-28: k = 3, hidden after a year (fresh 100%, table 69.9%).
# A penalty growing with the square of the idle time pushed leavers out a few
# months earlier at the same table accuracy, but was dropped as one rule too many.
VARIANTS = [
    RankingParams(rd_factor=k, hide_after_days=hide)
    for k in (1, 2, 3, 4)
    for hide in (None, 365, 548)
]


@dataclass(frozen=True)
class RankingMetrics:
    fresh: float
    stay_median: float
    stay_p90: float
    table_accuracy: float
    table_contests: int
    gain: float


def month_starts(start: date, end: date) -> list[date]:
    months = []
    day = start
    while day <= end:
        months.append(day)
        day = date(day.year + day.month // 12, day.month % 12 + 1, 1)
    return months


def measure(outcomes: list[ContestOutcome], params: RankingParams) -> RankingMetrics:
    states: dict[int, AthleteState] = {}
    contest_days: dict[int, list[date]] = defaultdict(list)
    months = month_starts(*PERIOD)
    next_month = 0
    fresh_places = places = 0
    # (athlete, day of the last contest) -> months in the top 10 since that contest
    months_in_top: dict[tuple[int, date], int] = defaultdict(int)
    table_right = table_contests = 0

    for outcome in outcomes:
        contest = outcome.contest
        # Snapshots are taken before the contests of their day.
        while next_month < len(months) and months[next_month] <= contest.day:
            tables = leaderboards(states, months[next_month], CHOSEN, params)
            for table in tables.values():
                for place in table[:TOP]:
                    places += 1
                    fresh_places += place.days_inactive <= BREAK.days
                    last_day = months[next_month] - timedelta(days=place.days_inactive)
                    months_in_top[(place.athlete_id, last_day)] += 1
            next_month += 1

        judged = not contest.bye and not contest.walkover
        if judged and PERIOD[0] <= contest.day <= PERIOD[1]:
            blue = states.get(contest.blue_id)
            white = states.get(contest.white_id)
            if blue and white:
                blue_place = standing(contest.blue_id, blue, contest.day, CHOSEN, params)
                white_place = standing(contest.white_id, white, contest.day, CHOSEN, params)
                if blue_place and white_place and blue_place.score != white_place.score:
                    table_contests += 1
                    table_right += (blue_place.score > white_place.score) == contest.blue_won

        for athlete_id, after in (
            (contest.blue_id, outcome.blue_after),
            (contest.white_id, outcome.white_after),
        ):
            contest_days[athlete_id].append(contest.day)
            weight = contest.weight if contest.weight in WEIGHTS else None
            if weight is None and athlete_id in states:
                weight = states[athlete_id].weight  # an open-weight contest keeps the category
            if weight is not None:
                states[athlete_id] = AthleteState(after.rating, after.rd, contest.day, weight)

    stays = []
    for (athlete_id, last_day), months_count in months_in_top.items():
        later = [day for day in contest_days[athlete_id] if day > last_day]
        next_day = min(later) if later else None
        on_break = (next_day - last_day >= BREAK) if next_day else last_day <= PERIOD[1] - BREAK
        if on_break:
            stays.append(months_count)

    return RankingMetrics(
        fresh=fresh_places / places,
        stay_median=statistics.median(stays),
        stay_p90=statistics.quantiles(stays, n=10)[-1],
        table_accuracy=table_right / table_contests,
        table_contests=table_contests,
        gain=fight_gain(params),
    )


def fight_gain(params: RankingParams, rating: float = 1850, rd: float = 70) -> float:
    """Score after half a year: 4 contests against equals with even results, minus resting."""
    rested_rd = grow_rd(rd, 180, CHOSEN.rd_growth, CHOSEN.max_rd)
    player = Rating(rating, rd, CHOSEN.initial_volatility)
    for _ in range(4):
        grown = grow_rd(player.rd, 45, CHOSEN.rd_growth, CHOSEN.max_rd)
        player = Rating(player.rating, grown, player.volatility)
        player = update(player, [(Rating(rating, rd, CHOSEN.initial_volatility), 0.5)], CHOSEN.tau)
    return params.rd_factor * (rested_rd - player.rd) + (player.rating - rating)


def main() -> None:
    with engine.connect() as connection:
        outcomes = run(load_contests(connection), CHOSEN)

    print("   k   hide   fresh  stay med/p90   table  gain")
    for params in VARIANTS:
        m = measure(outcomes, params)
        hide = f"{params.hide_after_days}d" if params.hide_after_days else "never"
        stay = f"{m.stay_median:.0f} / {m.stay_p90:.0f} mo"
        print(
            f"{params.rd_factor:>4} {hide:>6}  {m.fresh:6.1%} "
            f"{stay:>13} {m.table_accuracy:7.2%} {m.gain:5.0f}"
        )


if __name__ == "__main__":
    main()
