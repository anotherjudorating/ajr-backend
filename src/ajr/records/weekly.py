"""Records that need every week's tables: who was #1 of a weight and of pound for
pound and for how long (in total, and the longest run of weeks in a row), who stood
in the top 8 (the seeds of a World Championships or an Olympics), the nations' team
ratings and their deepest teams (their athletes in the top 10). Like "weeks at
No. 1" in tennis, the tables are looked at every Sunday; the ratings are built from
the first contest on, the records counted from RATINGS_SINCE, when they had settled.

A weight counts in a week only with at least MIN_TABLE athletes in its table, so
thin tables don't make champions of a handful of athletes.
"""

from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ajr.rating.engine import RatingParams
from ajr.rating.ranking import WEIGHTS, AthleteState, RankingParams, Standing, leaderboards
from ajr.records.queries import RATINGS_SINCE

MIN_TABLE = 20
TOP_8 = 8  # the weeks in the top: the seeds
TOP_10 = 10  # the deepest teams, and the top-10 places other records read
WEEK = timedelta(days=7)
SINCE = date.fromisoformat(RATINGS_SINCE)
GENDERS = {"male": WEIGHTS[:7], "female": WEIGHTS[7:]}
P4P_PACK = 7  # as api.p4p: the lead over the 7 best others of the own weight

# The tables listing the athlete from each row on (ajr/rating/ranking.py).
STATES_QUERY = text("""
    select rc.athlete_id, rc.fought_on, rc.weight, rc.rating_after, rc.rd_after,
           array_remove(array_append(
               coalesce((select array_agg(l.weight) from ajr.rating_listing l
                         where l.contest_id = rc.contest_id and l.athlete_id = rc.athlete_id),
                        '{}'),
               case when rc.listed_here then rc.weight end), null) as weights
    from ajr.rating_change rc
    where rc.weight is not null
    order by rc.seq
""")


class Runs:
    """Weeks in a row (at #1, in the top 8): each athlete's current run and best one."""

    def __init__(self) -> None:
        self.current: dict[int, tuple[int, date, date, Counter[str]]] = {}
        self.best: dict[int, tuple[int, date, date, str]] = {}  # weeks, from, to, weight

    def week(self, sunday: date, athletes: dict[int, str]) -> None:
        for athlete_id, weight in athletes.items():
            weeks, start, last, weights = self.current.get(athlete_id, (0, sunday, None, None))
            if last != sunday - WEEK:  # broken: a new run
                weeks, start, weights = 0, sunday, Counter()
            weights[weight] += 1
            weeks += 1
            self.current[athlete_id] = (weeks, start, sunday, weights)
            if weeks > self.best.get(athlete_id, (0,))[0]:
                self.best[athlete_id] = (weeks, start, sunday, weights.most_common(1)[0][0])

    def records(self) -> list[dict]:
        return [
            record(athlete_id=a, value=weeks, day=to, weight=weight, detail={"from": str(start)})
            for a, (weeks, start, to, weight) in self.best.items()
        ]


