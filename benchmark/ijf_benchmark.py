"""Our rating against the IJF World Ranking List and the classic baselines, on the same
contests: which one predicts the winner better.

Models (each gives the blue side's chance before the contest):
- coin: 0.5;
- IJF WRL: P = sigmoid(k * (log(pts_blue + 1) - log(pts_white + 1))), the points in the
  contest's weight in the latest weekly list published on or before the tournament's
  first day (a version YYYY_N is the list of the Monday of ISO week N, with the results
  up to the Sunday before); k fitted on the calibration window;
- Elo: 1500 at the start, K = 32, updated after every contest;
- Glicko-2 as in the paper (Glickman, 2013): monthly rating periods, the contests of a
  month rated together from the ratings at its start, the uncertainty grown only
  through the volatility (a period without contests: phi = sqrt(phi^2 + sigma^2)), the
  chance of a contest from both sides' uncertainty (Glicko, 1999); tau 0.5, 1500 /
  350 / 0.06 at the start;
- ours: the engine as on the site, the chance from the rating (skill - 1 * RD) of each
  side and both RDs.
Elo and ours update after every contest (live), as they are used; the paper's
Glicko-2 within a month and the WRL within a week do not.

Windows: the history before the WRL archive is warm-up (ratings only); the WRL's first
months are the calibration of k; the test is from TEST_FROM to TEST_TO. Judged: real
fights (the rating's own set) without byes and 0:00 contests, for every model alike.

Inputs (benchmark/data/): contests.csv.gz, the snapshot of our contests the rating
takes, in its order (written from a database with --snapshot); wrl_history.csv.gz,
the IJF's weekly lists (fetch_wrl_history.py; not in git: the IJF's data). Outputs:
RESULTS.md, results.json and data/predictions.csv.gz (every judged contest with each
model's chance), so every number can be traced.

    cd benchmark
    uv run python ijf_benchmark.py                 # from the snapshot
    DATABASE_URL=… uv run python ijf_benchmark.py --snapshot   # take a new one first
"""

import argparse
import bisect
import csv
import gzip
import io
import json
import math
import os
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import create_engine, text

from ajr.rating.engine import ContestRecord, RatingParams, load_contests, run
from ajr.rating.glicko2 import SCALE, Rating, g, update

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SNAPSHOT_COLUMNS = [
    "contest_id",
    "day",
    "weight",
    "blue_id",
    "white_id",
    "blue_won",
    "bye",
    "walkover",
    "competition_id",
    "major",
    "stage",
    "rank_name",
    "date_from",
]

CALIBRATION_FROM = date(2025, 3, 17)  # the WRL archive's first list (2025 week 12)
TEST_FROM = date(2025, 7, 1)
TEST_TO = date(2026, 11, 8)
ELO_K = 32
# our chance is from the rating, skill - 1 * RD of each side (k = 0, 1, 2, 3 measured on
# 2026-11-11: 1 the best, 3 overconfident)
RD_SHIFT = 1
MODELS = ["coin", "ijf", "elo", "glicko2", "ours"]
NAMES = {"coin": "Coin", "ijf": "IJF WRL", "elo": "Elo", "glicko2": "Glicko-2", "ours": "Ours"}
MAJORS = {"Olympic Games", "Masters"}
MEDAL_STAGES = {"F", "1/2", "BR"}
BOOT = 1000
EPS = 1e-12

FACTS = text("""
    select ct.id, coalesce(ct.stage, '') as stage, coalesce(cm.rank_name, '') as rank_name,
           cm.date_from
    from ajr.contest ct join ajr.competition cm on cm.id = ct.competition_id
""")


def level(rank: str) -> str:
    if rank in MAJORS or rank.startswith("World Championships"):
        return "Olympics, Worlds, Masters"
    if rank == "Grand Slam":
        return "Grand Slam"
    if rank == "Grand Prix":
        return "Grand Prix"
    if rank.endswith("Championships"):
        return "Continental championships"
    return "Opens and cups"


