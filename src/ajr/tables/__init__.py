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
    places/<version>/athletes/<athlete_id>.json           an athlete's place every week
    places/<version>/state.json                           every athlete's, for the next run
    places/<version>/nations/<IOC>.json                   a nation's place and rating every week
    places/<version>/nations-state.json                   every nation's, for the next run
    archive/<version>/rating_history.csv.gz, athletes.csv.gz, competitions.csv.gz, README.md

<version> is a hash of the rating settings: a new formula is written under a new
prefix, then the manifest switches to it and the old tables go an hour later; the old
archive stays 90 days (the manifest's `old_archives`), so a link in someone's analysis
keeps working for a while after the formula changes. The
files are cached for a year at the edge, so a day computed again in the same version
(results corrected back in time) gets a new name: the manifest's `generations` say
from which day on which generation holds (`.g<n>`, none for 0). Each file holds
exactly what api.leaderboard / api.p4p / api.teams answer for that day.

An athlete's places (in their weight's table and pound for pound, every Monday) are
one small file per athlete, for the site's rating chart: the weeks the run computes
replace the ones they cover in the state of the last run (state.json), and only the
files that changed are uploaded. They change every week, so they are not under v/ (a
year at the edge): places/ is cached an hour (ajr-web/infra/cloudflare.tf).

A nation's weeks (its place and rating in the mixed nations table every Monday, for the
country page's chart) come the same way, from the same tables, a file per nation.

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
PLACES_CACHE = "public, max-age=3600"  # they change every week: see above
ARCHIVE_KEEP = timedelta(days=90)  # an old version's archive, after a new formula
LICENSE = "https://creativecommons.org/licenses/by/4.0/"  # CC BY 4.0, the archive's
CONTACT = "data@anotherjudorating.com"
SITE = "https://www.anotherjudorating.com"


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
    places_version: str | None = None  # the version the places files are written for


