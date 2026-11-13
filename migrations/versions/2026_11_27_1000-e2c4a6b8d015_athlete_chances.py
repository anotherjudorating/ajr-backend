"""athlete chances: an athlete's tournaments still open, with their medal chances

api.athlete_chances(athlete_id): the tournaments with a published draw (ajr.medal_chance)
in which the athlete is in and their outcome still open, for the athlete's page: not
fought yet, a medal still open, or a medal sure and its colour open (a finalist). Out,
or with a medal and its colour decided: gone (their result is in the history).

Revision ID: e2c4a6b8d015
Revises: d7a3c5e9f104
Create Date: 2026-11-27 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2c4a6b8d015"
down_revision: Union[str, Sequence[str], None] = "d7a3c5e9f104"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ATHLETE_CHANCES = """
create function api.athlete_chances(athlete_id integer)
returns table (
    competition_id integer, competition text, rank_name text, city text, country text,
    date_from date, date_to date, weight text, gold double precision, medal double precision
)
language sql stable security definer
set search_path = ''
as $$
    select mc.competition_id, cm.name::text, cm.rank_name::text, cm.city::text, co.ioc::text,
           cm.date_from, cm.date_to, mc.weight, mc.gold, mc.medal
    from ajr.medal_chance mc
    join ajr.competition cm on cm.id = mc.competition_id
    left join ajr.country co on co.id = cm.country_id
    where mc.athlete_id = athlete_chances.athlete_id
      and (
          -- not fought yet: no decided contest, in the contests or the draw (a bye is none)
          (not exists (select from ajr.contest ct
                       where ct.competition_id = mc.competition_id and ct.weight = mc.weight
                         and ct.winner_id is not null and ct.white_id is not null
                         and ct.blue_id is not null
                         and mc.athlete_id in (ct.white_id, ct.blue_id))
           and not exists (select from ajr.draw d
                           where d.competition_id = mc.competition_id and d.weight = mc.weight
                             and d.winner_id is not null and d.white_id is not null
                             and d.blue_id is not null
                             and mc.athlete_id in (d.white_id, d.blue_id)))
          or (mc.medal > 0 and mc.medal < 0.9999)  -- a medal still open
          or (mc.medal >= 0.9999 and mc.gold > 0 and mc.gold < 0.9999))  -- its colour open
    order by cm.date_from, mc.weight
$$
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(ATHLETE_CHANCES)
    op.execute("revoke execute on function api.athlete_chances(integer) from public")
    op.execute("grant execute on function api.athlete_chances(integer) to anon, authenticated")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop function api.athlete_chances(integer)")
