"""Copy what changed in a working copy of the database to production.

The update job computes on its own Postgres (a working copy of production: sync,
rating, snapshots, records), then publishes: only the rows that differ go to
production, in one transaction, so production serves the site and does none of the
work, and a run that changed nothing writes nothing.

What production has is kept in the working copy too, in the schema `published`
(one table per published table, same columns, no constraints): the rows to send are
`ajr.<table> except published.<table>`, the rows to delete the keys of
`published.<table>` missing from `ajr.<table>`. After production commits, `published`
is set to the new rows.

A table whose columns differ from its copy in `published` (a migration changed it,
or `published` does not have it yet) is sent whole: every row, and production deletes
the rows the working copy does not have.

Every table of our schema is published, except the ones production writes itself
(NOT_PUBLISHED). Rows go through binary COPY, so values arrive exactly as computed.
"""

import logging
from dataclasses import dataclass

from psycopg import Connection, sql

logger = logging.getLogger(__name__)

SCHEMA = "ajr"
PUBLISHED = "published"
NOT_PUBLISHED = {
    "alembic_version",  # migrations run on each database
    "matchup_views",  # counted by the site's visitors
}
# Published, but not what the site's pages show: a change to them alone does not
# make the site refresh its cache (every run logs itself in job_run; the site only
# shows the day of the last update, which changes with today's tables anyway).
NOT_SHOWN = {"job_run"}
# Columns the site's pages do not show: rows that differ only in them are published
# but do not refresh the site. judobase's updated_at of a tournament moves all the
# while it runs (its schedule, mats, contests under way), and the sync keeps it with
# what it fetched (ajr/sync/job.py): 88 of 97 refreshes on 2026-11-03..07 changed only
# these (docs/audits/2026-11-07-vercel-isr-writes.md). A column a page starts to show
# leaves this list.
NOT_SHOWN_COLUMNS = {"competition": {"updated_at", "contests_synced_for", "results_changed_at"}}


def site_changed(changes: list[Change]) -> bool:
    """Whether a publish changed anything the site's pages show."""
    return any(c.shown and c.table not in NOT_SHOWN for c in changes)


@dataclass(frozen=True)
class Table:
    name: str
    columns: list[str]
    key: list[str]  # primary key


@dataclass(frozen=True)
class Change:
    table: str
    upserted: int
    deleted: int
    whole: bool  # sent whole (its columns changed)
    # a row sent or deleted differs in a column the site shows (NOT_SHOWN_COLUMNS)
    shown: bool = True


# Our tables with their columns and primary key, parents before the tables that
# refer to them (an upsert of a contest needs its athletes already there).
TABLES_QUERY = """
    select c.relname,
           (select array_agg(a.attname order by a.attnum) from pg_attribute a
            where a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped),
           (select array_agg(a.attname order by k.ordinality)
            from pg_constraint p
            cross join unnest(p.conkey) with ordinality k(attnum, ordinality)
            join pg_attribute a on a.attrelid = c.oid and a.attnum = k.attnum
            where p.conrelid = c.oid and p.contype = 'p'),
           array(select f.confrelid::regclass::text from pg_constraint f
                 where f.conrelid = c.oid and f.contype = 'f' and f.confrelid <> c.oid)
    from pg_class c
    where c.relnamespace = %s::regnamespace and c.relkind = 'r'
    order by c.relname
"""


def published_tables(connection: Connection) -> list[Table]:
    rows = connection.execute(TABLES_QUERY, [SCHEMA]).fetchall()
    tables = {
        name: (Table(name, columns, key or []), parents) for name, columns, key, parents in rows
    }
    ordered: list[Table] = []
    done: set[str] = set()

    def visit(name: str) -> None:
        if name in done or name not in tables:
            return
        done.add(name)
        table, parents = tables[name]
        for parent in parents:
            visit(parent.removeprefix(f"{SCHEMA}."))
        ordered.append(table)

    for name in tables:
        visit(name)
    result = [table for table in ordered if table.name not in NOT_PUBLISHED]
    if keyless := [table.name for table in result if not table.key]:
        raise ValueError(f"tables without a primary key cannot be published: {keyless}")
    return result


def columns_of(connection: Connection, schema: str, table: str) -> list[str] | None:
    row = connection.execute(
        """
        select array_agg(a.attname order by a.attnum) from pg_attribute a
        where a.attrelid = to_regclass(%s) and a.attnum > 0 and not a.attisdropped
        """,
        [f"{schema}.{table}"],
    ).fetchone()
    return row[0] if row else None


