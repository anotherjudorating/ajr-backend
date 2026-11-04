"""upsets fast

api.recent_upsets (the home page) read about 85 thousand pages a call (715 thousand
for a year): the planner joined each recent winner's whole rating history and
filtered by contest afterwards. It now picks the upsets from ajr.contest_list, the
list of real fights the rating job keeps (both athletes, their names, nations and
chances), within the year(s) the window covers, and reads the rating rows only of
the few it returns, by their primary key, for the scores before the contest. Same
arguments, same rows.

Revision ID: c3e7a1f9d204
Revises: b7e2d94f0a31
Create Date: 2026-11-09 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3e7a1f9d204"
down_revision: Union[str, Sequence[str], None] = "b7e2d94f0a31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

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
    -- of the competitions that started in the window
    with upsets as materialized (
        select l.*
        from ajr.competition cm
        join ajr.contest_list l on l.competition_id = cm.id
        where cm.date_from between current_date - recent_upsets.days and current_date
          and l.year between extract(year from current_date - recent_upsets.days)::integer
                         and extract(year from current_date)::integer
          and l.winner_chance <= 0.35
        order by l.winner_chance, l.contest_id
        limit recent_upsets.top
    )
    select u.contest_id, u.competition_id, u.competition, u.weight, u.round, u.day,
           u.winner_id,
           case when white then u.white_family_name else u.blue_family_name end,
           case when white then u.white_given_name else u.blue_given_name end,
           case when white then u.white_country else u.blue_country end,
           u.winner_chance,
           round(w.rating_before - s.rd_factor * w.rd_before)::integer,
           case when white then u.blue_id else u.white_id end,
           case when white then u.blue_family_name else u.white_family_name end,
           case when white then u.blue_given_name else u.white_given_name end,
           case when white then u.blue_country else u.white_country end,
           round(l.rating_before - s.rd_factor * l.rd_before)::integer
    from upsets u
    cross join lateral (select u.winner_id = u.white_id as white) side
    cross join ajr.rating_settings s
    join ajr.rating_change w on w.contest_id = u.contest_id and w.athlete_id = u.winner_id
    join ajr.rating_change l on l.contest_id = u.contest_id
                            and l.athlete_id = case when white then u.blue_id else u.white_id end
    order by u.winner_chance, u.contest_id
$$
"""


def load_migration(name: str):
    """An earlier migration's module, to restore its SQL."""
    import importlib.util
    from pathlib import Path

    path = next(Path(__file__).parent.glob(f"*{name}.py"))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(RECENT_UPSETS)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(load_migration("0f2b8c47d1a3_home_fixes").RECENT_UPSETS)
