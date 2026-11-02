"""The calls of a load test, picked from the API's own answers."""

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from ajr.loadtest.run import Api

WEIGHTS = [
    "-60", "-66", "-73", "-81", "-90", "-100", "+100",
    "-48", "-52", "-57", "-63", "-70", "-78", "+78",
]  # fmt: skip
SEARCHES = [
    "abe",
    "kim",
    "kim min",
    "heyd",
    "jap",
    "JPN",
    "tokyo",
    "grand slam",
    "x",
    "",
    "zzzqqq",
    "a" * 60,
]


@dataclass(frozen=True)
class Case:
    function: str
    params: dict = field(default_factory=dict)
    writes: bool = False  # changes the database: not on production

    @property
    def key(self) -> str:
        args = ", ".join(f"{k}={v!r}" for k, v in self.params.items())
        return f"{self.function}({args})"


def days(today: date) -> list[str]:
    """Today (the snapshot) and days back to before the data."""
    return [
        d.isoformat()
        for d in (
            today,
            today - timedelta(days=90),
            date(2024, 6, 1),
            date(2018, 1, 7),
            date(2012, 6, 3),
            date(2009, 6, 7),
            date(2005, 1, 1),
        )
    ]


async def build(api: Api, rng: random.Random) -> list[Case]:
    """Every api function, with the arguments and the rows that make it work hardest
    or differently: a leader and an athlete hidden for years, the World Championships
    and a small Open, a big nation and a tiny one, empty and odd searches."""
    today = date.fromisoformat((await api.json("last_update"))[:10])
    cases = [Case("last_update"), Case("nations")]

    # rankings, today and in the past
    for day in days(today):
        cases += [Case("leaderboard", {"weight": w, "day": day}) for w in WEIGHTS]
        cases += [Case("teams", {"kind": k, "day": day}) for k in ("men", "women", "mixed")]
        cases += [Case("p4p", {"gender": g, "day": day}) for g in ("men", "women")]

    # athletes: a leader, the middle of a table, the hidden, one contest, many contests
    board = await api.json("leaderboard", {"weight": "-73"})
    listing = await api.json("athletes", {"sort": "name-asc", "top": 1000, "skip": 5000})
    athletes = {
        board[0]["athlete_id"],
        board[len(board) // 2]["athlete_id"],
        next(r["id"] for r in listing if r["place"] is None),
        next((r["id"] for r in listing if r["contests"] == 1), listing[0]["id"]),
        max(listing, key=lambda r: r["contests"])["id"],
        0,  # none
    }
    for athlete in sorted(athletes):
        cases.append(Case("athlete", {"athlete_id": athlete}))
        for weight in (None, "-73", "+78"):
            cases.append(Case("athlete_history", {"athlete_id": athlete, "only_weight": weight}))

    # tournaments and contests: this year's biggest and smallest, an old one, a coming one
    year = await api.json("competitions", {"for_year": today.year})
    old = await api.json("competitions", {"for_year": 2010})
    coming = await api.json("upcoming", {"top": 3})
    tournaments = {
        max(year, key=lambda c: c["contests"] or 0)["id"],
        min(year, key=lambda c: c["contests"] or 0)["id"],
        max(old, key=lambda c: c["contests"] or 0)["id"],
        *(c["id"] for c in coming[:1]),
        0,  # none
    }
    contests: set[int] = {0}
    for tournament in sorted(tournaments):
        cases += [
            Case(f, {"competition_id": tournament})
            for f in ("competition", "competition_results", "competition_chances")
        ]
        for weight in (None, "-73", "+100"):
            cases.append(
                Case("competition_contests", {"competition_id": tournament, "only_weight": weight})
            )
        if tournament:
            fights = await api.json("competition_contests", {"competition_id": tournament})
            contests |= {f["contest_id"] for f in fights[:1]}  # the final
            walkover = next((f["contest_id"] for f in fights if not f["real_fight"]), None)
            if walkover:  # a bye or a 0:00 walkover
                contests.add(walkover)
    cases += [Case("contest", {"contest_id": c}) for c in sorted(contests)]

    # Explore
    for for_year in (today.year, 2015, 2009, None):
        cases.append(Case("competitions", {"for_year": for_year}))
    cases += [
        Case("competitions", {"for_year": today.year, "ranks": r})
        for r in (["Grand Slam"], ["Grand Slam", "Grand Prix"])
    ]
    competition = max(year, key=lambda c: c["contests"] or 0)["id"]
    contest_filters = [
        {},
        {"only_weight": "-73"},
        {"competition_id": competition},
        {"upsets": True},
        {"q": "abe"},
        {"q": "kim min"},
        {"sort": "date-asc"},
        {"sort": "chance-asc"},
        {"only_weight": "-73", "upsets": True, "q": "a"},
    ]
    for filters in contest_filters:
        for skip in (0, 500):
            cases.append(Case("contests", {"for_year": today.year, **filters, "skip": skip}))
    cases.append(Case("contests", {"for_year": 2012, "sort": "chance-asc"}))
    athlete_filters = [
        {},
        {"q": "abe"},
        {"country": "JPN"},
        {"gender": "female"},
        {"only_weight": "-73"},
        {"q": "a", "country": "FRA", "gender": "male", "only_weight": "-81"},
    ]
    for filters in athlete_filters:
        for sort in ("name-asc", "name-desc", "age-asc", "age-desc", "rating-desc"):
            cases.append(Case("athletes", {**filters, "sort": sort}))
    cases += [Case("athletes", {"skip": skip, "top": 100}) for skip in (0, 10000, 23500)]

    # nations: the biggest, a middle one, a tiny one, a past one, none
    nations = sorted(await api.json("nations"), key=lambda n: -n["athletes"])
    codes = {
        nations[0]["country"],
        nations[len(nations) // 2]["country"],
        nations[-1]["country"],
        "URS",
        "XXX",
    }
    for code in sorted(codes):
        cases += [Case(f, {"ioc": code}) for f in ("country", "country_history", "country_leaders")]
        cases.append(Case("country_tournaments", {"ioc": code, "top": 5}))

    # home
    cases += [Case("home_leaders", {"top": t}) for t in (7, 1)]
    cases += [Case("biggest_movers", {"top": 5, "pool": p}) for p in (20, 100)]
    cases += [Case("recent_upsets", {"days": d, "top": 4}) for d in (30, 365)]
    cases += [Case("upcoming", {"top": t}) for t in (3, 50)]

    # records: the overview, then every record by gender and a weight
    cases += [
        Case("records", {"top": t, "for_gender": g})
        for t in (10, 1)
        for g in (None, "male", "female")
    ]
    names = sorted({r["record"] for r in await api.json("records", {"top": 1})})
    for name in names:
        cases += [Case("record", {"name": name, "for_gender": g}) for g in (None, "male", "female")]
        cases.append(Case("record", {"name": name, "only_weight": "-73"}))

    # search and head-to-head
    cases += [Case("search", {"q": q}) for q in SEARCHES]
    cases += [
        Case("search_athletes", {"q": q, "only_weight": w, "top": 8})
        for q in SEARCHES
        for w in (None, "-73")
    ]
    leaders = [r["athlete_id"] for r in board[:4]]
    cases += [Case("popular_matchups", {"fallback": leaders, "top": t}) for t in (5, 1)]
    a, b = sorted(rng.sample(leaders, 2))
    cases.append(Case("count_matchup", {"a": a, "b": b}, writes=True))
    return cases
