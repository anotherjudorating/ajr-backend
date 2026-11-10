"""The past days' tables in R2 (ajr/tables), with a bucket kept in memory."""

import gzip
import json
import os
from datetime import UTC, date, datetime, timedelta

import psycopg
import pytest
from sqlalchemy import make_url, text

import ajr.tables as tables
from ajr.core.db import engine
from ajr.rating.job import run_rating
from ajr.tables import State, generation_of, make_plan, slug
from tests.test_api import add_data

pytestmark = pytest.mark.usefixtures("clean_db")

NOW = datetime(2026, 11, 9, 3, tzinfo=UTC)
TODAY = NOW.date()


class MemoryBucket(tables.Bucket):
    def __init__(self, manifest: dict | None = None) -> None:
        self.objects: dict[str, bytes] = {}
        if manifest is not None:
            self.objects["manifest.json"] = json.dumps(manifest).encode()
        self.uploaded = 0
        self.bytes = 0
        self.pending = []
        self.name = "memory"
        self.s3 = self
        self.requests = 0

    def put(self, key, body, content_type, cache, gzipped) -> None:
        self.objects[key] = body
        self.uploaded += 1
        self.bytes += len(body)

    def put_object(self, Key, Body, **kwargs) -> None:  # noqa: N803 - boto3's names
        self.objects[Key] = Body

    def wait(self) -> None:
        pass

    def get(self, key):
        return self.objects.get(key)

    def manifest(self):
        self.requests += 1
        body = self.objects.get("manifest.json")
        return json.loads(body) if body else None

    def delete_prefix(self, prefix: str) -> int:
        keys = [k for k in self.objects if k.startswith(prefix)]
        for k in keys:
            del self.objects[k]
        return len(keys)


def connection():
    return psycopg.connect(
        make_url(os.environ["DATABASE_URL"])
        .set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )


def test_slugs_are_the_sites():
    assert slug("-73") == "men-73"
    assert slug("+100") == "men-plus-100"
    assert slug("-48") == "women-48"
    assert slug("+78") == "women-plus-78"


def test_a_new_version_redoes_every_day_and_drops_old_versions_after_an_hour():
    manifest = {
        "version": "old",
        "last_day": "2026-11-07",
        "previous": [
            {"version": "older", "switched_out_at": (NOW - timedelta(hours=2)).isoformat()},
            {"version": "recent", "switched_out_at": (NOW - timedelta(minutes=10)).isoformat()},
        ],
    }

    plan = make_plan(manifest, State(None, "old", None), "new", TODAY, False, NOW)

    assert plan.full and plan.days[0] == tables.FIRST_DAY and plan.days[-1] == date(2026, 11, 2)
    assert {d.weekday() for d in plan.days} == {0}  # Mondays
    assert plan.delete == ["older"]


def test_a_week_adds_its_monday_and_a_correction_makes_a_new_generation():
    manifest = {"version": "v", "last_day": "2026-10-26", "generations": []}

    week = make_plan(manifest, State(None, "v", None), "v", TODAY, False, NOW)
    corrected = make_plan(manifest, State(date(2026, 10, 1), "v", None), "v", TODAY, False, NOW)

    # Monday 2026-11-09 is today: its table is done tomorrow
    assert week.days == [date(2026, 11, 2)] and week.generation == 0
    assert corrected.days[0] == date(2026, 10, 5) and corrected.generation == 1
    with_generation = {"generations": [{"from": "2026-10-01", "g": 1}]}
    assert generation_of(with_generation, date(2026, 9, 30)) == 0
    assert generation_of(with_generation, date(2026, 10, 1)) == 1


def test_publish_uploads_the_days_then_the_manifest_and_clears_the_mark(monkeypatch):
    add_data()
    run_rating()
    monkeypatch.setattr(tables, "FIRST_DAY", TODAY - timedelta(days=21))
    bucket = MemoryBucket()

    with connection() as c:
        result = tables.publish(c, bucket, today=TODAY)

    manifest = json.loads(bucket.objects["manifest.json"])
    assert result.plan.full and len(result.plan.days) == 3  # three Mondays
    last_monday = date(2026, 11, 2)
    key = tables.day_key(manifest["version"], "rankings", "men-73", last_monday, 0)
    document = json.loads(gzip.decompress(bucket.objects[key]))
    with connection() as c:
        expected = c.execute(
            "select count(*) from api.leaderboard('-73', %s)", [last_monday]
        ).fetchone()[0]
    assert len(document["rows"]) == expected
    assert manifest["last_day"] == last_monday.isoformat()
    assert f"archive/{manifest['version']}/rating_history.csv.gz" in bucket.objects
    with engine.connect() as c:
        state = c.execute(text("select pending_from, version from ajr.tables_export")).one()
    assert state == (None, manifest["version"])

    # nothing stale, nothing new: not even the manifest is read
    requests = bucket.requests
    with connection() as c:
        assert tables.publish(c, bucket, today=TODAY).plan.days == []
    assert bucket.requests == requests


def test_a_rating_rewritten_back_in_time_marks_the_tables_stale():
    add_data()
    run_rating()
    with engine.begin() as c:
        c.execute(text("update ajr.tables_export set pending_from = null"))
        c.execute(text("update ajr.competition set results_changed_at = now()"))

    run_rating()

    with engine.connect() as c:
        assert c.execute(text("select pending_from from ajr.tables_export")).scalar() is not None


