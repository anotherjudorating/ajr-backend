"""Medal chances at tournaments that are coming or under way.

Once the IJF publishes the draw, judobase lists every contest of a weight's
bracket, the later ones without athletes yet. The rating job plays each bracket
SIMULATIONS times with today's ratings (the contests already decided stay as they
were) and saves every athlete's chance of gold and of any medal in
ajr.medal_chance; during a tournament the chances follow every result.

The brackets are the IJF's single elimination with repechage from the quarter-
finals. With F the final's fight number (judobase numbers the contests 1..F):

    1 .. F-11      the rounds before the quarter-finals (32, 16, 8 contests…)
    F-10 .. F-7    quarter-finals          F-6, F-5   repechage (their losers, pairwise)
    F-4, F-3       semi-finals             F-2, F-1   bronze: a repechage winner and
    F              final                              the loser of the other semi-final

An athlete with a bye has no contest in the first round: they are already in the
next one. Brackets of another shape (pools of a few athletes) get no chances.
"""

import logging
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ajr.rating.engine import RatingParams
from ajr.rating.glicko2 import Rating, grow_rd, win_probability

logger = logging.getLogger(__name__)

SIMULATIONS = 5000
DRAW_LOOKAHEAD = timedelta(days=14)  # as the sync: contests are fetched this early
LIVE_GRACE = timedelta(days=2)

CONTESTS_QUERY = text("""
    select ct.competition_id, cm.date_from, ct.weight, ct.fight_no, ct.blue_id, ct.white_id,
           ct.winner_id
    from ajr.competition cm
    join ajr.contest ct on ct.competition_id = cm.id
    where cm.date_from between :today - :live_grace and :today + :lookahead
      and coalesce(cm.date_to, cm.date_from) >= :today - :live_grace
      and not coalesce(cm.is_teams, false)
      and ct.weight is not null and ct.fight_no is not null
    order by ct.competition_id, ct.weight, ct.fight_no
""")

RATINGS_QUERY = text("""
    select athlete_id, rating_after, rd_after, volatility_after, fought_on
    from ajr.rating_change
    where next_fought_on = date '9999-12-31' and athlete_id = any(:ids)
""")


@dataclass(frozen=True)
class Fight:
    number: int
    known: tuple[int, ...]  # the athletes judobase already put in it
    winner: int | None  # decided


def feeders(number: int, final: int) -> list[tuple[int, bool]]:
    """The contests whose (winner: True / loser: False) goes to contest `number`."""
    quarters = final - 10
    if number == final:
        return [(final - 4, True), (final - 3, True)]
    if number in (final - 2, final - 1):  # bronze
        repechage, semi = (final - 6, final - 3) if number == final - 2 else (final - 5, final - 4)
        return [(repechage, True), (semi, False)]
    if number in (final - 4, final - 3):  # semi-finals
        first = quarters + 2 * (number - (final - 4))
        return [(first, True), (first + 1, True)]
    if number in (final - 6, final - 5):  # repechage
        first = quarters + 2 * (number - (final - 6))
        return [(first, False), (first + 1, False)]
    # the main bracket: the rounds before, the quarter-finals included, run 1..final-7;
    # a round of n contests is fed by the 2n before it
    start, size = quarters, 4
    while number < start:
        size *= 2
        start -= size
    if start == 1:
        return []  # the first round
    previous = start - 2 * size
    first = previous + 2 * (number - start)
    return [(first, True), (first + 1, True)]


def is_bracket(numbers: set[int], final: int) -> bool:
    """The IJF's bracket: everything from the quarter-finals on, and before them rounds
    of 8, 16, 32… contests down to 1 (byes leave gaps in the first round only)."""
    before = final - 11
    size, total = 8, 0
    while total < before:
        total += size
        size *= 2
    return total == before and set(range(final - 10, final + 1)) <= numbers and min(numbers) >= 1


