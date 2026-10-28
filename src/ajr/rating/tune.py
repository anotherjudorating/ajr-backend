"""Pick rating parameters by how well they predict contests.

    python -m ajr.rating.tune              # coarse grid, judged on the selection years
    python -m ajr.rating.tune --grid refine
    python -m ajr.rating.tune --check 10   # also the check years for the 10 best
    python -m ajr.rating.tune --test rd_growth=5,initial_rd=350

Years: 2009-2012 warm the ratings up and are not judged; parameters are chosen on
SELECTION, the choice is confirmed on CHECK; TEST is looked at once, at the end.
Every run is compared to the current parameters (RatingParams defaults) in a duel.

Chosen on 2026-10-28 (test years 2025-26: 68.3% of contests won by the favourite,
log loss 0.584; old parameters c=3.5, RD 300: 68.0%, 0.586): rd_growth 5,
initial_rd 350. tau had no effect; a "favourite's win is not counted" threshold
and skipping walkovers did not help, so both were removed.
"""

import argparse
import itertools
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, fields, replace
from datetime import date

from ajr.core.db import engine
from ajr.rating import metrics
from ajr.rating.engine import ContestOutcome, ContestRecord, RatingParams, load_contests, run

SELECTION = (date(2013, 1, 1), date(2022, 12, 31))
CHECK = (date(2023, 1, 1), date(2024, 12, 31))
TEST = (date(2025, 1, 1), date(2100, 1, 1))

GRIDS = {
    "coarse": {
        "rd_growth": [2, 3.5, 5, 8, 12],
        "initial_rd": [200, 250, 300, 350],
    },
    # Around the best of the coarse grid; tau was fixed there.
    "refine": {
        "rd_growth": [4, 4.5, 5, 5.5, 6, 7],
        "initial_rd": [350, 400, 450],
        "tau": [0.3, 0.5, 0.8, 1.2],
    },
}


@dataclass(frozen=True)
class Result:
    params: RatingParams
    scores: metrics.Scores
    duel: metrics.Duel  # against the current parameters


# Each worker process loads the contests once and runs the current parameters once.
contests: list[ContestRecord] = []
current_outcomes: dict[tuple[date, date], list[ContestOutcome]] = {}


def start_worker(loaded: list[ContestRecord], periods: list[tuple[date, date]]) -> None:
    global contests
    contests = loaded
    outcomes = run(contests, RatingParams())
    for period in periods:
        current_outcomes[period] = metrics.judged(outcomes, *period)


def evaluate(params: RatingParams, period: tuple[date, date]) -> Result:
    outcomes = metrics.judged(run(contests, params), *period)
    return Result(
        params, metrics.scores(outcomes), metrics.duel(outcomes, current_outcomes[period])
    )


def evaluate_all(
    all_params: list[RatingParams], period: tuple[date, date], loaded: list[ContestRecord]
) -> list[Result]:
    with ProcessPoolExecutor(
        max_workers=os.cpu_count(), initializer=start_worker, initargs=(loaded, [period])
    ) as pool:
        results = list(pool.map(evaluate, all_params, itertools.repeat(period)))
    return sorted(results, key=lambda result: result.scores.log_loss)


def grid(name: str) -> list[RatingParams]:
    values_by_name = GRIDS[name]
    all_params = []
    for values in itertools.product(*values_by_name.values()):
        params = replace(RatingParams(), **dict(zip(values_by_name, values, strict=True)))
        # A newcomer can't be less certain than the RD limit allows.
        if params.initial_rd > params.max_rd:
            params = replace(params, max_rd=params.initial_rd)
        all_params.append(params)
    return all_params


def describe(params: RatingParams) -> str:
    """Only what differs from the current parameters."""
    current = RatingParams()
    changed = [
        f"{field.name}={getattr(params, field.name)}"
        for field in fields(params)
        if getattr(params, field.name) != getattr(current, field.name)
    ]
    return ", ".join(changed) or "(current)"


def print_table(title: str, results: list[Result]) -> None:
    print(f"\n{title}")
    print(f"{'log loss':>9} {'accuracy':>9} {'brier':>7}  {'duel vs current':>22}  params")
    for result in results:
        s, d = result.scores, result.duel
        duel = f"{d.first_share:.1%} of {d.contests} p={d.p_value:.0e}" if d.contests else "-"
        numbers = f"{s.log_loss:9.4f} {s.accuracy:9.2%} {s.brier:7.4f}"
        print(f"{numbers}  {duel:>22}  {describe(result.params)}")


def parse_params(text: str) -> RatingParams:
    """'rd_growth=5,initial_rd=350' -> RatingParams."""
    values = {}
    for pair in text.split(","):
        name, raw = pair.split("=")
        values[name] = float(raw)
    return replace(RatingParams(), **values)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pick rating parameters.")
    parser.add_argument("--grid", choices=list(GRIDS), default="coarse")
    parser.add_argument("--check", type=int, metavar="N", help="check years for the N best")
    parser.add_argument("--test", metavar="PARAMS", help="judge these parameters on test years")
    args = parser.parse_args()

    with engine.connect() as connection:
        loaded = load_contests(connection)
    print(f"{len(loaded)} contests")

    if args.test:
        params = parse_params(args.test)
        [result] = evaluate_all([params], TEST, loaded)
        print_table(f"TEST {TEST[0]}..", [result])
        outcomes = metrics.judged(run(loaded, params), *SELECTION)
        print(f"temperature fitted on selection years: {metrics.best_temperature(outcomes)}")
        return

    results = evaluate_all(grid(args.grid), SELECTION, loaded)
    print_table(f"SELECTION {SELECTION[0]}..{SELECTION[1]} ({len(results)} variants)", results[:25])

    if args.check:
        best = [result.params for result in results[: args.check]]
        print_table(f"CHECK {CHECK[0]}..{CHECK[1]}", evaluate_all(best, CHECK, loaded))


if __name__ == "__main__":
    main()