def load_state(connection: Connection) -> State:
    row = connection.execute(
        "select pending_from, version, last_day, places_version from ajr.tables_export where id = 1"
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


def place_key(version: str, athlete_id: int | str) -> str:
    return f"places/{version}/athletes/{athlete_id}.json"


def nation_key(version: str, ioc: str) -> str:
    return f"places/{version}/nations/{ioc}.json"


def nations_state_key(version: str) -> str:
    return f"places/{version}/nations-state.json"


def places_state_key(version: str) -> str:
    return f"places/{version}/state.json"


# A week of an athlete, packed into one number for the state: the place in the weight's
# table, the place pound for pound (0 outside it) and the weight's index in WEIGHTS; 0
# for a week outside every table.
def pack(place: int, p4p: int | None, weight: int) -> int:
    return place * 1024 + (p4p or 0) * 16 + weight


def unpack(code: int) -> list | None:
    if not code:
        return None
    return [code // 1024, WEIGHTS[code % 16], (code // 16) % 64 or None]


def week_places(tables: list[tuple[str, str, list[dict]]]) -> dict[int, int]:
    """A day's packed week of every athlete in its tables (day_tables)."""
    weights = {slug(w): i for i, w in enumerate(WEIGHTS)}
    p4p = {row["athlete_id"]: row["place"] for t, _, rows in tables if t == "p4p" for row in rows}
    out: dict[int, int] = {}
    for table, name, rows in tables:
        if table != "rankings":
            continue
        for row in rows:
            aid = row["athlete_id"]
            code = pack(row["place"], p4p.get(aid), weights[name])
            # listed in one table; if ever in two, the better place
            if aid not in out or code < out[aid]:
                out[aid] = code
    return out


def merge_places(state: dict, start: int, new: list[dict[int, int]]) -> dict:
    """The state ({athlete: [first week, codes…]}, weeks counted from FIRST_DAY) with
    the weeks from index `start` on replaced by `new` (one dict a week)."""
    out: dict[str, list[int]] = {}
    for aid, (first, *codes) in state.items():
        kept = codes[: max(0, start - first)]
        if kept:
            out[aid] = [first, *kept]
    for offset, week in enumerate(new):
        index = start + offset
        for aid, code in week.items():
            key = str(aid)
            entry = out.setdefault(key, [index])
            entry.extend([0] * (index - entry[0] - (len(entry) - 1)))
            entry.append(code)
    for entry in out.values():
        while len(entry) > 1 and entry[-1] == 0:
            entry.pop()
    return out


def place_document(entry: list[int]) -> dict:
    """An athlete's file: their first week, then a week a row (place, weight, place
    pound for pound; null outside every table)."""
    first, *codes = entry
    return {"format": FORMAT, "from": (FIRST_DAY + timedelta(weeks=first)).isoformat(),
            "weeks": [unpack(c) for c in codes]}  # fmt: skip


# A nation's week, packed as an athlete's: its place and rating.
def pack_nation(place: int, rating: int) -> int:
    return place * 8192 + rating


def week_nations(tables: list[tuple[str, str, list[dict]]]) -> dict[str, int]:
    """A day's packed week of every nation in the mixed nations table (day_tables)."""
    return {
        row["country"]: pack_nation(row["place"], row["rating"])
        for table, name, rows in tables
        if table == "teams" and name == "mixed"
        for row in rows
    }


def nation_document(entry: list[int]) -> dict:
    """A nation's file: a week a row (the Monday, the place, the rating), its weeks
    outside the table left out."""
    first, *codes = entry
    weeks = [[(FIRST_DAY + timedelta(weeks=first + i)).isoformat(), c // 8192, c % 8192]
             for i, c in enumerate(codes) if c]  # fmt: skip
    return {"format": FORMAT, "weeks": weeks}


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

    def get(self, key: str) -> bytes | None:
        try:
            return self.s3.get_object(Bucket=self.name, Key=key)["Body"].read()
        except self.s3.exceptions.NoSuchKey:
            return None

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
               rc.volatility_before, rc.rating_after, rc.rd_after, rc.volatility_after,
               rc.competition_id, rc.round_name
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


# What each column of the archive means, for its README (a test checks that every
# column of ARCHIVE has a line here).
COLUMNS = {
    "rating_history.csv.gz": {
        "contest_id": "the contest's judobase id",
        "athlete_id": "the athlete's judobase id (athletes.csv.gz); two rows per contest, one each",
        "opponent_id": "the opponent's judobase id",
        "fought_on": "the day of the contest (YYYY-MM-DD)",
        "weight": "the weight category, e.g. -73 or +78",
        "won": "whether the athlete won (true/false)",
        "win_probability": "the athlete's chance to win before the contest, by the rating (0 to 1)",
        "rating_before": "the athlete's Glicko-2 rating before the contest",
        "rd_before": "the rating deviation before the contest (how unsure the rating is)",
        "volatility_before": "the Glicko-2 volatility before the contest",
        "rating_after": "the rating after the contest",
        "rd_after": "the rating deviation after the contest",
        "volatility_after": "the volatility after the contest",
        "competition_id": "the tournament's judobase id (competitions.csv.gz)",
        "round_name": "the stage of the draw, from the final: F, 1/2 (semi-final), 1/4, 1/8 …"
        " 1/128; BR (bronze), REP (repechage); R1, R2… a tour of a round robin or of pools",
    },
    "athletes.csv.gz": {
        "id": "the athlete's judobase id",
        "family_name": "family name, as in judobase",
        "given_name": "given name, as in judobase",
        "gender": "male or female",
        "dob_year": "year of birth, when judobase has it",
        "country": "IOC code of the country the athlete last fought for",
    },
    "competitions.csv.gz": {
        "id": "the tournament's judobase id",
        "name": "the tournament's name",
        "rank_name": "its level: Grand Slam, Grand Prix, World Championships, Continental Open…",
        "city": "host city",
        "country": "IOC code of the host country",
        "date_from": "first day",
        "date_to": "last day",
        "contests": "contests of the tournament in the rating",
    },
}


def readme(current: str, settings: dict, files: dict[str, dict], now: datetime) -> str:
    """The archive's README: what the files are, their columns, the formula's settings,
    the license and where the results come from."""
    lines = [
        "# Another Judo Rating: rating history",
        "",
        "Every senior individual IJF contest since 2009 with the Glicko-2 rating of both",
        f"athletes before and after it, as computed by Another Judo Rating ({SITE}).",
        "",
        f"- Version: `{current}` (a hash of the rating settings below: a new formula, a new one)",
        f"- Updated: {now.date().isoformat()} (weekly, after Monday)",
        f"- About the files: {SITE}/data",
        f"- License: CC BY 4.0 ({LICENSE})",
        f"- Contact, questions and removal requests: {CONTACT}",
        "",
        "## Files",
        "",
        "| File | Rows | Bytes | sha256 |",
        "|---|---|---|---|",
    ]
    for name, meta in files.items():
        lines.append(f"| {name} | {meta['rows']} | {meta['bytes']} | `{meta['sha256']}` |")
    for name, columns in COLUMNS.items():
        lines += ["", f"## {name}", "", "| Column | Meaning |", "|---|---|"]
        lines += [f"| {column} | {meaning} |" for column, meaning in columns.items()]
    lines += ["", "## Rating settings of this version", "", "| Setting | Value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in settings.items()]
    lines += [
        "",
        "## Source and license",
        "",
        "Derived from results published in IJF judobase (judobase.ijf.org). Another Judo",
        "Rating is not affiliated with or endorsed by the International Judo Federation.",
        "The IJF retains all rights in its own data; this archive republishes only the",
        "identifiers and outcomes needed to reproduce the rating. CC BY 4.0 covers the",
        "rating and the other columns computed by Another Judo Rating.",
        "",
        f"Cite as: Another Judo Rating, rating history, version {current}, {SITE}/data",
        "",
    ]
    return "\n".join(lines)


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
        and state.places_version == current
    ):
        # nothing stale and nothing new: no request to R2 at all (most runs)
        return Result(Plan(current, False, [], 0), 0, 0, 0)
    manifest = bucket.manifest()
    plan = make_plan(manifest, state, current, today, full, now)
    connection.execute("set jit = off")
    connection.execute("set work_mem = '64MB'")

    weeks: list[dict[int, int]] = []
    nation_weeks: list[dict[str, int]] = []
    for day in plan.days:
        computed = day_tables(connection, day)
        for table, name, rows in computed:
            document = {"format": FORMAT, "table": table, "key": name, "day": day.isoformat(),
                        "version": current, "rows": rows}  # fmt: skip
            key = day_key(current, table, name, day, plan.generation)
            bucket.put(key, encode(document), "application/json", IMMUTABLE, gzipped=True)
        weeks.append(week_places(computed))
        nation_weeks.append(week_nations(computed))
        if len(bucket.pending) > 2000:
            bucket.wait()

    # the athletes' places and the nations' weeks: the computed weeks over the last run's,
    # only changed files up; also with no day to compute when they were never written
    # for this version
    if plan.days or state.places_version != current:
        old: dict = {}
        old_nations: dict = {}
        if not plan.full:
            body = bucket.get(places_state_key(current))
            old = json.loads(gzip.decompress(body)) if body else {}
            body = bucket.get(nations_state_key(current))
            old_nations = json.loads(gzip.decompress(body)) if body else {}
        # the first week computed (with no days: the one after the bucket's last)
        end = (
            plan.days[0]
            if plan.days
            else date.fromisoformat(manifest["last_day"]) + timedelta(weeks=1)
        )
        start = (end - FIRST_DAY).days // 7
        if not (old and old_nations) and not plan.full and start > 0:
            # no state yet (the first run with places): the weeks before, places only;
            # the files of the first layout (under v/, a year at the edge) go
            bucket.delete_prefix(f"v/{current}/places")
            before = [
                day_tables(connection, day)
                for day in days_between(FIRST_DAY, end - timedelta(days=1))
            ]
            weeks = [week_places(t) for t in before] + weeks
            nation_weeks = [week_nations(t) for t in before] + nation_weeks
            old, old_nations, start = {}, {}, 0
        for state_key, key, document, previous, new in (
            (places_state_key, place_key, place_document, old, merge_places(old, start, weeks)),
            (nations_state_key, nation_key, nation_document, old_nations,
             merge_places(old_nations, start, nation_weeks)),
        ):  # fmt: skip
            # one no longer in any computed table keeps a file, with no weeks
            for name, entry in {**{n: [0] for n in previous if n not in new}, **new}.items():
                if previous.get(name) != entry:
                    body = document(entry) if len(entry) > 1 else {"format": FORMAT, "weeks": []}
                    bucket.put(key(current, name), encode(body), "application/json",
                               PLACES_CACHE, gzipped=True)  # fmt: skip
                if len(bucket.pending) > 2000:
                    bucket.wait()
            bucket.put(state_key(current), encode(new), "application/json", "no-store",
                       gzipped=True)  # fmt: skip

    archive = dict((manifest or {}).get("archive", {})) if not plan.full else {}
    if plan.days or plan.full:
        for name, (body, rows) in archive_files(connection).items():
            bucket.put(f"archive/{current}/{name}", body, "text/csv", ARCHIVE_CACHE, gzipped=False)
            archive[name] = {
                "bytes": len(body), "rows": rows,
                "sha256": hashlib.sha256(body).hexdigest(), "updated_at": now.isoformat(),
            }  # fmt: skip
        text = readme(current, settings, archive, now).encode()
        bucket.put(f"archive/{current}/README.md", text, "text/markdown; charset=utf-8",
                   ARCHIVE_CACHE, gzipped=False)  # fmt: skip
    bucket.wait()

    # The old version's archive stays ARCHIVE_KEEP after a new formula, then goes.
    old_archives = list((manifest or {}).get("old_archives", []))
    if manifest and manifest["version"] != current and manifest.get("archive"):
        old_archives.append({"version": manifest["version"], "switched_out_at": now.isoformat(),
                             "archive": manifest["archive"]})  # fmt: skip
    expired = [a["version"] for a in old_archives
               if datetime.fromisoformat(a["switched_out_at"]) < now - ARCHIVE_KEEP]  # fmt: skip
    old_archives = [a for a in old_archives if a["version"] not in expired]

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
        "readme": f"archive/{current}/README.md" if archive else None,
        "license": LICENSE,
        "old_archives": old_archives,
        "previous": previous,
    }
    if dry_run:
        connection.rollback()
        return Result(plan, bucket.uploaded, bucket.bytes, 0)
    if (
        plan.days
        or plan.full
        or new_manifest["previous"] != (manifest or {}).get("previous")
        or new_manifest["old_archives"] != (manifest or {}).get("old_archives")
    ):
        bucket.s3.put_object(
            Bucket=bucket.name, Key="manifest.json",
            Body=json.dumps(new_manifest, default=str, indent=1).encode(),
            ContentType="application/json", CacheControl=MANIFEST_CACHE,
        )  # fmt: skip

    deleted = sum(bucket.delete_prefix(f"v/{v}/") for v in plan.delete)
    deleted += sum(bucket.delete_prefix(f"places/{v}/") for v in plan.delete)
    deleted += sum(bucket.delete_prefix(f"archive/{v}/") for v in expired)
    connection.execute(
        "insert into ajr.tables_export (id, version, last_day, places_version)"
        " values (1, %s, %s, %s)"
        " on conflict (id) do update set pending_from = null, version = excluded.version,"
        " last_day = excluded.last_day, places_version = excluded.places_version,"
        " updated_at = now()",
        [current, last_day, current],
    )
    connection.commit()
    return Result(plan, bucket.uploaded, bucket.bytes, deleted)
