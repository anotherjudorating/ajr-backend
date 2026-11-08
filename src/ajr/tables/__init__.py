"""Past days' ranking tables and the open-data archive, as files in Cloudflare R2.

A past week's table (one a week, on Monday) never changes unless the rating does (a
new formula, or results corrected back in time), so it is computed once and served from
data.anotherjudorating.com through the Cloudflare edge, not by the database on every
visit (docs/audits/2026-11-08-r2-tables-plan.md). Today's tables stay in the database.

Layout of the bucket:

    manifest.json                                         what the site reads first
    v/<version>/rankings/<slug>/<YYYY>/<YYYY-MM-DD>[.g<n>].json   (Mondays)
    v/<version>/p4p/<men|women>/<YYYY>/<YYYY-MM-DD>[.g<n>].json
    v/<version>/teams/<men|women|mixed>/<YYYY>/<YYYY-MM-DD>[.g<n>].json
    archive/<version>/rating_history.csv.gz, athletes.csv.gz, competitions.csv.gz

<version> is a hash of the rating settings: a new formula is written under a new
prefix, then the manifest switches to it and the old prefix goes an hour later. The
files are cached for a year at the edge, so a day computed again in the same version
(results corrected back in time) gets a new name: the manifest's `generations` say
from which day on which generation holds (`.g<n>`, none for 0). Each file holds
exactly what api.leaderboard / api.p4p / api.teams answer for that day.

The update job runs `python -m ajr.tables publish` after the publish to production:
the rating job marks from which day the tables are stale (ajr.tables_export.pending_from),
this computes those days (and the new day each night) on the working copy, uploads
them, writes the manifest last and clears the mark.
"""

import csv
import gzip
import hashlib
import io
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from psycopg import Connection

logger = logging.getLogger(__name__)

FORMAT = 2  # raised when the files' content changes without the rating settings (2: weekly)
FIRST_DAY = date(2009, 1, 5)  # the first Monday of 2009; earlier days stay with the database
WEIGHTS = ["-60", "-66", "-73", "-81", "-90", "-100", "+100",
           "-48", "-52", "-57", "-63", "-70", "-78", "+78"]  # fmt: skip
GENDERS = ["men", "women"]
TEAM_KINDS = ["men", "women", "mixed"]
OLD_VERSION_GRACE = timedelta(hours=1)  # the site caches the manifest ~10 minutes

IMMUTABLE = "public, max-age=31536000, immutable"
MANIFEST_CACHE = "public, max-age=300, must-revalidate"
ARCHIVE_CACHE = "public, max-age=3600"


def slug(weight: str) -> str:
    """The site's URL part of a weight (ajr-web src/lib/weights.ts): men-73, women-plus-78."""
    gender = "men" if weight in WEIGHTS[:7] else "women"
    return f"{gender}-{'plus-' if weight.startswith('+') else ''}{weight[1:]}"


def day_key(version: str, table: str, name: str, day: date, generation: int) -> str:
    suffix = f".g{generation}" if generation else ""
    return f"v/{version}/{table}/{name}/{day.year}/{day.isoformat()}{suffix}.json"


def generation_of(manifest: dict, day: date) -> int:
    """The generation holding `day`: the latest whose range starts on or before it."""
    held = [g["g"] for g in manifest.get("generations", []) if date.fromisoformat(g["from"]) <= day]
    return max(held, default=0)


