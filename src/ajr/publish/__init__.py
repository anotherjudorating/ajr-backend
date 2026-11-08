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
from psycopg.errors import LockNotAvailable

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
    swapped: bool = False  # built anew in its declared order and swapped in (SWAP_ORDER)


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
    freeze: bool = False,
) -> int:
    """Rows of a query on the working copy into a table on production; how many.
    `freeze`: the rows are written frozen and all-visible (the table must have been
    created in this transaction)."""
    options = sql.SQL("format binary, freeze" if freeze else "format binary")
    with local.cursor().copy(sql.SQL("copy ({}) to stdout (format binary)").format(query)) as out:
        with remote.cursor().copy(
            sql.SQL("copy {} ({}) from stdin ({})").format(into, columns, options)
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


def sent_whole(local: Connection, table: Table) -> bool:
    """A table whose columns differ from its copy in `published` (a migration changed
    it, or `published` does not have it yet) is sent whole."""
    return columns_of(local, PUBLISHED, table.name) != table.columns


def stage(local: Connection, remote: Connection, table: Table) -> Staged:
    """The table's rows to upsert and keys to delete (or to keep, when sent whole),
    copied into temporary tables on production."""
    ours = sql.Identifier(SCHEMA, table.name)
    theirs = sql.Identifier(PUBLISHED, table.name)
    cols, key = names(table.columns), names(table.key)
    whole = sent_whole(local, table)
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


# Tables published whole are not upserted row by row but built anew in this physical
# order and swapped in by rename (docs/audits/2026-11-08-b1-plan.md §5): the rows of one
# key then sit on few pages (an athlete's history: 64 pages instead of 440 on a copy of
# production), the table needs no VACUUM FULL afterwards, and the disk holds the old and
# the new table at once instead of the bloated one and its rewrite. A table referring to
# a swapped one is swapped with it, whatever changed in it: its foreign key must point
# at the new table. `python -m ajr.publish rebuild <table>` swaps one in order again
# when the 15-minute publishes have scattered its new rows.
SWAP_ORDER = {
    "rating_change": ["athlete_id", "seq"],  # an athlete's history (api.athlete_history)
    # a tournament's contests and results (api.competition_contests, api.competition_results);
    # competition ids grow with time, so a year's contests (api.contests) sit together too
    "contest_list": ["competition_id", "weight", "round_no", "fight_no"],
    "athlete_competition": ["competition_id", "weight", "athlete_id"],
    "nation_competition": ["country", "date_from", "competition_id"],  # api.country_tournaments
}
SWAP_LOCK_TIMEOUT = "5s"  # the renames wait for reads in flight; longer: the next run
NEW = "__new"
OLD = "__old"

REFERRERS_QUERY = """
    select distinct c.conrelid::regclass::text
    from pg_constraint c
    where c.contype = 'f' and c.confrelid = to_regclass(%s) and c.conrelid <> c.confrelid
"""


def swap_group(remote: Connection, tables: list[Table], swapping: set[str]) -> list[Table]:
    """The tables to build and swap: `swapping` and every table referring to one of
    them, parents first (as `tables` are)."""
    group = set(swapping)
    pending = list(swapping)
    while pending:
        name = pending.pop()
        for referrer in remote.execute(REFERRERS_QUERY, [f"{SCHEMA}.{name}"]).fetchall():
            schema, _, child = referrer[0].rpartition(".")
            if schema != SCHEMA:
                raise ValueError(f"{referrer[0]} refers to ajr.{name}: it cannot be swapped")
            if child not in group:
                group.add(child)
                pending.append(child)
    return [table for table in tables if table.name in group]


def build(local: Connection, remote: Connection, table: Table, group: set[str]) -> int:
    """ajr.<table>__new on production: the working copy's rows in the declared order
    (the primary key's for a table swapped with its parent), with the old table's
    indexes, keys, foreign keys (not yet validated), grants and options; how many rows."""
    old = sql.Identifier(SCHEMA, table.name)
    new = sql.Identifier(SCHEMA, table.name + NEW)
    oid = remote.execute("select to_regclass(%s)::oid", [f"{SCHEMA}.{table.name}"]).fetchone()[0]
    others = remote.execute(
        "select count(*) from pg_constraint where conrelid = %s and contype in ('u', 'x')", [oid]
    ).fetchone()[0]
    triggers = remote.execute(
        "select count(*) from pg_trigger where tgrelid = %s and not tgisinternal", [oid]
    ).fetchone()[0]
    policies = remote.execute(
        "select count(*) from pg_policy where polrelid = %s", [oid]
    ).fetchone()[0]
    if others or triggers or policies:
        raise ValueError(
            f"ajr.{table.name} has constraints, triggers or policies a swap would lose"
        )

    remote.execute(sql.SQL("drop table if exists {}").format(new))
    remote.execute(
        sql.SQL(
            "create table {} (like {} including defaults including constraints including storage)"
        ).format(new, old)
    )
    order = SWAP_ORDER.get(table.name, table.key)
    rows = stream(
        local,
        remote,
        sql.SQL("select {} from {} order by {}").format(names(table.columns), old, names(order)),
        new,
        names(table.columns),
        freeze=True,
    )
    # indexes after the rows (faster), the primary key's through its constraint
    for name, definition in remote.execute(
        """
        select i.relname, pg_get_indexdef(i.oid)
        from pg_index x join pg_class i on i.oid = x.indexrelid
        where x.indrelid = %s
          and not exists (select from pg_constraint c where c.conindid = i.oid)
        """,
        [oid],
    ).fetchall():
        head = f"INDEX {name} ON {SCHEMA}.{table.name} "
        if head not in definition:
            raise ValueError(f"unexpected definition of index {name}: {definition}")
        remote.execute(
            definition.replace(head, f"INDEX {name}{NEW} ON {SCHEMA}.{table.name}{NEW} ")
        )
    for name, definition, kind in remote.execute(
        """
        select conname, pg_get_constraintdef(oid), contype from pg_constraint
        where conrelid = %s and contype in ('p', 'f')
        order by contype desc
        """,
        [oid],
    ).fetchall():
        if kind == "f":
            for parent in group:
                definition = definition.replace(
                    f"REFERENCES {SCHEMA}.{parent}(", f"REFERENCES {SCHEMA}.{parent}{NEW}("
                )
            definition += " NOT VALID"  # the rows come from a copy where it holds
        remote.execute(
            sql.SQL("alter table {} add constraint {} ").format(new, sql.Identifier(name + NEW))
            + sql.SQL(definition)
        )
    for grantee, privilege in remote.execute(
        """
        select coalesce(r.rolname, 'public'), a.privilege_type
        from pg_class c cross join aclexplode(c.relacl) a
        left join pg_roles r on r.oid = a.grantee
        where c.oid = %s and a.grantee <> c.relowner
        """,
        [oid],
    ).fetchall():
        remote.execute(
            sql.SQL("grant {} on {} to {}").format(
                sql.SQL(privilege),
                new,
                sql.SQL("public") if grantee == "public" else sql.Identifier(grantee),
            )  # fmt: skip
        )
    options, secured = remote.execute(
        "select reloptions, relrowsecurity from pg_class where oid = %s", [oid]
    ).fetchone()
    if options:
        remote.execute(sql.SQL("alter table {} set ({})").format(new, sql.SQL(", ".join(options))))
    if secured:
        remote.execute(sql.SQL("alter table {} enable row level security").format(new))
    remote.execute(sql.SQL("analyze {}").format(new))
    return rows


def swap(remote: Connection, group: list[Table]) -> None:
    """Put the new tables in place of the old ones, then give their indexes and
    constraints the old names: the last statements before the commit, so the
    exclusive locks last milliseconds (or the publish fails after SWAP_LOCK_TIMEOUT
    and the next run builds them again)."""
    remote.execute(sql.SQL("set local lock_timeout = {}").format(sql.Literal(SWAP_LOCK_TIMEOUT)))
    for table in reversed(group):  # children first
        remote.execute(
            sql.SQL("alter table {} rename to {}").format(
                sql.Identifier(SCHEMA, table.name), sql.Identifier(table.name + OLD)
            )
        )
    for table in group:
        remote.execute(
            sql.SQL("alter table {} rename to {}").format(
                sql.Identifier(SCHEMA, table.name + NEW), sql.Identifier(table.name)
            )
        )
    for table in reversed(group):
        remote.execute(sql.SQL("drop table {}").format(sql.Identifier(SCHEMA, table.name + OLD)))
    for table in group:
        oid = remote.execute("select to_regclass(%s)::oid", [f"{SCHEMA}.{table.name}"]).fetchone()[
            0
        ]
        for (index,) in remote.execute(
            "select i.relname from pg_index x join pg_class i on i.oid = x.indexrelid "
            "where x.indrelid = %s and i.relname like %s",
            [oid, f"%{NEW}"],
        ).fetchall():  # a primary key's index renames its constraint too
            remote.execute(
                sql.SQL("alter index {} rename to {}").format(
                    sql.Identifier(SCHEMA, index), sql.Identifier(index.removesuffix(NEW))
                )
            )
        for (constraint,) in remote.execute(
            "select conname from pg_constraint where conrelid = %s and conname like %s",
            [oid, f"%{NEW}"],
        ).fetchall():
            remote.execute(
                sql.SQL("alter table {} rename constraint {} to {}").format(
                    sql.Identifier(SCHEMA, table.name),
                    sql.Identifier(constraint),
                    sql.Identifier(constraint.removesuffix(NEW)),
                )
            )


def validate(remote: Connection, group: list[Table]) -> None:
    """Validate the swapped tables' foreign keys (made NOT VALID to spare a scan in the
    publish's transaction; reads go on meanwhile). Commits."""
    remote.execute("set statement_timeout = 0")  # this session's maintenance only
    for table in group:
        for (constraint,) in remote.execute(
            "select conname from pg_constraint "
            "where conrelid = to_regclass(%s) and not convalidated",
            [f"{SCHEMA}.{table.name}"],
        ).fetchall():
            remote.execute(
                sql.SQL("alter table {} validate constraint {}").format(
                    sql.Identifier(SCHEMA, table.name), sql.Identifier(constraint)
                )
            )
    remote.commit()


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


def publish(
    local: Connection, remote: Connection, dry_run: bool = False, rebuild: set[str] = frozenset()
) -> list[Change]:
    """Send what changed in the working copy (`local`) to production (`remote`) in
    one transaction, then remember it in the working copy. Both connections must not
    be in autocommit mode; both are committed here. A dry run does it all on
    production, then rolls back and remembers nothing: what would be sent. `rebuild`:
    tables of SWAP_ORDER to build and swap in order even if nothing changed."""
    tables = published_tables(local)
    remote_tables = {table.name: table for table in published_tables(remote)}
    for table in tables:
        if remote_tables.get(table.name) != table:
            raise ValueError(
                f"ajr.{table.name} differs between the working copy and production: "
                "migrate both to the same version first"
            )
    if unknown := set(rebuild) - SWAP_ORDER.keys():
        raise ValueError(f"only tables with a declared order can be rebuilt: {sorted(unknown)}")
    remote.execute("set local statement_timeout = 0")  # a swap copies whole tables
    swapping = {
        table.name
        for table in tables
        if table.name in SWAP_ORDER and (table.name in rebuild or sent_whole(local, table))
    }
    group = swap_group(remote, tables, swapping) if swapping else []
    group_names = {table.name for table in group}
    staged = [stage(local, remote, table) for table in tables if table.name not in group_names]
    built = {table.name: build(local, remote, table, group_names) for table in group}
    # Upserts parents first (a new contest needs its athletes), deletes children first
    # (an athlete can go once no contest refers to it).
    for each in staged:
        if each.upserted:
            upsert(remote, each)
    deleted = {each.table.name: delete(remote, each) for each in reversed(staged)}
    if group:
        swap(remote, group)
    by_name = {each.table.name: each for each in staged}
    changes = [
        Change(table.name, built[table.name], 0, True, True, swapped=True)
        if table.name in built
        else Change(
            table.name,
            by_name[table.name].upserted,
            deleted[table.name],
            by_name[table.name].whole,
            by_name[table.name].shown,
        )  # fmt: skip
        for table in tables
    ]
    if dry_run:
        remote.rollback()
        local.rollback()
    else:
        remote.commit()
        if group:
            validate(remote, group)
        remember(local, tables, changes)
        local.commit()
    for change in changes:
        if change.whole or change.upserted or change.deleted:
            logger.info(
                "%s %s: %d upserted, %d deleted%s", "Would publish" if dry_run else "Published",
                change.table, change.upserted, change.deleted,
                " (built in order and swapped)" if change.swapped
                else " (whole table)" if change.whole else "",
            )  # fmt: skip
    return changes


# A table rewritten for the most part (a full rating: every row of rating_change)
# leaves its old rows' space in the file: Postgres reuses it but never gives it back,
# and production (500 MB on the free plan) holds about twice its data after one
# (docs/audits, 2026-11-06: 531 MB, 270 MB compacted). So after such a publish the
# table is rewritten compactly (VACUUM FULL, then a plain VACUUM): it is locked
# meanwhile (about a minute for rating_change; the site serves its cache), and needs
# room for the new file.
# The 15-minute runs change a few hundred rows: nothing to do.
COMPACT_SHARE = 0.3  # of the table's rows sent or deleted
COMPACT_MIN_BYTES = 20 * 1024 * 1024
COMPACT_MIN_ROWS = 1000  # sent or deleted: below, not worth counting the table
COMPACT_LOCK_TIMEOUT = "30s"  # waiting for long reads; then left for the next time


def compact(remote: Connection, changes: list[Change]) -> list[str]:
    """VACUUM FULL production's tables that the publish rewrote for the most part;
    the ones compacted. Commits whatever `remote` has open (VACUUM runs outside a
    transaction)."""
    remote.commit()
    remote.autocommit = True
    done = []
    for change in changes:
        if change.swapped or change.upserted + change.deleted < COMPACT_MIN_ROWS:
            continue  # a swapped table was written compactly
        table = sql.Identifier(SCHEMA, change.table)
        size, rows = remote.execute(
            sql.SQL("select pg_table_size({}), (select count(*) from {})").format(
                sql.Literal(f"{SCHEMA}.{change.table}"), table
            )
        ).fetchone()
        if size < COMPACT_MIN_BYTES or change.upserted + change.deleted < COMPACT_SHARE * rows:
            continue
        remote.execute("set statement_timeout = 0")  # this session's maintenance only
        remote.execute(sql.SQL("set lock_timeout = {}").format(sql.Literal(COMPACT_LOCK_TIMEOUT)))
        try:
            remote.execute(sql.SQL("vacuum (full) {}").format(table))
        except LockNotAvailable:
            logger.warning("%s not compacted: a long read held it", change.table)
            continue
        # VACUUM FULL writes a new file with an empty visibility map: until a plain
        # VACUUM marks its pages all-visible, no index answers alone (the board's
        # index read thousands of pages, not 30; on 2026-11-07 athlete pages hit the
        # 3-second limit). A plain VACUUM takes no lock that blocks reads.
        remote.execute(sql.SQL("vacuum (analyze) {}").format(table))
        after = remote.execute(
            sql.SQL("select pg_table_size({})").format(sql.Literal(f"{SCHEMA}.{change.table}"))
        ).fetchone()[0]
        logger.info("Compacted %s: %d MB -> %d MB", change.table, size >> 20, after >> 20)
        done.append(change.table)
    return done


def database_size(remote: Connection) -> int:
    """Production's size in bytes (the free plan allows 500 MB)."""
    return remote.execute("select pg_database_size(current_database())").fetchone()[0]


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
