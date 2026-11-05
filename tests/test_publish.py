"""Publishing the working copy's changes to production: two test databases."""

import os
from datetime import date

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from conftest import ROOT
from sqlalchemy import create_engine, make_url, text
from sqlmodel import Session

from ajr.core.db import engine
from ajr.core.models import Athlete, Competition, Contest, Country
from ajr.publish import NOT_PUBLISHED, Change, check, publish, published_tables, site_changed

pytestmark = pytest.mark.usefixtures("clean_db")

REMOTE = "ajr_test_production"


def plain(url) -> str:
    """psycopg's own URL (no SQLAlchemy driver name)."""
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


@pytest.fixture(scope="module")
def production_url():
    """A second database migrated like the first: production, for these tests."""
    url = make_url(os.environ["DATABASE_URL"])
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(f"drop database if exists {REMOTE} with (force)"))
        connection.execute(text(f"create database {REMOTE}"))
    production = create_engine(url.set(database=REMOTE))
    with production.connect() as connection:
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    production.dispose()
    yield plain(url.set(database=REMOTE))
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(f"drop database {REMOTE} with (force)"))


@pytest.fixture
def connections(production_url):
    """The working copy (the tests' database, emptied, without `published`) and
    production (emptied)."""
    with psycopg.connect(production_url) as remote:
        tables = remote.execute(
            "select string_agg('ajr.' || tablename, ', ') from pg_tables "
            "where schemaname = 'ajr' and tablename <> 'alembic_version'"
        ).fetchone()[0]
        remote.execute(f"truncate {tables} cascade")
        remote.commit()
    with psycopg.connect(plain(make_url(os.environ["DATABASE_URL"]))) as local:
        local.execute("drop schema if exists published cascade")
        local.commit()
        with psycopg.connect(production_url) as remote:
            yield local, remote


def add_data() -> None:
    with Session(engine) as session:
        session.add(Country(id=1, name="Japan", ioc="JPN"))
        session.add(Competition(id=10, name="Grand Slam", date_from=date(2026, 3, 1)))
        session.flush()
        session.add_all(Athlete(id=i, family_name=f"A{i}", country_id=1) for i in (1, 2, 3))
        session.flush()
        session.add_all(
            [
                Contest(id=101, competition_id=10, blue_id=1, white_id=2, winner_id=1),
                Contest(id=102, competition_id=10, blue_id=1, white_id=3, winner_id=3),
            ]
        )
        session.commit()


def rows(connection, table: str) -> list[tuple]:
    return connection.execute(f"select * from ajr.{table} order by 1, 2").fetchall()


def assert_same(local, remote) -> None:
    for table in published_tables(local):
        assert rows(local, table.name) == rows(remote, table.name), table.name


def changed(changes: list[Change]) -> dict[str, tuple[int, int]]:
    return {c.table: (c.upserted, c.deleted) for c in changes if c.upserted or c.deleted}


def run(statement: str) -> None:
    with engine.begin() as connection:
        connection.execute(text(statement))


def test_parents_come_before_the_tables_that_refer_to_them(connections):
    local, _ = connections
    order = [table.name for table in published_tables(local)]
    assert order.index("country") < order.index("athlete") < order.index("contest")
    assert order.index("contest") < order.index("rating_change")
    assert not NOT_PUBLISHED & set(order)


def test_the_first_publish_sends_every_table_whole(connections):
    local, remote = connections
    add_data()

    changes = publish(local, remote)

    assert all(change.whole for change in changes)
    assert changed(changes) == {
        "country": (1, 0),
        "competition": (1, 0),
        "athlete": (3, 0),
        "contest": (2, 0),
    }
    assert_same(local, remote)


def test_then_only_what_changed(connections):
    local, remote = connections
    add_data()
    publish(local, remote)

    assert changed(publish(local, remote)) == {}  # nothing changed: nothing sent

    run("update ajr.athlete set given_name = 'Hifumi' where id = 1")
    run("insert into ajr.athlete (id, family_name, country_id) values (4, 'A4', 1)")
    with Session(engine) as session:
        session.add(Contest(id=103, competition_id=10, blue_id=4, white_id=2, winner_id=4))
        session.commit()
    changes = publish(local, remote)

    assert not any(change.whole for change in changes)
    assert changed(changes) == {"athlete": (2, 0), "contest": (1, 0)}
    assert_same(local, remote)