def wrl_lists(path: str):
    """{(athlete, weight): ([monday…], [points…])} of the seniors' lists, by date."""
    rows = defaultdict(list)
    with gzip.open(path, "rt") as f:
        for r in csv.DictReader(f):
            if r["age"] != "Seniors" or not r["year"]:
                continue
            monday = date.fromisocalendar(int(r["year"]), int(r["week"]), 1)
            rows[(int(r["athlete_id"]), r["weight"])].append((monday, int(r["points"])))
    out = {}
    for key, items in rows.items():
        items.sort()
        out[key] = ([d for d, _ in items], [p for _, p in items])
    return out


def points(lists, athlete: int, weight: str, day: date) -> int:
    found = lists.get((athlete, weight))
    if not found:
        return 0
    i = bisect.bisect_right(found[0], day) - 1
    return found[1][i] if i >= 0 else 0


def elo_chances(contests) -> list[float]:
    ratings: dict[int, float] = {}
    out = []
    for c in contests:
        a, b = ratings.get(c.blue_id, 1500.0), ratings.get(c.white_id, 1500.0)
        p = 1 / (1 + 10 ** ((b - a) / 400))
        out.append(p)
        s = 1.0 if c.blue_won else 0.0
        ratings[c.blue_id] = a + ELO_K * (s - p)
        ratings[c.white_id] = b + ELO_K * ((1 - s) - (1 - p))
    return out


def chance(o, shift: float) -> float:
    """The blue side's chance from the ratings (skill - shift * RD) and both RDs."""
    a, b = o.blue_before, o.white_before
    phi = math.hypot(a.rd, b.rd) / SCALE
    gap = (a.rating - shift * a.rd) - (b.rating - shift * b.rd)
    return 1 / (1 + math.exp(-g(phi) * gap / SCALE))


def glicko_paper_chances(contests, tau: float = 0.5) -> list[float]:
    """Glicko-2 by the paper: a rating period a calendar month, by the contest's day (a
    tournament across the turn of a month falls in both)."""
    state: dict[int, Rating] = {}
    last: dict[int, int] = {}  # the last period an athlete was rated in
    out: list[float] = [0.0] * len(contests)

    def period(day: date) -> int:
        return day.year * 12 + day.month

    def at_start(athlete: int, p: int) -> Rating:
        r = state.get(athlete)
        if r is None:
            return Rating(1500.0, 350.0, 0.06)
        missed = max(0, p - last[athlete] - 1)  # periods without contests since: RD grows
        rd = min(math.sqrt(r.rd**2 + missed * (r.volatility * SCALE) ** 2), 350.0)
        return Rating(r.rating, rd, r.volatility)

    # every month's contests together, the months in order (the list is in the rating's
    # order, by the tournaments' first days: a month's contests are not all in a row)
    months: dict[int, list[int]] = defaultdict(list)
    for i, c in enumerate(contests):
        months[period(c.day)].append(i)
    for p in sorted(months):
        pre: dict[int, Rating] = {}
        results: dict[int, list] = defaultdict(list)
        for i in months[p]:
            c = contests[i]
            for a in (c.blue_id, c.white_id):
                if a not in pre:
                    pre[a] = at_start(a, p)
            a, b = pre[c.blue_id], pre[c.white_id]
            phi = math.hypot(a.rd, b.rd) / SCALE
            out[i] = 1 / (1 + math.exp(-g(phi) * (a.rating - b.rating) / SCALE))
            s = 1.0 if c.blue_won else 0.0
            results[c.blue_id].append((b, s))
            results[c.white_id].append((a, 1 - s))
        for a, games in results.items():
            new = update(pre[a], games, tau)
            state[a] = Rating(new.rating, min(new.rd, 350.0), new.volatility)
            last[a] = p
    return out


def log_loss(p: float, won: bool) -> float:
    q = p if won else 1 - p
    return -math.log(min(max(q, EPS), 1 - EPS))


def scores(rows, model):
    n = len(rows)
    if not n:
        return None
    ll = sum(log_loss(r[model], r["won"]) for r in rows) / n
    brier = sum((r[model] - (1.0 if r["won"] else 0.0)) ** 2 for r in rows) / n
    acc = sum(0.5 if r[model] == 0.5 else float((r[model] > 0.5) == r["won"]) for r in rows) / n
    return {"log loss": ll, "Brier": brier, "accuracy": acc}