def version(settings: dict) -> str:
    payload = json.dumps({"format": FORMAT, **settings}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def load_settings(connection: Connection) -> dict:
    cursor = connection.execute("select * from ajr.rating_settings where id = 1")
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("no rating settings: run the rating first")
    names = [c.name for c in cursor.description]
    return {k: v for k, v in zip(names, row, strict=True) if k != "id"}


@dataclass
class State:
    """ajr.tables_export: what the bucket holds, and from which day it is stale."""

    pending_from: date | None
    version: str | None
    last_day: date | None


def load_state(connection: Connection) -> State:
    row = connection.execute(
        "select pending_from, version, last_day from ajr.tables_export where id = 1"
    ).fetchone()
    return State(*row) if row else State(None, None, None)


@dataclass
class Plan:
    version: str
    full: bool  # a new prefix, every day
    days: list[date]
    generation: int  # of the days computed
    delete: list[str] = field(default_factory=list)  # old prefixes to remove


def monday(day: date) -> date:
    """The Monday of `day`'s week (the day itself on a Monday)."""
    return day - timedelta(days=day.weekday())


def days_between(first: date, last: date) -> list[date]:
    """The Mondays from `first` to `last`: a table a week. Between tournaments a table
    barely moves (scores slide as RD grows), and tournaments end at weekends, so a
    Monday's table is the state after the weekend's events; the site shows a day's
    table as its week's Monday's."""
    start = monday(first) + (timedelta(days=7) if first.weekday() else timedelta(0))
    return [start + timedelta(days=7 * i) for i in range(max(0, (last - start).days // 7 + 1))]


def make_plan(
    manifest: dict | None, state: State, current: str, today: date, full: bool, now: datetime
) -> Plan:
    yesterday = today - timedelta(days=1)
    old = [
        p["version"]
        for p in (manifest or {}).get("previous", [])
        if datetime.fromisoformat(p["switched_out_at"]) < now - OLD_VERSION_GRACE
    ]
    if full or manifest is None or manifest["version"] != current:
        return Plan(current, True, days_between(FIRST_DAY, yesterday), 0, old)
    last = date.fromisoformat(manifest["last_day"])
    start = last + timedelta(days=1)
    generation = max((g["g"] for g in manifest.get("generations", [])), default=0)
    if state.pending_from is not None and state.pending_from <= last:
        # days the bucket already holds are stale: a new generation from that day on
        start = max(state.pending_from, FIRST_DAY)
        generation += 1
    return Plan(current, False, days_between(start, yesterday), generation, old)


def day_tables(connection: Connection, day: date) -> list[tuple[str, str, list[dict]]]:
    """(table, name, rows) for every table of `day`, exactly as the site's functions
    answer for a past day."""
    out = []
    for table, function, names, label in (
        ("rankings", "api.leaderboard", WEIGHTS, slug),
        ("p4p", "api.p4p", GENDERS, str),
        ("teams", "api.teams", TEAM_KINDS, str),
    ):
        for name in names:
            cursor = connection.execute(f"select * from {function}(%s, %s)", [name, day])
            columns = [c.name for c in cursor.description]
            rows = [dict(zip(columns, row, strict=True)) for row in cursor]
            out.append((table, label(name), rows))
    return out


def encode(document: dict) -> bytes:
    text = json.dumps(document, separators=(",", ":"), default=str, ensure_ascii=False)
    return gzip.compress(text.encode(), compresslevel=9, mtime=0)


class Bucket:
    """The R2 bucket through its S3 API; uploads run in a thread pool."""

    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        self.name = os.environ["R2_BUCKET"]
        self.s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
            region_name="auto",
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            config=Config(
                retries={"max_attempts": 10, "mode": "adaptive"},
                max_pool_connections=64,
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )
        self.pool = ThreadPoolExecutor(32)
        self.pending: list = []
        self.uploaded = 0
        self.bytes = 0

    def put(self, key: str, body: bytes, content_type: str, cache: str, gzipped: bool) -> None:
        extra = {"ContentEncoding": "gzip"} if gzipped else {}
        self.pending.append(
            self.pool.submit(
                self.s3.put_object,
                Bucket=self.name,
                Key=key,
                Body=body,
                ContentType=content_type,
                CacheControl=cache,
                **extra,
            )  # fmt: skip
        )
        self.uploaded += 1
        self.bytes += len(body)

    def wait(self) -> None:
        """Every upload so far has succeeded (or raise)."""
        for future in self.pending:
            future.result()
        self.pending = []

    def manifest(self) -> dict | None:
        try:
            body = self.s3.get_object(Bucket=self.name, Key="manifest.json")["Body"].read()
        except self.s3.exceptions.NoSuchKey:
            return None
        return json.loads(body)

    def delete_prefix(self, prefix: str) -> int:
        deleted = 0
        for page in self.s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.name, Prefix=prefix
        ):
            keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if keys:
                self.s3.delete_objects(Bucket=self.name, Delete={"Objects": keys, "Quiet": True})
                deleted += len(keys)
        return deleted


ARCHIVE = {
    "rating_history.csv.gz": """
        select rc.contest_id, rc.athlete_id, rc.opponent_id, rc.fought_on, rc.weight,
               rc.won, rc.win_probability, rc.rating_before, rc.rd_before,
               rc.rating_after, rc.rd_after, rc.competition_id, rc.round_name
        from ajr.rating_change rc
        order by rc.fought_on, rc.seq, rc.athlete_id
    """,
    "athletes.csv.gz": """
        select a.id, a.family_name, a.given_name, a.gender, a.dob_year, co.ioc as country
        from ajr.athlete a left join ajr.country co on co.id = a.country_id
        where exists (select from ajr.athlete_summary s where s.athlete_id = a.id)
        order by a.id
    """,
    "competitions.csv.gz": """
        select st.competition_id as id, st.name, st.rank_name, st.city, st.country,
               st.date_from, st.date_to, st.contests
        from ajr.competition_stats st
        order by st.date_from, st.competition_id
    """,
}


def archive_files(connection: Connection) -> dict[str, tuple[bytes, int]]:
    """name -> (gzipped CSV, rows) of the open-data archive."""
    files = {}
    for name, query in ARCHIVE.items():
        text = io.StringIO()
        writer = csv.writer(text)
        cursor = connection.execute(query)
        writer.writerow([c.name for c in cursor.description])
        rows = 0
        for row in cursor:
            writer.writerow(row)
            rows += 1
        files[name] = (gzip.compress(text.getvalue().encode(), compresslevel=9, mtime=0), rows)
    return files


@dataclass
class Result:
    plan: Plan
    files: int
    bytes: int
    deleted: int


def publish(
    connection: Connection,
    bucket: Bucket,
    full: bool = False,
    today: date | None = None,
    dry_run: bool = False,
) -> Result:
    """Compute and upload what the plan says, then the manifest, then clear the mark.
    A dry run computes everything and writes nothing (`bucket` only counts)."""
    today = today or datetime.now(UTC).date()
    now = datetime.now(UTC)
    settings = load_settings(connection)
    current = version(settings)
    state = load_state(connection)
    if (
        not full
        and state.pending_from is None
        and state.version == current
        and state.last_day == monday(today - timedelta(days=1))
    ):
        # nothing stale and nothing new: no request to R2 at all (most runs)
        return Result(Plan(current, False, [], 0), 0, 0, 0)
    manifest = bucket.manifest()
    plan = make_plan(manifest, state, current, today, full, now)
    connection.execute("set jit = off")
    connection.execute("set work_mem = '64MB'")

    for day in plan.days:
        for table, name, rows in day_tables(connection, day):
            document = {"format": FORMAT, "table": table, "key": name, "day": day.isoformat(),
                        "version": current, "rows": rows}  # fmt: skip
            key = day_key(current, table, name, day, plan.generation)
            bucket.put(key, encode(document), "application/json", IMMUTABLE, gzipped=True)
        if len(bucket.pending) > 2000:
            bucket.wait()

    archive = dict((manifest or {}).get("archive", {})) if not plan.full else {}
    if plan.days or plan.full:
        for name, (body, rows) in archive_files(connection).items():
            bucket.put(f"archive/{current}/{name}", body, "text/csv", ARCHIVE_CACHE, gzipped=False)
            archive[name] = {
                "bytes": len(body), "rows": rows,
                "sha256": hashlib.sha256(body).hexdigest(), "updated_at": now.isoformat(),
            }  # fmt: skip
    bucket.wait()

    previous = [p for p in (manifest or {}).get("previous", []) if p["version"] not in plan.delete]
    if manifest and manifest["version"] != current:
        previous.append({"version": manifest["version"], "switched_out_at": now.isoformat()})
    generations = [] if plan.full else list((manifest or {}).get("generations", []))
    if plan.days and plan.generation and not plan.full:
        if not generations or generations[-1]["g"] != plan.generation:
            generations.append({"from": plan.days[0].isoformat(), "g": plan.generation})
    last_day = plan.days[-1] if plan.days else date.fromisoformat(manifest["last_day"])
    new_manifest = {
        "format": FORMAT,
        "version": current,
        "first_day": FIRST_DAY.isoformat(),
        "last_day": last_day.isoformat(),
        "generations": generations,
        "switched_at": now.isoformat() if plan.full else (manifest or {}).get("switched_at"),
        "settings": settings,
        "tables": {"rankings": [slug(w) for w in WEIGHTS], "p4p": GENDERS, "teams": TEAM_KINDS},
        "archive": archive,
        "previous": previous,
    }
    if dry_run:
        connection.rollback()
        return Result(plan, bucket.uploaded, bucket.bytes, 0)
    if plan.days or plan.full or new_manifest["previous"] != (manifest or {}).get("previous"):
        bucket.s3.put_object(
            Bucket=bucket.name, Key="manifest.json",
            Body=json.dumps(new_manifest, default=str, indent=1).encode(),
            ContentType="application/json", CacheControl=MANIFEST_CACHE,
        )  # fmt: skip

    deleted = sum(bucket.delete_prefix(f"v/{v}/") + bucket.delete_prefix(f"archive/{v}/")
                  for v in plan.delete)  # fmt: skip
    connection.execute(
        "insert into ajr.tables_export (id, version, last_day) values (1, %s, %s)"
        " on conflict (id) do update set pending_from = null, version = excluded.version,"
        " last_day = excluded.last_day, updated_at = now()",
        [current, last_day],
    )
    connection.commit()
    return Result(plan, bucket.uploaded, bucket.bytes, deleted)
