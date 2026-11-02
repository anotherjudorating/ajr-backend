"""medal chances

ajr.medal_chance: at tournaments with a published draw (from two weeks ahead to
two days after), every athlete's chance of gold and of any medal, from playing
the bracket with today's ratings; built by the rating job (ajr/rating/chances.py).
api.competition_chances(competition_id) reads them, the likeliest medallists of
every weight first.

Revision ID: 3a6d9e21b7c4
Revises: 0f2b8c47d1a3
Create Date: 2026-11-05 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3a6d9e21b7c4"
down_revision: Union[str, Sequence[str], None] = "0f2b8c47d1a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Men, then women, lightest first.
WEIGHT_ORDER = (
    "coalesce(array_position(array['-60', '-66', '-73', '-81', '-90', '-100', '+100',"
    " '-48', '-52', '-57', '-63', '-70', '-78', '+78'], {}), 100)"
)

TABLE = """
create table ajr.medal_chance (
    competition_id integer not null references ajr.competition (id),
    weight text not null,
    athlete_id integer not null references ajr.athlete (id),
    gold double precision not null,
    medal double precision not null,
    primary key (competition_id, weight, athlete_id)
)
"""

COMPETITION_CHANCES = f"""
create function api.competition_chances(competition_id integer)
returns table (
    weight text,
    athlete_id integer,
    family_name text,
    given_name text,
    country text,
    gold double precision,
    medal double precision
)
language sql stable security definer
set search_path = ''
as $$
    select mc.weight, mc.athlete_id, a.family_name::text, a.given_name::text, co.ioc::text,
           mc.gold, mc.medal
    from ajr.medal_chance mc
    join ajr.athlete a on a.id = mc.athlete_id
    left join ajr.country co on co.id = a.country_id
    where mc.competition_id = competition_chances.competition_id
    order by {WEIGHT_ORDER.format("mc.weight")}, mc.weight, mc.medal desc, mc.gold desc
$$
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(TABLE)
    op.execute(COMPETITION_CHANCES)
    op.execute("revoke execute on function api.competition_chances(integer) from public")
    op.execute("grant execute on function api.competition_chances(integer) to anon, authenticated")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop function api.competition_chances(integer)")
    op.execute("drop table ajr.medal_chance")
