"""home fixes

- api.recent_upsets ran past the Data API's limit: the planner did not know how
  few tournaments started in the last days and read every contest. It now takes
  those tournaments and their contests first (materialized), then the ratings by
  key.
- api.biggest_movers counted climbs from the bottom of a table (+400 places, +1300
  points: an athlete the rating barely knew). A mover now was in the top 50 of
  their weight 90 days ago too.

Revision ID: 0f2b8c47d1a3
Revises: e7a9d3c15f62
Create Date: 2026-11-04 14:00:00

"""

import importlib.util
from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0f2b8c47d1a3"
down_revision: Union[str, Sequence[str], None] = "e7a9d3c15f62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WAS_WITHIN = 50  # the place 90 days ago a mover must have been at or above

RECENT_UPSETS = """
create or replace function api.recent_upsets(days integer default 30, top integer default 4)
returns table (
    contest_id integer,
    competition_id integer,
    competition text,
    weight text,
    round text,
    fought_on date,
    winner_id integer,
    winner_family_name text,
    winner_given_name text,
    winner_country text,
    winner_chance double precision,
    winner_score integer,
    loser_id integer,
    loser_family_name text,
    loser_given_name text,
    loser_country text,
    loser_score integer
)
language sql stable security definer
set search_path = ''
as $$
    -- score: before the contest
    with recent as materialized (
        select cm.id, cm.name
        from ajr.competition cm
        where cm.date_from between current_date - recent_upsets.days and current_date
    ),
    fights as materialized (
        select ct.id, ct.competition_id, r.name, ct.weight, ct.round_name, ct.winner_id
        from recent r
        join ajr.contest ct on ct.competition_id = r.id
        where not coalesce(ct.bye, false) and ct.duration is distinct from '00:00:00'
    )
    select f.id, f.competition_id, f.name::text, f.weight::text, f.round_name::text, w.fought_on,
           w.athlete_id, wa.family_name::text, wa.given_name::text, wc.ioc::text,
           w.win_probability, round(w.rating_before - s.rd_factor * w.rd_before)::integer,
           l.athlete_id, la.family_name::text, la.given_name::text, lc.ioc::text,
           round(l.rating_before - s.rd_factor * l.rd_before)::integer
    from fights f
    join ajr.rating_change w on w.contest_id = f.id and w.athlete_id = f.winner_id
    join ajr.rating_change l on l.contest_id = f.id and l.athlete_id <> f.winner_id
    cross join ajr.rating_settings s
    join ajr.athlete wa on wa.id = w.athlete_id
    left join ajr.country wc on wc.id = wa.country_id
    join ajr.athlete la on la.id = l.athlete_id
    left join ajr.country lc on lc.id = la.country_id
    where w.win_probability <= 0.35
    order by w.win_probability, f.id
    limit recent_upsets.top
$$
"""


def load_migration(name: str):
    """An earlier migration's module, to reuse its SQL."""
    path = next(Path(__file__).parent.glob(f"*{name}.py"))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def previous(name: str) -> str:
    sql = getattr(load_migration("e7a9d3c15f62_home"), name)
    return sql.replace("create function", "create or replace function")


def biggest_movers() -> str:
    sql = previous("BIGGEST_MOVERS").replace(
        "      and l.score_change_90d <> 0\n",
        "      and l.score_change_90d <> 0\n"
        f"      and l.place + l.places_up_90d <= {WAS_WITHIN} -- the place 90 days ago\n",
    )
    assert f"<= {WAS_WITHIN}" in sql
    return sql


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(RECENT_UPSETS)
    op.execute(biggest_movers())


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(previous("RECENT_UPSETS"))
    op.execute(previous("BIGGEST_MOVERS"))