def names(columns: list[str]) -> sql.Composable:
    return sql.SQL(", ").join(map(sql.Identifier, columns))


def stream(
    local: Connection,
    remote: Connection,
    query: sql.Composable,
    into: sql.Identifier,
    columns: sql.Composable,
) -> int:
    """Rows of a query on the working copy into a temporary table on production; how many."""
    with local.cursor().copy(sql.SQL("copy ({}) to stdout (format binary)").format(query)) as out:
        with remote.cursor().copy(
            sql.SQL("copy {} ({}) from stdin (format binary)").format(into, columns)
        ) as copy:
            for block in out:
                copy.write(block)
    # a binary COPY gives no row count
    return remote.execute(sql.SQL("select count(*) from {}").format(into)).fetchone()[0]


@dataclass(frozen=True)
class Staged:
    table: Table
    upserts: sql.Identifier | None  # temporary tables on production; None: unchanged
    keys: sql.Identifier | None
    whole: bool
    upserted: int
    shown: bool = True  # see Change


def stage(local: Connection, remote: Connection, table: Table) -> Staged:
    """The table's rows to upsert and keys to delete (or to keep, when sent whole),
    copied into temporary tables on production."""
    ours = sql.Identifier(SCHEMA, table.name)
    theirs = sql.Identifier(PUBLISHED, table.name)
    cols, key = names(table.columns), names(table.key)
    whole = columns_of(local, PUBLISHED, table.name) != table.columns
    if whole:
        rows = sql.SQL("select {} from {}").format(cols, ours)
        keys = sql.SQL("select {} from {}").format(key, ours)  # the ones to keep
    else:
        rows = sql.SQL("select {} from {} except select {} from {}").format(
            cols, ours, cols, theirs
        )
        keys = sql.SQL("select {} from {} except select {} from {}").format(key, theirs, key, ours)
        unchanged = not local.execute(
            sql.SQL("select exists ({}) or exists ({})").format(rows, keys)
        ).fetchone()[0]
        if unchanged:  # production is not asked anything
            return Staged(table, None, None, False, 0, shown=False)
    shown = whole or shown_change(local, table, ours, theirs, keys)

    upserts = sql.Identifier(f"publish_{table.name}")
    deletes = sql.Identifier(f"publish_{table.name}_keys")
    for temp, columns in ((upserts, cols), (deletes, key)):
        remote.execute(
            sql.SQL("create temp table {} on commit drop as select {} from {} limit 0").format(
                temp, columns, ours
            )
        )
    # numbered, to upsert them in parts
    remote.execute(
        sql.SQL("alter table {} add column publish_n bigint generated always as identity").format(
            upserts
        )
    )
    upserted = stream(local, remote, rows, upserts, cols)
    stream(local, remote, keys, deletes, key)
    return Staged(table, upserts, deletes, whole, upserted, shown)


def shown_change(
    local: Connection,
    table: Table,
    ours: sql.Identifier,
    theirs: sql.Identifier,
    keys: sql.Composable,
) -> bool:
    """Whether the table's changes touch what the site shows: a row deleted, or one
    new or different in a column not in NOT_SHOWN_COLUMNS."""
    hidden = NOT_SHOWN_COLUMNS.get(table.name)
    if not hidden:
        return True
    shown = names([c for c in table.columns if c not in hidden])
    return local.execute(
        sql.SQL("select exists ({}) or exists (select {} from {} except select {} from {})").format(
            keys, shown, ours, shown, theirs
        )
    ).fetchone()[0]


# Rows per upsert statement: production's statements have a 2-minute limit, and a
# night when judobase changed old results rewrites most of the history (450 thousand
# rows of rating_change, one statement of which took about 3 minutes). The parts run
# in the same transaction: the site still sees all of a run's changes at once.
UPSERT_ROWS = 50_000


def upsert(remote: Connection, staged: Staged) -> None:
    table = staged.table
    cols, key = names(table.columns), names(table.key)
    updates = [column for column in table.columns if column not in table.key]
    on_conflict = (
        sql.SQL("do update set {}").format(
            sql.SQL(", ").join(
                sql.SQL("{} = excluded.{}").format(sql.Identifier(c), sql.Identifier(c))
                for c in updates
            )
        )
        if updates
        else sql.SQL("do nothing")
    )
    statement = sql.SQL(
        "insert into {} ({}) select {} from {} where publish_n > %s and publish_n <= %s "
        "on conflict ({}) {}"
    ).format(sql.Identifier(SCHEMA, table.name), cols, cols, staged.upserts, key, on_conflict)
    for first in range(0, staged.upserted, UPSERT_ROWS):
        remote.execute(statement, [first, first + UPSERT_ROWS])


