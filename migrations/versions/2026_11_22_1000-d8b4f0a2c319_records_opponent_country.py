"""records opponent country

A record with a second athlete (the biggest upsets, the fastest wins) shows the
opponent's flag too: ajr.record holds the opponent's nation as it holds their name
(the records job writes it with the names; this migration fills the rows there are),
and api.records and api.record return it. A new column changes the functions' result
type: dropped and created again.

Revision ID: d8b4f0a2c319
Revises: c7a3e9f1d208
Create Date: 2026-11-22 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8b4f0a2c319"
down_revision: Union[str, Sequence[str], None] = "c7a3e9f1d208"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# As ajr/records/job.py's NAMES, for the opponent's nation only.
FILL = """
update ajr.record r
set opponent_country = co.ioc
from ajr.athlete o
join ajr.country co on co.id = o.country_id
where o.id = r.opponent_id
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
    opponent_country,
    country,
    country_name,
    competition_id,
    competition,
    weight::text as weight,
    value,
    detail,
    day
"""

OLD_COLUMNS = """
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
create function api.records(top integer default 10, for_gender text default null)
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
    opponent_country text,
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
           top_rows.opponent_family_name, top_rows.opponent_given_name,
           top_rows.opponent_country, top_rows.country,
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
create function api.record(
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
    opponent_country text,
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

OLD_RECORDS = f"""
create function api.records(top integer default 10, for_gender text default null)
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
        select {OLD_COLUMNS}, r.id
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

OLD_RECORD = f"""
create function api.record(
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
    select {OLD_COLUMNS}
    from ajr.record r
    where r.record = record.name
      and (record.for_gender is null or r.athlete_id is null
           or r.gender = record.for_gender)
      and (record.only_weight is null or r.weight = record.only_weight)
    order by r.place, r.id
$$
"""

SIGNATURES = ("api.records(integer, text)", "api.record(text, text, text)")


def replace(*definitions: str) -> None:
    for signature in SIGNATURES:
        op.execute(f"drop function {signature}")
    for definition in definitions:
        op.execute(definition)
    for signature in SIGNATURES:
        op.execute(f"revoke execute on function {signature} from public")
        op.execute(f"grant execute on function {signature} to anon, authenticated")


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("alter table ajr.record add column opponent_country text")
    op.execute(FILL)
    replace(RECORDS, RECORD)


def downgrade() -> None:
    """Downgrade schema."""
    replace(OLD_RECORDS, OLD_RECORD)
    op.execute("alter table ajr.record drop column opponent_country")
