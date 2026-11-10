"""upsets of strong athletes

api.recent_upsets (the home page's "Upsets of the month") showed the least likely
wins of the month whoever lost: often a win over an athlete outside the top 200 at an
Open, which says little. Now only wins over an athlete in the top 30 of their table
(`loser_top`). A new argument changes the function's signature: the old one dropped.

Revision ID: e9c5a1b3d420
Revises: d8b4f0a2c319
Create Date: 2026-11-23 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e9c5a1b3d420"
down_revision: Union[str, Sequence[str], None] = "d8b4f0a2c319"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = "api.recent_upsets(integer, integer)"
NEW = "api.recent_upsets(integer, integer, integer)"

RECENT_UPSETS = """
create function api.recent_upsets(
    days integer default 30, top integer default 4, loser_top integer default 30
)
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
    -- of the competitions that started in the window, over an athlete in the top
    -- `loser_top` of their table (today's place: the window is a month, the place
    -- barely moved since; not a newcomer beating an unknown)
    with upsets as materialized (
        select l.*
        from ajr.competition cm
        join ajr.contest_list l on l.competition_id = cm.id  -- ix_contest_list_competition
        join ajr.athlete_summary sm
          on sm.athlete_id = case when l.winner_id = l.white_id then l.blue_id else l.white_id end
        where cm.date_from between current_date - recent_upsets.days and current_date
          and l.winner_chance <= 0.35
          and sm.place <= recent_upsets.loser_top
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


def grant(signature: str) -> None:
    op.execute(f"revoke execute on function {signature} from public")
    op.execute(f"grant execute on function {signature} to anon, authenticated")


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(f"drop function {OLD}")
    op.execute(RECENT_UPSETS)
    grant(NEW)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"drop function {NEW}")
    op.execute(load_migration("c5e2a8d1f379_upsets_by_competition").RECENT_UPSETS)
    grant(OLD)
