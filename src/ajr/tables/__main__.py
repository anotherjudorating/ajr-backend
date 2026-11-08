"""python -m ajr.tables publish [--full] [--dry-run] | build --day D --out DIR | check [--days N]

publish: compute the past days' tables that are stale or new, upload them to R2 with the
archive, then the manifest (ajr/tables). Needs DATABASE_URL (the working copy) and
R2_ACCOUNT_ID, R2_BUCKET, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY; without the R2
settings (a fork) it says so and does nothing. --full: every day again under the
current version. --dry-run: plan and compute, upload nothing.
build: one day's files to a directory, for a look.
check: a few random days of the manifest, downloaded from DATA_URL and compared with
the database's functions.
"""

import argparse
import gzip
import json
import logging
import os
import random
import sys
import urllib.request
from datetime import date
from pathlib import Path

import psycopg
from sqlalchemy import make_url

from ajr.core.job_run import job_run
from ajr.tables import (
    FIRST_DAY,
    Bucket,
    day_key,
    day_tables,
    encode,
    generation_of,
    publish,
)

R2_SETTINGS = ("R2_ACCOUNT_ID", "R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")


def plain(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def summary(lines: list[str]) -> None:
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a") as file:
            file.write("\n".join(lines) + "\n")


class DryBucket(Bucket):
    """Counts what would be uploaded; reads the real manifest when it can."""

    def __init__(self) -> None:  # noqa: D107 - no client unless the settings are there
        self.uploaded = 0
        self.bytes = 0
        self.pending = []
        self.real = Bucket() if all(os.environ.get(k) for k in R2_SETTINGS) else None
        self.name = "dry-run"

    def put(self, key, body, content_type, cache, gzipped) -> None:
        self.uploaded += 1
        self.bytes += len(body)

    def wait(self) -> None:
        pass

    def manifest(self):
        return self.real.manifest() if self.real else None

    def delete_prefix(self, prefix: str) -> int:
        return 0


def run_publish(args) -> int:
    if not args.dry_run and not all(os.environ.get(k) for k in R2_SETTINGS):
        print("::notice::R2 is not set up (R2_* settings): no past-day tables uploaded")
        return 0
    bucket = DryBucket() if args.dry_run else Bucket()
    with psycopg.connect(plain(os.environ["DATABASE_URL"])) as connection:
        with job_run("tables"):
            result = publish(connection, bucket, full=args.full, dry_run=args.dry_run)
    plan = result.plan
    span = f"{plan.days[0]} … {plan.days[-1]}" if plan.days else "none"
    line = (
        f"version {plan.version}{' (new, every day)' if plan.full else ''}, days {span} "
        f"({len(plan.days)}), generation {plan.generation}, files {result.files}, "
        f"{result.bytes / 1e6:.1f} MB, old objects deleted {result.deleted}"
    )
    logging.info("Past-day tables: %s", line)
    summary(["### Past-day tables (R2)" + (" — dry run" if args.dry_run else ""), "", line])
    return 0


def run_build(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    day = date.fromisoformat(args.day)
    with psycopg.connect(plain(os.environ["DATABASE_URL"])) as connection:
        for table, name, rows in day_tables(connection, day):
            path = out / f"{table}-{name}-{day}.json.gz"
            path.write_bytes(encode({"table": table, "key": name, "day": str(day), "rows": rows}))
            print(path, len(rows), "rows", path.stat().st_size, "bytes")
    return 0


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
    return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body


def run_check(args) -> int:
    base = os.environ.get("DATA_URL", "https://data.anotherjudorating.com")
    manifest = json.loads(fetch(f"{base}/manifest.json"))
    last = date.fromisoformat(manifest["last_day"])
    days = [
        date.fromordinal(random.Random(args.seed).randint(FIRST_DAY.toordinal(), last.toordinal()))
        for _ in range(args.days)
    ]
    differ = []
    with psycopg.connect(plain(os.environ["DATABASE_URL"])) as connection:
        for day in days:
            g = generation_of(manifest, day)
            for table, name, rows in day_tables(connection, day):
                key = day_key(manifest["version"], table, name, day, g)
                stored = json.loads(fetch(f"{base}/{key}"))["rows"]
                if json.loads(json.dumps(rows, default=str)) != stored:
                    differ.append(key)
    print(f"checked {len(days)} days: {len(differ)} files differ", *differ, sep="\n")
    return 1 if differ else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Past days' tables in R2.")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("publish")
    p.add_argument("--full", action="store_true", help="every day again under the current version")
    p.add_argument("--dry-run", action="store_true", help="compute, upload nothing")
    b = commands.add_parser("build")
    b.add_argument("--day", required=True)
    b.add_argument("--out", required=True)
    c = commands.add_parser("check")
    c.add_argument("--days", type=int, default=5)
    c.add_argument("--seed", type=int, default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return {"publish": run_publish, "build": run_build, "check": run_check}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
