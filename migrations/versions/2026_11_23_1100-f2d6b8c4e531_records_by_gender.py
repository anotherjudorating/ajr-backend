"""records by gender

The records of nations and tournaments were the same for men and women (a nation's
medals, its team, a tournament's strength counted both). The records job now
computes them for both together and for each gender (ajr/records/queries.py
BY_GENDER, weekly.py), the rows marked with their gender; api.records and
api.record give, for both genders, the athletes' rows and the nations' and
tournaments' rows for both, and for one gender only its rows. Until the next records
run a nation's or tournament's record has no rows for one gender.

Revision ID: f2d6b8c4e531
Revises: e9c5a1b3d420
Create Date: 2026-11-23 11:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2d6b8c4e531"
down_revision: Union[str, Sequence[str], None] = "e9c5a1b3d420"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

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
          -- both genders: the athletes' rows and the nations' and tournaments' for
          -- both; one: its athletes' rows and its nations' and tournaments'
          and (case when records.for_gender is null
                    then r.athlete_id is not null or r.gender is null
                    else r.gender = records.for_gender end)
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
      and (case when record.for_gender is null then r.athlete_id is not null or r.gender is null
                else r.gender = record.for_gender end)
      and (record.only_weight is null or r.weight = record.only_weight)
    order by r.place, r.id
$$
"""

OLD_RECORDS = f"""
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

OLD_RECORD = f"""
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


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(RECORDS)
    op.execute(RECORD)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(OLD_RECORDS)
    op.execute(OLD_RECORD)