def weekly_records(
    connection: Connection,
    rating: RatingParams,
    ranking: RankingParams,
    today: date,
    places: list[tuple] | None = None,
) -> dict[str, list[dict]]:
    """The records; every Sunday's top 10 of every weight, (sunday, weight, athlete,
    place), goes to `places` (for the records of contests against a top-10 athlete)."""
    rows = connection.execute(STATES_QUERY).all()
    if not rows:
        return {}
    athletes = connection.execute(text("select id, country_id, dob_year from ajr.athlete")).all()
    country = {athlete.id: athlete.country_id for athlete in athletes}
    birth_year = {athlete.id: athlete.dob_year for athlete in athletes}

    weeks_at_1: Counter[int] = Counter()
    weights_at_1: dict[int, Counter[str]] = defaultdict(Counter)
    last_at_1: dict[int, date] = {}
    first_at_1: dict[int, tuple[date, str]] = {}
    weeks_p4p: Counter[int] = Counter()
    weights_p4p: dict[int, Counter[str]] = defaultdict(Counter)
    last_p4p: dict[int, date] = {}
    p4p_lead: dict[int, tuple[float, date, str]] = {}
    # a nation's records for men and women together (None) and for each gender
    scopes = {None: WEIGHTS, **GENDERS}
    team_best: dict[str | None, dict[int, tuple[float, date]]] = {g: {} for g in scopes}
    runs_at_1, runs_p4p, runs_top_8 = Runs(), Runs(), Runs()
    weeks_top_8: Counter[int] = Counter()
    weights_top_8: dict[int, Counter[str]] = defaultdict(Counter)
    last_top_8: dict[int, date] = {}
    # scope -> nation -> athletes, weights, sunday
    deepest: dict[str | None, dict[int, tuple[int, int, date]]] = {g: {} for g in scopes}

    states: dict[int, AthleteState] = {}
    first_day = rows[0].fought_on
    sunday = first_day + timedelta(days=6 - first_day.weekday())
    next_row = 0
    while sunday <= today:
        while next_row < len(rows) and rows[next_row].fought_on <= sunday:
            row = rows[next_row]
            states[row.athlete_id] = AthleteState(
                row.rating_after, row.rd_after, row.fought_on, row.weight, frozenset(row.weights)
            )
            next_row += 1
        if ranking.hide_after_days is not None:  # hidden ones come back with their next contest
            states = {
                athlete_id: state
                for athlete_id, state in states.items()
                if (sunday - state.last_day).days <= ranking.hide_after_days
            }
        if sunday < SINCE:  # the ratings are still settling: nothing to count yet
            sunday += WEEK
            continue
        tables = {
            weight: table
            for weight, table in leaderboards(states, sunday, rating, ranking).items()
            if len(table) >= MIN_TABLE
        }

        at_1: dict[int, str] = {}
        top_10: dict[int, str] = {}  # an athlete in two weights' top 10 counts once
        top_8: dict[int, str] = {}  # as the top 10
        for weight, table in tables.items():
            athlete_id = table[0].athlete_id
            weeks_at_1[athlete_id] += 1
            weights_at_1[athlete_id][weight] += 1
            last_at_1[athlete_id] = sunday
            first_at_1.setdefault(athlete_id, (sunday, weight))
            at_1.setdefault(athlete_id, weight)
            for place, standing in enumerate(table[:TOP_10], start=1):
                top_10.setdefault(standing.athlete_id, weight)
                if place <= TOP_8:
                    top_8.setdefault(standing.athlete_id, weight)
                if places is not None:
                    places.append((sunday, weight, standing.athlete_id, place))
        runs_at_1.week(sunday, at_1)
        runs_top_8.week(sunday, top_8)
        for athlete_id, weight in top_8.items():
            weeks_top_8[athlete_id] += 1
            weights_top_8[athlete_id][weight] += 1
            last_top_8[athlete_id] = sunday
        for scope, scope_weights in scopes.items():
            athletes_of: Counter[int] = Counter()
            weights_of: dict[int, set[str]] = defaultdict(set)
            for athlete_id, weight in top_10.items():
                nation = country.get(athlete_id)
                if nation is not None and weight in scope_weights:
                    athletes_of[nation] += 1
                    weights_of[nation].add(weight)
            for nation, count in athletes_of.items():
                if count > deepest[scope].get(nation, (0,))[0]:
                    deepest[scope][nation] = (count, len(weights_of[nation]), sunday)

        p4p_1: dict[int, str] = {}
        for weights in GENDERS.values():
            leader = p4p_leader({w: t for w, t in tables.items() if w in weights})
            if leader is None:
                continue
            athlete_id, gap, weight = leader
            weeks_p4p[athlete_id] += 1
            weights_p4p[athlete_id][weight] += 1
            last_p4p[athlete_id] = sunday
            p4p_1[athlete_id] = weight
            if athlete_id not in p4p_lead or gap > p4p_lead[athlete_id][0]:
                p4p_lead[athlete_id] = (gap, sunday, weight)
        runs_p4p.week(sunday, p4p_1)

        for scope, scope_weights in scopes.items():
            # team ratings only when every weight of the scope has a table
            if not all(w in tables for w in scope_weights):
                continue
            ratings = team_ratings({w: tables[w] for w in scope_weights}, country)
            for nation, score in ratings.items():
                best = team_best[scope]
                if nation not in best or score > best[nation][0]:
                    best[nation] = (score, sunday)

        sunday += WEEK

    def ages(firsts: dict[int, tuple[date, str]]) -> dict[int, tuple[int, date, str]]:
        return {
            athlete_id: (day.year - birth_year[athlete_id], day, weight)
            for athlete_id, (day, weight) in firsts.items()
            if birth_year.get(athlete_id) and 14 <= day.year - birth_year[athlete_id] <= 50
        }

    return {
        "longest_at_1": ranked(
            [
                record(athlete_id=a, value=weeks, day=last_at_1[a],
                       weight=weights_at_1[a].most_common(1)[0][0])
                for a, weeks in weeks_at_1.items()
            ],
            best="high",
        ),
        "youngest_1": ranked(
            [record(athlete_id=a, value=age, day=day, weight=weight)
             for a, (age, day, weight) in ages(first_at_1).items()],
            best="low",
        ),
        "longest_p4p_1": ranked(
            [
                record(athlete_id=a, value=weeks, day=last_p4p[a],
                       weight=weights_p4p[a].most_common(1)[0][0])
                for a, weeks in weeks_p4p.items()
            ],
            best="high",
        ),
        "longest_at_1_run": ranked(runs_at_1.records(), best="high"),
        "longest_p4p_1_run": ranked(runs_p4p.records(), best="high"),
        "most_weeks_in_top_8": ranked(
            [
                record(athlete_id=a, value=weeks, day=last_top_8[a],
                       weight=weights_top_8[a].most_common(1)[0][0])
                for a, weeks in weeks_top_8.items()
            ],
            best="high",
        ),
        "most_weeks_in_top_8_run": ranked(runs_top_8.records(), best="high"),
        "biggest_p4p_lead": ranked(
            [record(athlete_id=a, value=gap, day=day, weight=weight)
             for a, (gap, day, weight) in p4p_lead.items()],
            best="high",
        ),
        "highest_team_rating": [
            row
            for g, best in team_best.items()
            for row in ranked(
                [record(country_id=n, value=score, day=day, gender=g)
                 for n, (score, day) in best.items()],
                best="high",
            )
        ],
        "deepest_team": [
            row
            for g, best in deepest.items()
            for row in ranked(
                [record(country_id=n, value=count, day=day, detail={"weights": weights}, gender=g)
                 for n, (count, weights, day) in best.items()],
                best="high",
            )
        ],
    }  # fmt: skip