def test_every_archive_column_is_described_and_the_readme_goes_up(monkeypatch):
    add_data()
    run_rating()
    monkeypatch.setattr(tables, "FIRST_DAY", TODAY - timedelta(days=7))
    bucket = MemoryBucket()

    with connection() as c:
        for name, query in tables.ARCHIVE.items():
            columns = [col.name for col in c.execute(query + " limit 0").description]
            assert columns == list(tables.COLUMNS[name]), name
        tables.publish(c, bucket, today=TODAY)

    manifest = json.loads(bucket.objects["manifest.json"])
    assert manifest["license"] == tables.LICENSE
    text = bucket.objects[manifest["readme"]].decode()
    assert "volatility_before" in text and "CC BY 4.0" in text and tables.CONTACT in text
    assert manifest["archive"]["rating_history.csv.gz"]["sha256"] in text


def test_an_old_formulas_archive_stays_90_days(monkeypatch):
    add_data()
    run_rating()
    monkeypatch.setattr(tables, "FIRST_DAY", TODAY - timedelta(days=7))
    old = {"rating_history.csv.gz": {"bytes": 1, "rows": 1, "sha256": "x", "updated_at": "-"}}
    bucket = MemoryBucket(
        {"version": "old", "last_day": "2026-11-02", "archive": old, "previous": [],
         "old_archives": [{"version": "older", "archive": old,
                           "switched_out_at": (NOW - timedelta(days=91)).isoformat()}]}
    )  # fmt: skip
    bucket.objects["archive/old/rating_history.csv.gz"] = b"old"
    bucket.objects["archive/older/rating_history.csv.gz"] = b"older"

    with connection() as c:
        tables.publish(c, bucket, today=TODAY)

    manifest = json.loads(bucket.objects["manifest.json"])
    assert [a["version"] for a in manifest["old_archives"]] == ["old"]
    assert "archive/old/rating_history.csv.gz" in bucket.objects
    assert "archive/older/rating_history.csv.gz" not in bucket.objects


def test_publish_writes_every_athletes_places_and_a_week_later_only_whats_new(monkeypatch):
    add_data()
    run_rating()
    monkeypatch.setattr(tables, "FIRST_DAY", TODAY - timedelta(days=21))
    bucket = MemoryBucket()

    with connection() as c:
        tables.publish(c, bucket, today=TODAY)

    version = json.loads(bucket.objects["manifest.json"])["version"]
    mondays = tables.days_between(tables.FIRST_DAY, TODAY - timedelta(days=1))
    with connection() as c:
        query = "select athlete_id, place from api.leaderboard('-73', %s)"
        listed = c.execute(query, [mondays[-1]]).fetchall()
    assert listed
    for athlete_id, place in listed:
        body = bucket.objects[tables.place_key(version, athlete_id)]
        document = json.loads(gzip.decompress(body))
        first = date.fromisoformat(document["from"])
        week = document["weeks"][(mondays[-1] - first).days // 7]
        assert week[0] == place and week[1] == "-73"

    # a week later: the new Monday added to the state, unchanged athletes not uploaded again
    with engine.begin() as c:
        c.execute(text("update ajr.tables_export set pending_from = null"))
    before = dict(bucket.objects)
    with connection() as c:
        result = tables.publish(c, bucket, today=TODAY + timedelta(days=7))
    assert len(result.plan.days) == 1
    state = json.loads(gzip.decompress(bucket.objects[tables.places_state_key(version)]))
    athlete_id = str(listed[0][0])
    assert len(state[athlete_id]) - 1 == len(mondays) + 1  # every week, the new one too
    changed = [
        k for k in bucket.objects if k.startswith("places/") and before.get(k) != bucket.objects[k]
    ]
    assert set(changed) <= {tables.place_key(version, a) for a in state} | {
        tables.places_state_key(version), tables.nations_state_key(version)}  # fmt: skip


def test_publish_writes_the_nations_weeks_and_again_only_the_changed(monkeypatch):
    add_data()
    run_rating()
    monkeypatch.setattr(tables, "FIRST_DAY", TODAY - timedelta(days=21))
    with engine.begin() as c:
        c.execute(text("insert into ajr.nation_history select date '2026-11-01', id, 1, 1700"
                       " from ajr.country where ioc = 'JPN'"))  # fmt: skip
    bucket = MemoryBucket()

    with connection() as c:
        tables.publish(c, bucket, today=TODAY)

    version = json.loads(bucket.objects["manifest.json"])["version"]
    document = json.loads(gzip.decompress(bucket.objects[tables.nation_key(version, "JPN")]))
    assert document["weeks"] == [["2026-11-01", 1, 1700]]

    # a week later, the same weeks: not uploaded again (gone from the memory: not put back)
    with engine.begin() as c:
        c.execute(text("update ajr.tables_export set pending_from = null"))
    del bucket.objects[tables.nation_key(version, "JPN")]
    with connection() as c:
        tables.publish(c, bucket, today=TODAY + timedelta(days=7))
    assert tables.nation_key(version, "JPN") not in bucket.objects


def test_merge_places_replaces_the_weeks_from_start_and_trims_absent_ones():
    state = {"1": [0, 1024, 2048, 3072], "2": [2, 5000]}

    merged = tables.merge_places(state, 2, [{1: 9999}, {}, {3: 4096}])

    assert merged["1"] == [0, 1024, 2048, 9999]  # week 2 replaced, the empty weeks trimmed
    assert "2" not in merged  # only weeks from 2 on, none now
    assert merged["3"] == [4, 4096]
    assert tables.unpack(tables.pack(12, 3, 2)) == [12, "-73", 3]
    assert tables.unpack(tables.pack(40, None, 13)) == [40, "+78", None]
