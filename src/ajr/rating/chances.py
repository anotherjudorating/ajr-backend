"""Medal chances at tournaments that are coming or under way.

Once the IJF publishes a weight's draw (the day before), judobase's contest sheets
have its whole bracket, every contest by its number, the later ones empty
(ajr.draw, saved by the sync). The rating job plays each drawn bracket SIMULATIONS
times with today's ratings: the contests decided stay as they were, the rest is
fought by our chances. Before the draw: no chances. It saves every
athlete's chance of the quarter-finals, the semi-finals, the final, gold and any
medal (ajr.medal_chance), and for every contest of the bracket who is likely in it
and to win it (ajr.slot_chance); during a tournament they follow every result.

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
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ajr.rating.engine import RatingParams
from ajr.rating.glicko2 import Rating, win_probability

logger = logging.getLogger(__name__)

SIMULATIONS = 5000
DRAW_LOOKAHEAD = timedelta(days=14)  # as the sync: contests are fetched this early
LIVE_GRACE = timedelta(days=2)

# A weight's contests by their number: from its draw where judobase has published one
# (every contest, the ones not fought yet too; results and athletes from the contests
# as they come), else the contests fought so far.
CONTESTS_QUERY = text("""
    select d.competition_id, cm.date_from, d.weight, d.fight_no,
           coalesce(ct.blue_id, d.blue_id) as blue_id,
           coalesce(ct.white_id, d.white_id) as white_id,
           coalesce(ct.winner_id, d.winner_id) as winner_id, d.contest_id as id
    from ajr.draw d
    join ajr.competition cm on cm.id = d.competition_id
    left join ajr.contest ct on ct.id = d.contest_id
    where cm.date_from between :today - :live_grace and :today + :lookahead
      and coalesce(cm.date_to, cm.date_from) >= :today - :live_grace
      and not coalesce(cm.is_teams, false)
    union all
    select ct.competition_id, cm.date_from, ct.weight, ct.fight_no, ct.blue_id, ct.white_id,
           ct.winner_id, ct.id
    from ajr.competition cm
    join ajr.contest ct on ct.competition_id = cm.id
    where cm.date_from between :today - :live_grace and :today + :lookahead
      and coalesce(cm.date_to, cm.date_from) >= :today - :live_grace
      and not coalesce(cm.is_teams, false)
      and ct.weight is not null and ct.fight_no is not null
      and not exists (select from ajr.draw d
                      where d.competition_id = ct.competition_id and d.weight = ct.weight)
    order by 1, 3, 4
""")


STATE_QUERY = text("""
    select a.athlete_id, s.skill, s.rd, s.volatility
    from unnest(cast(:ids as integer[])) as a(athlete_id)
    cross join lateral ajr.state_on(a.athlete_id, :day, :weight) s
""")


@dataclass(frozen=True)
class Fight:
    number: int
    known: tuple[int, ...]  # the athletes judobase already put in it
    winner: int | None  # decided
    contest_id: int | None = None


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


def round_of(number: int, final: int) -> str:
    """The stage as the site writes it: F, BR, 1/2, REP, 1/4, 1/8, 1/16…"""
    if number == final:
        return "F"
    if number >= final - 2:
        return "BR"
    if number >= final - 4:
        return "1/2"
    if number >= final - 6:
        return "REP"
    start, size = final - 10, 4
    while number < start:
        size *= 2
        start -= size
    return f"1/{size}"


def first_round(final: int) -> range:
    """The numbers of the bracket's first round."""
    start, size = final - 10, 4
    while start > 1:
        size *= 2
        start -= size
    return range(1, size + 1)


def is_bracket(numbers: set[int], final: int) -> bool:
    """The IJF's bracket: everything from the quarter-finals on, and before them rounds
    of 8, 16, 32… contests down to 1 (byes leave gaps in the first round only)."""
    before = final - 11
    size, total = 8, 0
    while total < before:
        total += size
        size *= 2
    return total == before and set(range(final - 10, final + 1)) <= numbers and min(numbers) >= 1