def p4p_leader(tables: dict[str, list[Standing]]) -> tuple[int, float, str] | None:
    """Pound for pound #1 of these weights, as api.p4p ranks it: of the top 3 of every
    weight, the biggest lead over the average of the 7 best others of the own weight."""
    best = None
    for weight, table in tables.items():
        for candidate in table[:3]:
            others = [s.score for s in table if s.athlete_id != candidate.athlete_id][:P4P_PACK]
            if not others:  # nobody to be ahead of
                continue
            gap = candidate.score - sum(others) / len(others)
            if best is None or gap > best[1]:
                best = (candidate.athlete_id, gap, weight)
    return best


def team_ratings(tables: dict[str, list[Standing]], country: dict[int, int | None]) -> dict:
    """Nation -> the average score of its best athlete in every weight; an empty weight
    counts as the last place of its table (as api.teams does)."""
    best: dict[int, dict[str, float]] = defaultdict(dict)
    for weight, table in tables.items():
        for standing in table:  # best first
            nation = country.get(standing.athlete_id)
            if nation is not None and weight not in best[nation]:
                best[nation][weight] = standing.score
    last_place = {weight: table[-1].score for weight, table in tables.items()}
    return {
        nation: sum(by_weight.get(weight, score) for weight, score in last_place.items())
        / len(last_place)
        for nation, by_weight in best.items()
    }


def record(**fields) -> dict:
    return {"athlete_id": None, "country_id": None, "weight": None, "detail": None} | fields


def ranked(rows: list[dict], best: str, top: int = 500) -> list[dict]:
    """Best first, with places (ties share one), the first `top` rows."""
    sign = -1 if best == "high" else 1
    rows = sorted(rows, key=lambda row: (sign * row["value"], row["day"]))  # equals: earlier first
    place = 0
    for index, row in enumerate(rows[:top]):
        if index == 0 or row["value"] != rows[index - 1]["value"]:
            place = index + 1
        row["place"] = place
    return rows[:top]