def bootstrap_diff(rows, a, b, seed=1):
    """The difference in log loss a - b, and its 95% interval, resampling tournaments."""
    by = defaultdict(list)
    for r in rows:
        by[r["competition"]].append(log_loss(r[a], r["won"]) - log_loss(r[b], r["won"]))
    groups = list(by.values())
    total = sum(sum(g) for g in groups) / sum(len(g) for g in groups)
    rng = random.Random(seed)
    sample = []
    for _ in range(BOOT):
        pick = [groups[rng.randrange(len(groups))] for _ in groups]
        sample.append(sum(sum(g) for g in pick) / sum(len(g) for g in pick))
    sample.sort()
    return total, sample[int(0.025 * BOOT)], sample[int(0.975 * BOOT) - 1]


def binomial_two_sided(k: int, n: int) -> float:
    """Exact McNemar: P(as extreme) under p = 0.5."""
    if n == 0:
        return 1.0
    k = min(k, n - k)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def gz_text(path: str):
    """A gzip text file written without a timestamp: the same rows, the same bytes."""
    return io.TextIOWrapper(gzip.GzipFile(path, "wb", mtime=0), newline="")


def take_snapshot(path: str) -> None:
    """Our contests as the rating takes them, with the facts the slices need."""
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as connection:
        contests = load_contests(connection, real_fights_only=True)
        facts = {r.id: r for r in connection.execute(FACTS)}
    with gz_text(path) as f:
        w = csv.writer(f)
        w.writerow(SNAPSHOT_COLUMNS)
        for c in contests:
            x = facts[c.contest_id]
            w.writerow(
                [
                    c.contest_id,
                    c.day,
                    c.weight,
                    c.blue_id,
                    c.white_id,
                    int(bool(c.blue_won)),
                    int(bool(c.bye)),
                    int(bool(c.walkover)),
                    c.competition_id,
                    int(bool(c.major)),
                    x.stage,
                    x.rank_name,
                    x.date_from,
                ]
            )
    print(f"snapshot: {len(contests)} contests in {path}", flush=True)
    # today's listed athletes with their skill and RD, for the slider's tables
    with (
        engine.connect() as connection,
        gz_text(os.path.join(DATA, "tables.csv.gz")) as f,
    ):
        w = csv.writer(f)
        w.writerow(["weight", "athlete_id", "name", "country", "skill", "rd"])
        for r in connection.execute(TABLES):
            w.writerow(
                [r.weight, r.athlete_id, r.name, r.country, round(r.skill, 3), round(r.rd, 3)]
            )


def read_snapshot(path: str):
    contests, facts = [], {}
    with gzip.open(path, "rt") as f:
        for r in csv.DictReader(f):
            c = ContestRecord(
                int(r["contest_id"]),
                date.fromisoformat(r["day"]),
                r["weight"],
                int(r["blue_id"]),
                int(r["white_id"]),
                r["blue_won"] == "1",
                r["bye"] == "1",
                r["walkover"] == "1",
                int(r["competition_id"]),
                r["major"] == "1",
            )
            contests.append(c)
            facts[c.contest_id] = Facts(
                r["stage"], r["rank_name"], date.fromisoformat(r["date_from"])
            )
    return contests, facts


@dataclass
class Facts:
    stage: str
    rank_name: str
    date_from: date


# The methodology's slider: the rating as skill - n * RD, n from 0 to 5. For each n, how
# well the chance from it predicts (the test's contests) and the tables it makes (today's
# listed athletes resorted), into data/rd_shift.json.
SWEEP = [x / 2 for x in range(11)]
CAL_BINS = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]


