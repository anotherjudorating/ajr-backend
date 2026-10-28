"""Test database setup.

Tests use TEST_DATABASE_URL when it is set (CI runs a Postgres service), otherwise
they start a throwaway Postgres in a temporary folder and delete it afterwards.

The URL goes into DATABASE_URL before any ajr module is imported, so the app's
engine talks to the test database. Anything that is not a local database is
refused: tests wipe tables and must never reach Supabase.
"""

import os
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).parents[1]
local_postgres_dir: Path | None = None


def pytest_configure(config: pytest.Config) -> None:
    url = os.environ.get("TEST_DATABASE_URL") or start_local_postgres()
    if urlparse(url).hostname not in ("localhost", "127.0.0.1"):
        pytest.exit(f"Refusing to run tests against a non-local database: {url}")
    os.environ["DATABASE_URL"] = url
    prepare_database()


def pytest_unconfigure(config: pytest.Config) -> None:
    if local_postgres_dir is not None:
        pg_ctl("stop", "-m", "immediate")
        shutil.rmtree(local_postgres_dir, ignore_errors=True)


def start_local_postgres() -> str:
    global local_postgres_dir
    local_postgres_dir = Path(tempfile.mkdtemp(prefix="ajr-test-postgres-"))
    port = free_port()
    subprocess.run(
        ["initdb", "-D", str(local_postgres_dir / "data"), "-U", "postgres", "-A", "trust"],
        check=True,
        capture_output=True,
    )
    pg_ctl(
        "start",
        "-w",
        "-l",
        str(local_postgres_dir / "log"),
        "-o",
        f"-p {port} -c listen_addresses=127.0.0.1 -c unix_socket_directories=''",
    )
    return f"postgresql+psycopg://postgres@127.0.0.1:{port}/postgres"


def pg_ctl(*args: str) -> None:
    assert local_postgres_dir is not None
    subprocess.run(
        ["pg_ctl", "-D", str(local_postgres_dir / "data"), *args], check=True, capture_output=True
    )


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def prepare_database() -> None:
    """Supabase roles the migration refers to, then all migrations."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from ajr.core.db import engine

    with engine.begin() as connection:
        for role in ("anon", "authenticated"):
            connection.execute(
                text(
                    f"do $$ begin create role {role}; "
                    "exception when duplicate_object then null; end $$"
                )
            )
        # Like Supabase's pooler: floats are sent with fewer digits unless asked.
        connection.execute(
            text(
                "do $$ begin execute format("
                "'alter database %I set extra_float_digits = 0', current_database()); end $$"
            )
        )
    engine.dispose()  # new connections pick the setting up
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")


@pytest.fixture
def clean_db() -> None:
    """Empty every table of our schema (the migration version stays)."""
    from sqlalchemy import text

    from ajr.core.db import engine
    from ajr.core.models import SCHEMA

    with engine.begin() as connection:
        tables = connection.execute(
            text(
                "select tablename from pg_tables "
                "where schemaname = :schema and tablename <> 'alembic_version'"
            ),
            {"schema": SCHEMA},
        ).scalars()
        names = ", ".join(f"{SCHEMA}.{name}" for name in tables)
        connection.execute(text(f"truncate {names} restart identity cascade"))