def simulate(
    fights: list[Fight], chance: dict[tuple[int, int], float], runs: int, rng: random.Random
) -> dict[int, tuple[float, float]]:
    """Athlete -> (chance of gold, chance of any medal) over `runs` plays."""
    final = max(f.number for f in fights)
    numbers = {f.number for f in fights}
    # by number: a contest's feeders come before it
    plan = [
        (f.number, f.known, f.winner, [s for s in feeders(f.number, final) if s[0] in numbers])
        for f in sorted(fights, key=lambda f: f.number)
    ]
    gold: Counter[int] = Counter()
    medal: Counter[int] = Counter()
    for _ in range(runs):
        winners: dict[int, int | None] = {}
        losers: dict[int, int | None] = {}
        for number, known, decided, sources in plan:
            pair = list(known)
            for source, won in sources:
                athlete = (winners if won else losers)[source]
                if athlete is not None and athlete not in pair:
                    pair.append(athlete)
            if decided is not None:
                winner = decided
            elif len(pair) == 2:
                a, b = min(pair), max(pair)
                winner = a if rng.random() < chance[(a, b)] else b
            else:
                winner = pair[0] if pair else None  # walks through, or nobody yet
            winners[number] = winner
            losers[number] = next((a for a in pair if a != winner), None)
        for number in (final - 2, final - 1):
            if winners[number] is not None:
                medal[winners[number]] += 1
        if winners[final] is not None:
            gold[winners[final]] += 1
            medal[winners[final]] += 1
        if losers[final] is not None:
            medal[losers[final]] += 1
    athletes = {a for f in fights for a in f.known}
    return {a: (gold[a] / runs, medal[a] / runs) for a in athletes}


def ratings_on(
    connection: Connection, athletes: set[int], day: date, params: RatingParams
) -> dict[int, Rating]:
    """Each athlete's rating on `day` (RD grown since their last contest)."""
    ratings = {}
    for row in connection.execute(RATINGS_QUERY, {"ids": list(athletes)}):
        days = max(0, (day - row.fought_on).days)
        rd = grow_rd(row.rd_after, days, params.rd_growth, params.max_rd)
        ratings[row.athlete_id] = Rating(row.rating_after, rd, row.volatility_after)
    new = Rating(params.initial_rating, params.initial_rd, params.initial_volatility)
    return {a: ratings.get(a, new) for a in athletes}


def medal_chances(connection: Connection, today: date, params: RatingParams) -> list[dict]:
    """Rows of ajr.medal_chance for the tournaments from LIVE_GRACE ago to
    DRAW_LOOKAHEAD ahead."""
    weights: dict[tuple[int, str], list[Fight]] = defaultdict(list)
    starts: dict[int, date] = {}
    query = {"today": today, "live_grace": LIVE_GRACE, "lookahead": DRAW_LOOKAHEAD}
    for row in connection.execute(CONTESTS_QUERY, query):
        starts[row.competition_id] = row.date_from
        known = tuple(a for a in (row.blue_id, row.white_id) if a is not None)
        weights[(row.competition_id, row.weight)].append(Fight(row.fight_no, known, row.winner_id))

    rows = []
    for (competition_id, weight), fights in weights.items():
        final = max(f.number for f in fights)
        if not is_bracket({f.number for f in fights}, final):
            logger.info("Competition %s %s: not a bracket, no chances", competition_id, weight)
            continue
        athletes = {a for f in fights for a in f.known}
        ratings = ratings_on(connection, athletes, max(today, starts[competition_id]), params)
        chance = {
            (a, b): win_probability(ratings[a], ratings[b], params.rd_factor)
            for a in athletes
            for b in athletes
            if a < b
        }
        # the same numbers on every run of the job while nothing changes
        rng = random.Random(f"{competition_id} {weight}")
        for athlete, (gold, medal) in simulate(fights, chance, SIMULATIONS, rng).items():
            rows.append(
                {"competition_id": competition_id, "weight": weight, "athlete_id": athlete,
                 "gold": gold, "medal": medal}
            )  # fmt: skip
    return rows
