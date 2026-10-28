"""records

ajr.record holds the all-time bests of the records page, recomputed as a whole
by `python -m ajr.records` (see ajr/records/job.py). The site reads them with:

- api.records(top, for_gender): the first `top` rows of every record. With for_gender
  ('male' / 'female') only athletes of it; records of nations and tournaments
  are the same for both.
- api.record(name, for_gender, only_weight): every row of one record.

Revision ID: 0e0fe6ec9e08
Revises: 4ae485321e30
Create Date: 2026-10-28 19:05:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0e0fe6ec9e08"
down_revision: Union[str, Sequence[str], None] = "4ae485321e30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = """
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
"""

# The rows with names; a nation's record has the nation, an athlete's their nation.
SELECT = """
    select r.record::text,
           r.place,
           r.athlete_id,
           a.family_name::text,
           a.given_name::text,
           a.gender::text,
           r.opponent_id,
           o.family_name::text,
           o.given_name::text,
           co.ioc::text,
           co.name::text,
           r.competition_id,
           cm.name::text,
           r.weight::text,
           r.value,
           r.detail,
           r.day,
           r.id
    from ajr.record r
    left join ajr.athlete a on a.id = r.athlete_id
    left join ajr.athlete o on o.id = r.opponent_id
    left join ajr.country co on co.id = coalesce(r.country_id, a.country_id)
    left join ajr.competition cm on cm.id = r.competition_id
"""

RECORDS = f"""
create function api.records(top integer default 10, for_gender text default null)
returns table ({COLUMNS})
language sql stable security definer
set search_path = ''
as $$
    select record, place, athlete_id, family_name, given_name, gender, opponent_id,
           opponent_family_name, opponent_given_name, country, country_name,
           competition_id, competition, weight, value, detail, day
    from (
        select named.*, row_number() over (partition by named.record order by named.place, named.id) as n
        from ({SELECT}) named(record, place, athlete_id, family_name, given_name, gender,
                              opponent_id, opponent_family_name, opponent_given_name,
                              country, country_name, competition_id, competition, weight,
                              value, detail, day, id)
        where records.for_gender is null or named.athlete_id is null
           or named.gender = records.for_gender
    ) numbered
    where n <= records.top
    order by record, n
$$
"""

RECORD = f"""
create function api.record(
    name text, for_gender text default null, only_weight text default null
)
returns table ({COLUMNS})
language sql stable security definer
set search_path = ''
as $$
    select record, place, athlete_id, family_name, given_name, gender, opponent_id,
           opponent_family_name, opponent_given_name, country, country_name,
           competition_id, competition, weight, value, detail, day
    from ({SELECT}) named(record, place, athlete_id, family_name, given_name, gender,
                          opponent_id, opponent_family_name, opponent_given_name,
                          country, country_name, competition_id, competition, weight,
                          value, detail, day, id)
    where named.record = record.name
      and (record.for_gender is null or named.athlete_id is null
           or named.gender = record.for_gender)
      and (record.only_weight is null or named.weight = record.only_weight)
    order by place, id
$$
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "record",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("record", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("place", sa.Integer(), nullable=False),
        sa.Column("athlete_id", sa.Integer(), nullable=True),
        sa.Column("opponent_id", sa.Integer(), nullable=True),
        sa.Column("country_id", sa.Integer(), nullable=True),
        sa.Column("competition_id", sa.Integer(), nullable=True),
        sa.Column("weight", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("day", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(["athlete_id"], ["ajr.athlete.id"]),
        sa.ForeignKeyConstraint(["competition_id"], ["ajr.competition.id"]),
        sa.ForeignKeyConstraint(["country_id"], ["ajr.country.id"]),
        sa.ForeignKeyConstraint(["opponent_id"], ["ajr.athlete.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="ajr",
    )
    op.create_index(
        "ix_record_record_place", "record", ["record", "place"], unique=False, schema="ajr"
    )
    op.execute(RECORDS)
    op.execute(RECORD)
    for function in ("api.records(integer, text)", "api.record(text, text, text)"):
        op.execute(f"revoke execute on function {function} from public")
        op.execute(f"grant execute on function {function} to anon, authenticated")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop function api.record(text, text, text)")
    op.execute("drop function api.records(integer, text)")
    op.drop_index("ix_record_record_place", table_name="record", schema="ajr")
    op.drop_table("record", schema="ajr")
