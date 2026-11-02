"""Records that need every week's tables: who was #1 of a weight and of pound for
pound, and the nations' team ratings. Like "weeks at No. 1" in tennis, the tables
are looked at every Sunday; the ratings are built from the first contest on, the
records counted from RATINGS_SINCE, when they had settled.

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
WEEK = timedelta(days=7)
SINCE = date.fromisoformat(RATINGS_SINCE)
GENDERS = {"male": WEIGHTS[:7], "female": WEIGHTS[7:]}
P4P_PACK = 7  # as api.p4p: the lead over the 7 best others of the own weight

STATES_QUERY = text("""
    select athlete_id, fought_on, weight, rating_after, rd_after
    from ajr.rating_change
    where weight is not null
    order by seq
""")


def weekly_records(
    connection: Connection,
    rating: RatingParams,
    ranking: RankingParams,
    today: date,
    nation_history: list[dict] | None = None,
) -> dict[str, list[dict]]:
    """The records; every week's mixed nations ranking goes to `nation_history`."""
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
    first_p4p: dict[int, tuple[date, str]] = {}
    p4p_lead: dict[int, tuple[float, date, str]] = {}
    nation_weeks: Counter[int] = Counter()
    nation_last: dict[int, date] = {}
    team_best: dict[int, tuple[float, date]] = {}

    states: dict[int, AthleteState] = {}
    first_day = rows[0].fought_on
    sunday = first_day + timedelta(days=6 - first_day.weekday())
    next_row = 0
    while sunday <= today:
        while next_row < len(rows) and rows[next_row].fought_on <= sunday:
            row = rows[next_row]
            states[row.athlete_id] = AthleteState(
                row.rating_after, row.rd_after, row.fought_on, row.weight
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

        for weight, table in tables.items():
            athlete_id = table[0].athlete_id
            weeks_at_1[athlete_id] += 1
            weights_at_1[athlete_id][weight] += 1
            last_at_1[athlete_id] = sunday
            first_at_1.setdefault(athlete_id, (sunday, weight))

        for weights in GENDERS.values():
            leader = p4p_leader({w: t for w, t in tables.items() if w in weights})
            if leader is None:
                continue
            athlete_id, gap, weight = leader
            weeks_p4p[athlete_id] += 1
            weights_p4p[athlete_id][weight] += 1
            last_p4p[athlete_id] = sunday
            first_p4p.setdefault(athlete_id, (sunday, weight))
            if athlete_id not in p4p_lead or gap > p4p_lead[athlete_id][0]:
                p4p_lead[athlete_id] = (gap, sunday, weight)

        if len(tables) == 14:  # team ratings only when every weight has a table
            ratings = team_ratings(tables, country)
            if nation_history is not None:
                nation_history.extend(nations_ranking(ratings, sunday))
            best_nation = max(ratings, key=ratings.get)
            nation_weeks[best_nation] += 1
            nation_last[best_nation] = sunday
            for nation, score in ratings.items():
                if nation not in team_best or score > team_best[nation][0]:
                    team_best[nation] = (score, sunday)

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
        "youngest_p4p_1": ranked(
            [record(athlete_id=a, value=age, day=day, weight=weight)
             for a, (age, day, weight) in ages(first_p4p).items()],
            best="low",
        ),
        "biggest_p4p_lead": ranked(
            [record(athlete_id=a, value=gap, day=day, weight=weight)
             for a, (gap, day, weight) in p4p_lead.items()],
            best="high",
        ),
        "highest_team_rating": ranked(
            [record(country_id=n, value=score, day=day) for n, (score, day) in team_best.items()],
            best="high",
        ),
        "longest_at_1_nation": ranked(
            [record(country_id=n, value=weeks, day=nation_last[n])
             for n, weeks in nation_weeks.items()],
            best="high",
        ),
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


def nations_ranking(ratings: dict[int, float], day: date) -> list[dict]:
    """The nations of a week, best first; equal ratings share a place."""
    rows = []
    for nation, score in sorted(ratings.items(), key=lambda item: -item[1]):
        rating = round(score)
        place = rows[-1]["place"] if rows and rows[-1]["rating"] == rating else len(rows) + 1
        rows.append({"day": day, "country_id": nation, "place": place, "rating": rating})
    return rows


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