def delete(remote: Connection, staged: Staged) -> int:
    if staged.keys is None:
        return 0
    table = staged.table
    ours = sql.Identifier(SCHEMA, table.name)
    match = sql.SQL(" and ").join(
        sql.SQL("t.{} = k.{}").format(sql.Identifier(c), sql.Identifier(c)) for c in table.key
    )
    if staged.whole:  # production keeps only the rows the working copy has
        statement = sql.SQL("delete from {} t where not exists (select from {} k where {})")
    else:
        statement = sql.SQL("delete from {} t where exists (select from {} k where {})")
    return remote.execute(statement.format(ours, staged.keys, match)).rowcount


def remember(local: Connection, tables: list[Table], changes: list[Change]) -> None:
    """Set `published` to what production now has (the working copy's rows)."""
    local.execute(sql.SQL("create schema if not exists {}").format(sql.Identifier(PUBLISHED)))
    for table, change in zip(tables, changes, strict=True):
        if not (change.whole or change.upserted or change.deleted):
            continue
        theirs = sql.Identifier(PUBLISHED, table.name)
        local.execute(sql.SQL("drop table if exists {}").format(theirs))
        local.execute(
            sql.SQL("create table {} as select {} from {}").format(
                theirs, names(table.columns), sql.Identifier(SCHEMA, table.name)
            )
        )


def adopt(local: Connection) -> None:
    """The working copy was just restored from production: remember all of it as
    what production has, so the next publish sends only what changes."""
    tables = published_tables(local)
    remember(local, tables, [Change(table.name, 0, 0, True) for table in tables])
    local.commit()


def publish(local: Connection, remote: Connection, dry_run: bool = False) -> list[Change]:
    """Send what changed in the working copy (`local`) to production (`remote`) in
    one transaction, then remember it in the working copy. Both connections must not
    be in autocommit mode; both are committed here. A dry run does it all on
    production, then rolls back and remembers nothing: what would be sent."""
    tables = published_tables(local)
    remote_tables = {table.name: table for table in published_tables(remote)}
    for table in tables:
        if remote_tables.get(table.name) != table:
            raise ValueError(
                f"ajr.{table.name} differs between the working copy and production: "
                "migrate both to the same version first"
            )
    staged = [stage(local, remote, table) for table in tables]
    # Upserts parents first (a new contest needs its athletes), deletes children first
    # (an athlete can go once no contest refers to it).
    for each in staged:
        if each.upserted:
            upsert(remote, each)
    deleted = {each.table.name: delete(remote, each) for each in reversed(staged)}
    changes = [
        Change(each.table.name, each.upserted, deleted[each.table.name], each.whole, each.shown)
        for each in staged
    ]
    if dry_run:
        remote.rollback()
        local.rollback()
    else:
        remote.commit()
        remember(local, tables, changes)
        local.commit()
    for change in changes:
        if change.whole or change.upserted or change.deleted:
            logger.info(
                "%s %s: %d upserted, %d deleted%s", "Would publish" if dry_run else "Published",
                change.table, change.upserted, change.deleted,
                " (whole table)" if change.whole else "",
            )  # fmt: skip
    return changes


# Per table: its rows and a sum of their hashes, which does not depend on their
# order (so no sort). Floats in full, whatever the connection's setting.
CHECK_QUERY = "select count(*), coalesce(sum(hashtextextended(t::text, 0)), 0) from {} t"


@dataclass(frozen=True)
class Difference:
    table: str
    local_rows: int
    remote_rows: int


def check(local: Connection, remote: Connection) -> list[Difference]:
    """The tables whose rows differ between the working copy and production. Reads
    every published table on both: a full pass over production's tables."""
    differences = []
    for connection in (local, remote):
        connection.execute("set extra_float_digits = 3")
    for table in published_tables(local):
        query = sql.SQL(CHECK_QUERY).format(sql.Identifier(SCHEMA, table.name))
        ours = local.execute(query).fetchone()
        theirs = remote.execute(query).fetchone()
        if ours != theirs:
            differences.append(Difference(table.name, ours[0], theirs[0]))
    local.rollback()
    remote.rollback()
    return differences