def sweep(outcomes, test, slices) -> None:
    tables = defaultdict(list)
    with gzip.open(os.path.join(DATA, "tables.csv.gz"), "rt") as f:
        for r in csv.DictReader(f):
            tables[r["weight"]].append(r)
    out = {"n": SWEEP, "metrics": [], "tables": {}}
    picked = {
        "all": test,
        "newcomers": slices["Experience: one side < 10 contests"],
        "medal_rounds": slices["Medal rounds of majors (OG, Worlds, Masters, GS)"],
    }
    for n in SWEEP:
        entry = {"n": n}
        for name, sub in picked.items():
            rows = [
                {"p": chance(outcomes[r["i"]], n), "won": r["won"], "ijf": r["ijf"]} for r in sub
            ]
            m = scores(rows, "p")
            entry[name] = {k: round(v, 5) for k, v in m.items()}
            if name == "all":
                cal = []
                for lo, hi in CAL_BINS:
                    fav = [
                        (max(r["p"], 1 - r["p"]), (r["p"] > 0.5) == r["won"])
                        for r in rows
                        if r["p"] != 0.5 and lo <= max(r["p"], 1 - r["p"]) < hi
                    ]
                    cal.append(
                        {
                            "from": lo,
                            "to": min(hi, 1.0),
                            "n": len(fav),
                            "promised": round(sum(p for p, _ in fav) / len(fav), 4)
                            if fav
                            else None,
                            "won": round(sum(w for _, w in fav) / len(fav), 4) if fav else None,
                        }
                    )
                entry["calibration"] = cal
                split = [r for r in rows if r["ijf"] != 0.5 and (r["p"] > 0.5) != (r["ijf"] > 0.5)]
                right = sum((r["p"] > 0.5) == r["won"] for r in split)
                entry["against_ijf"] = {
                    "n": len(split),
                    "right": round(right / len(split), 4) if split else None,
                }
        out["metrics"].append(entry)
    for weight, rows in tables.items():
        out["tables"][weight] = {
            str(n): [
                {
                    "athlete_id": int(r["athlete_id"]),
                    "name": r["name"],
                    "country": r["country"],
                    "rating": round(float(r["skill"]) - n * float(r["rd"])),
                }
                for r in sorted(rows, key=lambda r: -(float(r["skill"]) - n * float(r["rd"])))[:10]
            ]
            for n in SWEEP
        }
    with open(os.path.join(DATA, "rd_shift.json"), "w") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    print(
        "rd_shift.json:",
        ", ".join(f"n={e['n']} {e['all']['log loss']:.4f}" for e in out["metrics"]),
        flush=True,
    )