@dataclass
class Odds:
    gold: Counter = field(default_factory=Counter)
    medal: Counter = field(default_factory=Counter)
    quarter: Counter = field(default_factory=Counter)
    semi: Counter = field(default_factory=Counter)
    final: Counter = field(default_factory=Counter)
    here: dict = field(default_factory=lambda: defaultdict(Counter))  # contest -> athlete
    wins: dict = field(default_factory=lambda: defaultdict(Counter))


def complete(fights: list[Fight], final: int) -> tuple[list[Fight], dict[int, int]]:
    """Every contest of the bracket up to `final` (those judobase has not listed: empty),
    and the byes judobase shows: an athlete in a second-round contest who fought in
    neither contest before it came through the one of them not listed."""
    by_number = {f.number: f for f in fights}
    allf = [by_number.get(n, Fight(n, (), None)) for n in range(1, final + 1)]
    first = set(first_round(final))
    byes: dict[int, int] = {}
    for f in allf:
        sources = feeders(f.number, final)
        if not sources or not all(s in first for s, _ in sources):
            continue
        fought = {a for s, _ in sources for a in by_number.get(s, Fight(s, (), None)).known}
        for athlete in f.known:
            if athlete in fought:
                continue
            free = [s for s, _ in sources if s not in by_number and s not in byes]
            if free:
                byes[free[0]] = athlete
    return allf, byes


def simulate(
    fights: list[Fight],
    chance: dict[tuple[int, int], float],
    runs: int,
    rng: random.Random,
    byes: dict[int, int] | None = None,
) -> Odds:
    """`runs` plays of the bracket (`fights`: every contest up to the final, by number;
    `byes`: a first round contest not listed -> the athlete who passes through it)."""
    final = max(f.number for f in fights)
    byes = byes or {}
    plan = [
        (f.number, f.known, f.winner, feeders(f.number, final))
        for f in sorted(fights, key=lambda f: f.number)
    ]
    odds = Odds()
    for _ in range(runs):
        filled: dict[int, tuple[int, ...]] = {n: (a,) for n, a in byes.items()}
        winners: dict[int, int | None] = {}
        losers: dict[int, int | None] = {}
        for number, known, decided, sources in plan:
            pair = list(known) or list(filled.get(number, ()))
            for source, won in sources:
                if len(pair) == 2:
                    break
                athlete = (winners if won else losers).get(source)
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
            if decided is None:  # a first round place alone: a bye
                for a in pair:
                    odds.here[number][a] += 1
                if winner is not None and len(pair) == 2:
                    odds.wins[number][winner] += 1
            if final - 10 <= number <= final - 7:
                odds.quarter.update(pair)
            elif number in (final - 4, final - 3):
                odds.semi.update(pair)
            elif number == final:
                odds.final.update(pair)
        for number in (final - 2, final - 1):
            if winners[number] is not None:
                odds.medal[winners[number]] += 1
        for athlete in (winners[final], losers[final]):
            if athlete is not None:
                odds.medal[athlete] += 1
        if winners[final] is not None:
            odds.gold[winners[final]] += 1
    return odds


def ratings_on(
    connection: Connection, athletes: set[int], day: date, weight: str
) -> dict[int, Rating]:
    """Each athlete's rating on `day` in `weight`, as the engine takes it (ajr.state_on:
    RD grown since their last contest, a move of weight's handicap; a new athlete's the
    initial one): the contest page's figures for a contest to come are the same."""
    rows = connection.execute(STATE_QUERY, {"ids": list(athletes), "day": day, "weight": weight})
    return {row.athlete_id: Rating(row.skill, row.rd, row.volatility) for row in rows}


