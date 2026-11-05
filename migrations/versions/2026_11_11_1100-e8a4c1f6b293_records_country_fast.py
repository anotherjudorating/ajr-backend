"""records country fast

The records page and the country page read far less (docs/audits/2026-11-05-queries.md,
F4, F6). Same rows.

- api.records numbered every row of every record (7,752) after looking up its
  athlete, opponent, nation and tournament, to keep the first few of each: about
  2,250 pages per call, three calls per page, and 9.8 s on average on a day the disk
  was throttled. ajr.record now holds those names itself (the records job writes them
  after computing the records, from the same joins, and this migration fills the
  rows there are), and api.records takes the first rows of each record from the
  index on (record, place); api.record reads only its record's rows.
- api.country counted the nation's athletes and found its best scores through the
  athletes' table; ajr.athlete_summary and ajr.leaderboard_snapshot carry the
  nation's code already: an index on each answers both.

The names in ajr.record are those of the records job's run: a name judobase corrects
shows there with the next run (a week at most).

Revision ID: e8a4c1f6b293
Revises: d7f3b9e2a514
Create Date: 2026-11-11 11:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8a4c1f6b293"
down_revision: Union[str, Sequence[str], None] = "d7f3b9e2a514"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAME_COLUMNS = [
    "family_name",
    "given_name",
    "gender",
    "opponent_family_name",
    "opponent_given_name",
    "country",
    "country_name",
    "competition",
]

# As ajr/records/job.py's NAMES: a nation's record has the nation, an athlete's their
# nation.
NAMES = """
update ajr.record r
set family_name = a.family_name,
    given_name = a.given_name,
    gender = a.gender,
    opponent_family_name = o.family_name,
    opponent_given_name = o.given_name,
    country = co.ioc,
    country_name = co.name,
    competition = cm.name
from ajr.record named
left join ajr.athlete a on a.id = named.athlete_id
left join ajr.athlete o on o.id = named.opponent_id
left join ajr.country co on co.id = coalesce(named.country_id, a.country_id)
left join ajr.competition cm on cm.id = named.competition_id
where named.id = r.id
"""

COLUMNS = """
    record::text as record,
    place,
    athlete_id,
    family_name,
    given_name,
    gender,
    opponent_id,
    opponent_family_name,
    opponent_given_name,
    country,
    country_name,
    competition_id,
    competition,
    weight::text as weight,
    value,
    detail,
    day
"""

RECORDS = f"""
create or replace function api.records(top integer default 10, for_gender text default null)
returns table (
    record text,
    place integer,
    athlete_id integer,
    family_name text,
    given_name text,
    gender text,
    opponent_id integer,
    opponent_family_name text,
    opponent_given_name text,
    country text,
    country_name text,
    competition_id integer,
    competition text,
    weight text,
    value double precision,
    detail jsonb,
    day date
)
language sql stable security definer
set search_path = ''
as $$
    -- The records' names, one index step each, then the first rows of each.
    with recursive names(record) as (
        (select r.record from ajr.record r order by r.record limit 1)
        union all
        select (select r.record from ajr.record r where r.record > n.record
                order by r.record limit 1)
        from names n
        where n.record is not null
    )
    select top_rows.record, top_rows.place, top_rows.athlete_id, top_rows.family_name,
           top_rows.given_name, top_rows.gender, top_rows.opponent_id,
           top_rows.opponent_family_name, top_rows.opponent_given_name, top_rows.country,
           top_rows.country_name, top_rows.competition_id, top_rows.competition,
           top_rows.weight, top_rows.value, top_rows.detail, top_rows.day
    from names n
    cross join lateral (
        select {COLUMNS}, r.id
        from ajr.record r
        where r.record = n.record
          and (records.for_gender is null or r.athlete_id is null
               or r.gender = records.for_gender)
        order by r.place, r.id
        limit records.top
    ) top_rows
    where n.record is not null
    order by top_rows.record, top_rows.place, top_rows.id
$$
"""

RECORD = f"""
create or replace function api.record(
    name text, for_gender text default null, only_weight text default null
)
returns table (
    record text,
    place integer,
    athlete_id integer,
    family_name text,
    given_name text,
    gender text,
    opponent_id integer,
    opponent_family_name text,
    opponent_given_name text,
    country text,
    country_name text,
    competition_id integer,
    competition text,
    weight text,
    value double precision,
    detail jsonb,
    day date
)
language sql stable security definer
set search_path = ''
as $$
    select {COLUMNS}
    from ajr.record r
    where r.record = record.name
      and (record.for_gender is null or r.athlete_id is null
           or r.gender = record.for_gender)
      and (record.only_weight is null or r.weight = record.only_weight)
    order by r.place, r.id
$$
"""

COUNTRY_INDEXES = [
    "create index ix_athlete_summary_country on ajr.athlete_summary (country)",
    "create index ix_leaderboard_snapshot_country_score on ajr.leaderboard_snapshot "
    "(country, score desc)",
]


def load_migration(name: str):
    """An earlier migration's module, to reuse its SQL."""
    import importlib.util
    from pathlib import Path

    path = next(Path(__file__).parent.glob(f"*{name}.py"))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rewrite(sql: str, *changes: tuple[str, str]) -> str:
    """An earlier function's SQL as a replacement, with the given changes."""
    sql = sql.replace("create function", "create or replace function")
    for old, new in changes:
        assert old in sql, old
        sql = sql.replace(old, new)
    return sql


def country(new: bool) -> str:
    """api.country, reading the nation's code from the summaries (new) or not."""
    module = load_migration("5d1c2b7e9a40_country")
    if not new:
        return rewrite(module.COUNTRY)
    return rewrite(
        module.COUNTRY,
        (
            """            from ajr.athlete_summary s
            join ajr.athlete a on a.id = s.athlete_id
            where a.country_id = co.id),""",
            """            from ajr.athlete_summary s
            where s.country = co.ioc),  -- ix_athlete_summary_country""",
        ),
        (
            """            from ajr.leaderboard_snapshot l
            join ajr.athlete a on a.id = l.athlete_id
            where a.country_id = co.id
            order by l.score desc""",
            """            from ajr.leaderboard_snapshot l
            where l.country = co.ioc  -- ix_leaderboard_snapshot_country_score
            order by l.score desc""",
        ),
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "alter table ajr.record "
        + ", ".join(f"add column {column} text" for column in NAME_COLUMNS)
    )
    op.execute(NAMES)
    op.execute(RECORDS)
    op.execute(RECORD)
    for statement in COUNTRY_INDEXES:
        op.execute(statement)
    op.execute(country(new=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(country(new=False))
    op.execute("drop index ajr.ix_leaderboard_snapshot_country_score")
    op.execute("drop index ajr.ix_athlete_summary_country")
    records = load_migration("0e0fe6ec9e08_records")
    op.execute(rewrite(records.RECORDS))
    op.execute(rewrite(records.RECORD))
    op.execute(
        "alter table ajr.record "
        + ", ".join(f"drop column {column}" for column in NAME_COLUMNS)
    )