TABLES = text("""
    select weight, athlete_id, concat_ws(' ', family_name, given_name) as name, country,
           rating as skill, rd
    from ajr.leaderboard_snapshot
""")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--snapshot", action="store_true", help="take data/contests.csv.gz from DATABASE_URL first"
    )
    args = parser.parse_args()
    snapshot = os.path.join(DATA, "contests.csv.gz")
    if args.snapshot:
        take_snapshot(snapshot)
    contests, facts = read_snapshot(snapshot)
    print(f"contests {len(contests)}", flush=True)

    outcomes = run(contests, RatingParams())  # the job's settings
    ours = [chance(o, RD_SHIFT) for o in outcomes]
    glicko = glicko_paper_chances(contests)
    elo = elo_chances(contests)
    lists = wrl_lists(os.path.join(DATA, "wrl_history.csv.gz"))

    rows = []
    seen: dict[int, int] = defaultdict(int)  # contests before, any weight
    weight_of: dict[int, str] = {}  # the weight of the latest contest
    in_weight: dict[tuple[int, str], int] = defaultdict(int)  # contests in this weight
    moved: dict[int, bool] = {}  # fought in another weight before this one
    for i, c in enumerate(contests):
        f = facts[c.contest_id]
        start = f.date_from
        for side in (c.blue_id, c.white_id):
            if side in weight_of and weight_of[side] != c.weight:
                moved[side] = True
        fresh_move = any(
            moved.get(s) and in_weight[(s, c.weight)] < 5 for s in (c.blue_id, c.white_id)
        )
        if not c.bye and not c.walkover and start >= CALIBRATION_FROM and start <= TEST_TO:
            pb, pw = (
                points(lists, c.blue_id, c.weight, start),
                points(lists, c.white_id, c.weight, start),
            )
            rows.append(
                {
                    "i": i,
                    "contest_id": c.contest_id,
                    "competition": c.competition_id,
                    "start": start,
                    "won": c.blue_won,
                    "coin": 0.5,
                    "elo": elo[i],
                    "glicko2": glicko[i],
                    "ours": ours[i],
                    "pts": (pb, pw),
                    "stage": f.stage,
                    "level": level(f.rank_name),
                    "experience": min(seen[c.blue_id], seen[c.white_id]),
                    "moved": fresh_move,
                }
            )
        for side in (c.blue_id, c.white_id):
            seen[side] += 1
            in_weight[(side, c.weight)] += 1
            weight_of[side] = c.weight

    def ijf(k, pts):
        a, b = math.log(pts[0] + 1), math.log(pts[1] + 1)
        return 1 / (1 + math.exp(-k * (a - b)))

    calibration = [r for r in rows if r["start"] < TEST_FROM]
    best = min(
        (sum(log_loss(ijf(k / 100, r["pts"]), r["won"]) for r in calibration), k / 100)
        for k in range(5, 301)
    )
    k = best[1]
    for r in rows:
        r["ijf"] = ijf(k, r["pts"])
        r["ijf1"] = ijf(1.0, r["pts"])
    test = [r for r in rows if r["start"] >= TEST_FROM]
    print(f"calibration {len(calibration)} contests, k = {k}; test {len(test)}", flush=True)

    def gap(r):
        p = max(r["ours"], 1 - r["ours"])
        return (
            "close (ours < 60%)" if p < 0.6 else "middle (60–75%)" if p < 0.75 else "clear (75%+)"
        )

    slices = {"All": test}
    for name in ("close (ours < 60%)", "middle (60–75%)", "clear (75%+)"):
        slices[f"Strength gap: {name}"] = [r for r in test if gap(r) == name]
    for name in (
        "Olympics, Worlds, Masters",
        "Grand Slam",
        "Grand Prix",
        "Continental championships",
        "Opens and cups",
    ):
        slices[f"Level: {name}"] = [r for r in test if r["level"] == name]
    big = {"Olympics, Worlds, Masters", "Grand Slam"}
    slices["Medal rounds of majors (OG, Worlds, Masters, GS)"] = [
        r for r in test if r["level"] in big and r["stage"] in MEDAL_STAGES
    ]
    slices["Experience: one side < 10 contests"] = [r for r in test if r["experience"] < 10]
    slices["Experience: both 10+"] = [r for r in test if r["experience"] >= 10]
    slices["No WRL points: one side has 0"] = [r for r in test if 0 in r["pts"]]
    slices["After a change of weight (first 5 in the new one)"] = [r for r in test if r["moved"]]

    result = {"k": k, "calibration": len(calibration), "test": len(test), "slices": {}}
    lines = [
        "| Metric | Slice | n | " + " | ".join(NAMES[m] for m in MODELS) + " |",
        "|---|---|---:|" + "---:|" * len(MODELS),
    ]
    for name, sub in slices.items():
        per = {m: scores(sub, m) for m in MODELS}
        result["slices"][name] = {"n": len(sub), **{m: per[m] for m in MODELS}}
        if not sub:
            continue
        for metric in ("log loss", "Brier", "accuracy"):
            values = [per[m][metric] for m in MODELS]
            better = min if metric != "accuracy" else max
            top = better(values[1:])  # the coin is the floor, not a contender
            cells = [f"**{v:.4f}**" if v == top else f"{v:.4f}" for v in values]
            lines.append(f"| {metric} | {name} | {len(sub)} | " + " | ".join(cells) + " |")

    # paired differences in log loss, ours against each, with tournaments resampled
    diffs = ["", "| Ours minus | Slice | Δ log loss ×1000 | 95% interval |", "|---|---|---:|---|"]
    for name in (
        "All",
        "Medal rounds of majors (OG, Worlds, Masters, GS)",
        "Experience: one side < 10 contests",
    ):
        for other in ("ijf", "elo", "glicko2"):
            d, lo, hi = bootstrap_diff(slices[name], "ours", other)
            diffs.append(
                f"| {NAMES[other]} | {name} | {d * 1000:+.1f}"
                f" | [{lo * 1000:+.1f}, {hi * 1000:+.1f}] |"
            )

    # calibration: the favourite's predicted chance against how often it won
    cal = [
        "",
        "| Favourite's chance | " + " | ".join(NAMES[m] for m in MODELS[1:]) + " |",
        "|---|" + "---|" * (len(MODELS) - 1),
    ]
    bins = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]
    for lo, hi in bins:
        cells = []
        for m in MODELS[1:]:
            fav = [
                (max(r[m], 1 - r[m]), r["won"] == (r[m] > 0.5))
                for r in test
                if r[m] != 0.5 and lo <= max(r[m], 1 - r[m]) < hi
            ]
            cells.append(
                f"{sum(p for p, _ in fav) / len(fav) * 100:.1f}%"
                f" → won {sum(w for _, w in fav) / len(fav) * 100:.1f}% (n={len(fav)})"
                if fav
                else "–"
            )
        cal.append(f"| {int(lo * 100)}–{min(int(hi * 100), 100)}% | " + " | ".join(cells) + " |")

    # where ours and the WRL name different favourites (the WRL with no tie)
    split = [r for r in test if r["ijf"] != 0.5 and (r["ours"] > 0.5) != (r["ijf"] > 0.5)]
    ours_right = sum((r["ours"] > 0.5) == r["won"] for r in split)
    p_value = binomial_two_sided(ours_right, len(split))
    per_split = {m: scores(split, m) for m in MODELS}
    dis = [
        "",
        f"Disagreements with the WRL: {len(split)} contests; ours right in {ours_right} "
        f"({ours_right / len(split) * 100:.1f}%), the WRL in {len(split) - ours_right};"
        f" exact McNemar p = {p_value:.2g}.",
        "",
        "| Metric | " + " | ".join(NAMES[m] for m in MODELS) + " |",
        "|---|" + "---:|" * len(MODELS),
    ]
    for metric in ("log loss", "accuracy"):
        dis.append(
            f"| {metric} | " + " | ".join(f"{per_split[m][metric]:.4f}" for m in MODELS) + " |"
        )
    ijf1 = scores(test, "ijf1")
    note = [
        "",
        f"IJF WRL: k = {k} fitted on {len(calibration)} contests"
        f" ({CALIBRATION_FROM} to {TEST_FROM}); with k = 1 (chances proportional to points)"
        f" the test's log loss is {ijf1['log loss']:.4f},"
        f" accuracy {ijf1['accuracy']:.4f}.",
    ]
    result["disagreements"] = {"n": len(split), "ours_right": ours_right, "p": p_value}
    sweep(outcomes, test, slices)
    report = "\n".join(lines + diffs + cal + dis + note)
    open(os.path.join(HERE, "RESULTS.md"), "w").write(report + "\n")
    json.dump(result, open(os.path.join(HERE, "results.json"), "w"), indent=1, default=str)
    # every judged contest with each model's chance of the blue side, to trace any number
    with gz_text(os.path.join(DATA, "predictions.csv.gz")) as f:
        w = csv.writer(f)
        w.writerow(
            [
                "contest_id",
                "competition_id",
                "start",
                "window",
                "blue_won",
                "coin",
                "ijf",
                "elo",
                "glicko2",
                "ours",
                "wrl_points_blue",
                "wrl_points_white",
                "stage",
                "level",
                "experience",
                "moved",
            ]
        )
        for r in rows:
            w.writerow(
                [
                    r["contest_id"],
                    r["competition"],
                    r["start"],
                    "test" if r["start"] >= TEST_FROM else "calibration",
                    int(r["won"]),
                    0.5,
                    round(r["ijf"], 6),
                    round(r["elo"], 6),
                    round(r["glicko2"], 6),
                    round(r["ours"], 6),
                    *r["pts"],
                    r["stage"],
                    r["level"],
                    r["experience"],
                    int(r["moved"]),
                ]
            )
    print(report)


if __name__ == "__main__":
    main()