def test_deleted_rows_children_first(connections):
    local, remote = connections
    add_data()
    publish(local, remote)

    # the sync removed contest 102, and athlete 3 with it
    run("delete from ajr.contest where id = 102")
    run("delete from ajr.athlete where id = 3")

    assert changed(publish(local, remote)) == {"athlete": (0, 1), "contest": (0, 1)}
    assert_same(local, remote)


def test_a_table_whose_columns_changed_is_sent_whole(connections):
    local, remote = connections
    add_data()
    publish(local, remote)
    # production has a row the working copy does not (say, written by hand)
    remote.execute("insert into ajr.athlete (id, family_name, country_id) values (9, 'X', 1)")
    remote.commit()
    # as after a migration of the table: its copy in `published` no longer matches
    local.execute("alter table published.athlete drop column given_name")
    local.commit()

    changes = {change.table: change for change in publish(local, remote)}

    assert changes["athlete"].whole and changes["athlete"].deleted == 1
    assert not changes["contest"].whole
    assert_same(local, remote)


def test_production_keeps_its_own_tables(connections):
    local, remote = connections
    add_data()
    publish(local, remote)
    remote.execute("insert into ajr.matchup_views (a, b, views) values (1, 2, 5)")
    remote.commit()

    run("update ajr.athlete set given_name = 'Hifumi' where id = 1")
    publish(local, remote)

    assert rows(remote, "matchup_views") == [(1, 2, 5)]


def test_the_runs_log_is_published_with_the_data(connections):
    local, remote = connections
    run("insert into ajr.job_run (type, status, started_at) values ('rating', 'success', now())")

    publish(local, remote)

    assert [(r[1], r[2]) for r in rows(remote, "job_run")] == [("rating", "success")]


def test_a_different_schema_is_refused(connections):
    local, remote = connections
    remote.execute("alter table ajr.athlete add column extra integer")
    remote.commit()

    with pytest.raises(ValueError, match="ajr.athlete differs"):
        publish(local, remote)

    remote.rollback()
    remote.execute("alter table ajr.athlete drop column extra")
    remote.commit()


def test_a_dry_run_writes_nothing_and_remembers_nothing(connections):
    local, remote = connections
    add_data()
    publish(local, remote)
    run("update ajr.athlete set given_name = 'Hifumi' where id = 1")

    assert changed(publish(local, remote, dry_run=True)) == {"athlete": (1, 0)}

    assert rows(remote, "athlete")[0][2] is None  # production still has the old name
    assert changed(publish(local, remote)) == {"athlete": (1, 0)}  # sent for real now
    assert_same(local, remote)


def test_check_finds_the_tables_that_differ(connections):
    local, remote = connections
    add_data()
    publish(local, remote)
    assert check(local, remote) == []

    remote.execute("update ajr.contest set winner_id = 2 where id = 101")
    remote.commit()

    assert [d.table for d in check(local, remote)] == ["contest"]


def test_many_rows_are_upserted_in_parts(connections, monkeypatch):
    import ajr.publish

    local, remote = connections
    monkeypatch.setattr(ajr.publish, "UPSERT_ROWS", 2)  # three athletes: two parts
    add_data()

    assert changed(publish(local, remote))["athlete"] == (3, 0)
    assert_same(local, remote)


def test_a_run_that_only_logged_itself_does_not_refresh_the_site(connections):
    local, remote = connections
    add_data()
    publish(local, remote)

    run("insert into ajr.job_run (type, status, started_at) values ('sync', 'success', now())")
    assert not site_changed(publish(local, remote))  # job_run only

    run("update ajr.athlete set given_name = 'Hifumi' where id = 1")
    assert site_changed(publish(local, remote))
