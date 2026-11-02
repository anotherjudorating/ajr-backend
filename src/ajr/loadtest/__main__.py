"""python -m ajr.loadtest --api URL [--key KEY] [--plan] [--writes] [--clients 5,15,30]
[--out FILE]: see ajr/loadtest/__init__.py."""

import argparse
import asyncio
import json
import random
import sys
from dataclasses import asdict

from ajr.loadtest.cases import build
from ajr.loadtest.run import Api, one_by_one, under_load


async def main(args: argparse.Namespace) -> int:
    rng = random.Random(1)  # the same cases and order on every run
    async with Api(args.api, args.key) as api:
        cases = [c for c in await build(api, rng) if args.writes or not c.writes]
        print(f"{len(cases)} cases", file=sys.stderr)
        first = await one_by_one(api, cases)
        warm = await one_by_one(api, cases)
        plans = await one_by_one(api, cases, plan=True) if args.plan else [None] * len(cases)
        loads = [await under_load(api, cases, n, rng) for n in args.clients]

    report = {
        "cases": [
            {
                "case": case.key,
                "function": case.function,
                "first": asdict(f),
                "warm": asdict(w),
                "pages": p.pages if p else None,
            }
            for case, f, w, p in zip(cases, first, warm, plans, strict=True)
        ],
        "loads": [asdict(load) for load in loads],
    }
    failures = [
        f"{c['case']}: {c[run]['status']} {c[run]['error']}"
        for c in report["cases"]
        for run in ("first", "warm")
        if not 200 <= c[run]["status"] < 300
    ] + [
        f"{f['case']} ({load['clients']} clients): {f['status']} {f['error']}"
        for load in report["loads"]
        for f in load["failures"]
    ]
    report["failures"] = failures

    text = json.dumps(report, indent=1)
    if args.out:
        with open(args.out, "w") as file:
            file.write(text)
    for load in loads:
        print(
            f"{load.clients:>3} clients: p50 {load.p50} ms, p95 {load.p95} ms, p99 {load.p99} ms, "
            f"{len(load.failures)} failed of {load.calls}",
            file=sys.stderr,
        )
    for failure in failures:
        print("FAILED", failure, file=sys.stderr)
    return 1 if failures else 0


def parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api",
        required=True,
        help="PostgREST: http://localhost:3000 or https://<ref>.supabase.co/rest/v1",
    )
    parser.add_argument("--key", default="", help="the publishable key (Supabase)")
    parser.add_argument("--plan", action="store_true", help="pages read per call (db-plan-enabled)")
    parser.add_argument("--writes", action="store_true", help="also count_matchup, which writes")
    parser.add_argument(
        "--clients", type=lambda text: [int(n) for n in text.split(",")], default=[5, 15, 30]
    )
    parser.add_argument("--out", help="the report, JSON")
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse())))
