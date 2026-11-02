"""python -m ajr.loadtest.report BASE HEAD: the load test of main and of a pull
request on the same copy of the database, side by side, as markdown (the job's
summary). For information: what fails the job is a failed call (in HEAD).

Pages are what a call reads (cache or disk): on the same data and plan the same on
every run, unlike the times. A call that reads clearly more than on main is marked.
"""

import json
import sys
from collections import defaultdict

MORE = 1.5  # marked: this many times the pages of main…
AND_AT_LEAST = 500  # …and at least this many pages more


def pages_of(cases: list[dict]) -> dict[str, int | None]:
    return {c["case"]: c["pages"] for c in cases}


def ratio(before: float | None, after: float | None) -> str:
    if not before or after is None:
        return ""
    return f"×{after / before:.1f}"


def marked(before: int | None, after: int | None) -> bool:
    return (
        before is not None
        and after is not None
        and after >= before * MORE
        and after - before >= AND_AT_LEAST
    )


def report(base: dict, head: dict) -> str:
    lines = ["## Load test: main → this pull request", ""]
    if head["failures"]:
        lines += [f"**{len(head['failures'])} failed calls** (timeouts, server errors):", ""]
        lines += [f"- `{f}`" for f in head["failures"][:50]] + [""]
    else:
        lines += [f"All {len(head['cases'])} calls answered.", ""]
    if base["failures"]:
        lines += [f"On main {len(base['failures'])} calls failed too.", ""]

    lines += [
        "### Under load",
        "",
        "| Clients | p50 ms | p95 ms | p99 ms | Failed |",
        "|---|---|---|---|---|",
    ]
    for b, h in zip(base["loads"], head["loads"], strict=False):
        lines.append(
            f"| {h['clients']} | {b['p50']} → {h['p50']} | {b['p95']} → {h['p95']} "
            f"| {b['p99']} → {h['p99']} | {len(b['failures'])} → {len(h['failures'])} |"
        )

    before = pages_of(base["cases"])
    by_function: dict[str, list[dict]] = defaultdict(list)
    for case in head["cases"]:
        by_function[case["function"]].append(case)
    first_ms = {c["case"]: c["first"]["ms"] for c in base["cases"]}

    lines += [
        "",
        "### Per function",
        "",
        "Pages read (all its calls) and the slowest first call. ⚠️: a call reads "
        f"{MORE}× the pages of main and {AND_AT_LEAST}+ more.",
        "",
        "| Function | Calls | Pages | | Slowest first call, ms |",
        "|---|---|---|---|---|",
    ]
    for function, cases in sorted(by_function.items()):
        b = sum(before.get(c["case"]) or 0 for c in cases)
        a = sum(c["pages"] or 0 for c in cases)
        slow_b = max((first_ms.get(c["case"], 0) for c in cases), default=0)
        slow_a = max(c["first"]["ms"] for c in cases)
        warn = " ⚠️" if any(marked(before.get(c["case"]), c["pages"]) for c in cases) else ""
        lines.append(
            f"| `{function}`{warn} | {len(cases)} | {b} → {a} | {ratio(b, a)} "
            f"| {slow_b:.0f} → {slow_a:.0f} |"
        )

    worse = [c for c in head["cases"] if marked(before.get(c["case"]), c["pages"])]
    if worse:
        lines += ["", "### Calls reading clearly more", "", "| Call | Pages |", "|---|---|"]
        lines += [f"| `{c['case']}` | {before[c['case']]} → {c['pages']} |" for c in worse]
    new = [c["case"] for c in head["cases"] if c["case"] not in before]
    if new:
        lines += ["", f"New calls (not on main): {len(new)}."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    base, head = (json.load(open(path)) for path in sys.argv[1:3])
    print(report(base, head))