def medal_chances(
    connection: Connection, today: date, params: RatingParams
) -> tuple[list[dict], list[dict]]:
    """Rows of ajr.medal_chance and of ajr.slot_chance for the tournaments from
    LIVE_GRACE ago to DRAW_LOOKAHEAD ahead."""
    weights: dict[tuple[int, str], list[Fight]] = defaultdict(list)
    starts: dict[int, date] = {}
    query = {"today": today, "live_grace": LIVE_GRACE, "lookahead": DRAW_LOOKAHEAD}
    for row in connection.execute(CONTESTS_QUERY, query):
        starts[row.competition_id] = row.date_from
        known = tuple(a for a in (row.blue_id, row.white_id) if a is not None)
        weights[(row.competition_id, row.weight)].append(
            Fight(row.fight_no, known, row.winner_id, row.id)
        )

    medal_rows, slot_rows = [], []
    for key in sorted(weights):
        competition_id, weight = key
        fights = weights[key]
        final = max(f.number for f in fights)
        if not is_bracket({f.number for f in fights}, final):
            logger.info(
                "Competition %s %s: not a drawn bracket, no chances", competition_id, weight
            )
            continue
        allf, byes = complete(fights, final)
        athletes = {a for f in allf for a in f.known} | set(byes.values())
        ratings = ratings_on(connection, athletes, max(today, starts[competition_id]), weight)
        chance = {
            (a, b): win_probability(ratings[a], ratings[b], params.rd_factor)
            for a in athletes
            for b in athletes
            if a < b
        }
        # the same numbers on every run of the job while nothing changes
        rng = random.Random(f"{competition_id} {weight}")
        odds = simulate(allf, chance, SIMULATIONS, rng, byes)

        def share(counter: Counter, athlete: int) -> float:
            return counter[athlete] / SIMULATIONS

        rows = medal_rows
        for a in athletes:
            rows.append(
                {"competition_id": competition_id, "weight": weight, "athlete_id": a,
                 "gold": share(odds.gold, a), "medal": share(odds.medal, a),
                 "quarter": share(odds.quarter, a), "semi": share(odds.semi, a),
                 "final": share(odds.final, a),
                 "rating": ratings[a].rating - params.rd_factor * ratings[a].rd}
            )  # fmt: skip
        slot_rows.extend(slots_of(competition_id, weight, final, allf, byes, odds, chance))
    return medal_rows, slot_rows


def slots_of(
    competition_id: int,
    weight: str,
    final: int,
    fights: list[Fight],
    byes: dict[int, int],
    odds: Odds,
    chance: dict[tuple[int, int], float],
) -> list[dict]:
    """ajr.slot_chance's rows of a weight: the bracket as it would go if every favourite
    won. A contest decided: its two athletes (wins: 1 and 0); a bye: its athlete; any
    other: its pair, known or the favourites of the contests before (losers, for the
    repechage and the bronze), with their chances against each other (wins) and of
    being in it at all (here, from the plays)."""

    def beats(a: int, b: int) -> float:
        return chance[(a, b)] if a < b else 1 - chance[(b, a)]

    rows: list[dict] = []
    winners: dict[int, int | None] = {}
    losers: dict[int, int | None] = {}
    for f in sorted(fights, key=lambda f: f.number):
        base = {"competition_id": competition_id, "weight": weight, "fight_no": f.number,
                "round": round_of(f.number, final), "contest_id": f.contest_id}  # fmt: skip
        pair = list(f.known) or ([byes[f.number]] if f.number in byes else [])
        for source, won in feeders(f.number, final):
            if len(pair) == 2:
                break
            athlete = (winners if won else losers).get(source)
            if athlete is not None and athlete not in pair:
                pair.append(athlete)
        if f.winner is not None:
            winner = f.winner
        elif len(pair) == 2:
            winner = max(pair, key=lambda a: beats(a, next(b for b in pair if b != a)))
        else:
            winner = pair[0] if pair else None
        winners[f.number] = winner
        losers[f.number] = next((a for a in pair if a != winner), None)
        if f.winner is not None:
            rows += [
                {**base, "athlete_id": a, "here": 1.0, "wins": float(a == f.winner)}
                for a in f.known
            ]
        elif len(pair) == 1:
            rows.append({**base, "athlete_id": pair[0], "here": 1.0, "wins": 1.0})
        elif len(pair) == 2:
            for a in pair:
                b = next(x for x in pair if x != a)
                here = 1.0 if a in f.known else odds.here[f.number][a] / SIMULATIONS
                rows.append({**base, "athlete_id": a, "here": here, "wins": beats(a, b)})
    return rows
