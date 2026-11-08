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

    assert plan.full and plan.days[0] == tables.FIRST_DAY and plan.days[-1] == TODAY - timedelta(1)
    assert plan.delete == ["older"]


def test_a_night_adds_yesterday_and_a_correction_makes_a_new_generation():
    manifest = {"version": "v", "last_day": "2026-11-07", "generations": []}

    night = make_plan(manifest, State(None, "v", None), "v", TODAY, False, NOW)
    corrected = make_plan(manifest, State(date(2026, 10, 1), "v", None), "v", TODAY, False, NOW)

    assert night.days == [date(2026, 11, 8)] and night.generation == 0
    assert corrected.days[0] == date(2026, 10, 1) and corrected.generation == 1
    with_generation = {"generations": [{"from": "2026-10-01", "g": 1}]}
    assert generation_of(with_generation, date(2026, 9, 30)) == 0
    assert generation_of(with_generation, date(2026, 10, 1)) == 1


def test_publish_uploads_the_days_then_the_manifest_and_clears_the_mark(monkeypatch):
    add_data()
    run_rating()
    monkeypatch.setattr(tables, "FIRST_DAY", TODAY - timedelta(days=3))
    bucket = MemoryBucket()

    with connection() as c:
        result = tables.publish(c, bucket, today=TODAY)

    manifest = json.loads(bucket.objects["manifest.json"])
    assert result.plan.full and len(result.plan.days) == 3
    key = tables.day_key(manifest["version"], "rankings", "men-73", TODAY - timedelta(1), 0)
    document = json.loads(gzip.decompress(bucket.objects[key]))
    with connection() as c:
        expected = c.execute(
            "select count(*) from api.leaderboard('-73', %s)", [TODAY - timedelta(1)]
        ).fetchone()[0]
    assert len(document["rows"]) == expected
    assert manifest["last_day"] == (TODAY - timedelta(1)).isoformat()
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
