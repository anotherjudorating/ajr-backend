"""leaderboard snapshot

A weight's table with its place and score changes, trend, IJF place and latest
competition costs the database a few hundred milliseconds of CPU; the site asks
for several at once (a build, the cache refreshing, prefetched links) and the
small Supabase instance then runs over the Data API's 3-second limit for anon.

So today's tables are built ahead:
- ajr.leaderboard_full(weight, day): the whole table, as api.leaderboard was.
- ajr.leaderboard_snapshot: today's full tables of every weight, rebuilt by the
  rating job after every run (ajr/rating/snapshot.py).
- api.leaderboard(weight, day): today's from the snapshot; any other day a plain
  table (place, name, nation, rating, year of birth), which is one ajr.board_at.

Revision ID: a780ebc52e26
Revises: 0e0fe6ec9e08
Create Date: 2026-11-01 14:00:00

"""

import importlib.util
from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a780ebc52e26"
down_revision: Union[str, Sequence[str], None] = "0e0fe6ec9e08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SNAPSHOT = """
create table ajr.leaderboard_snapshot (
    weight text not null,
    day date not null,
    place bigint not null,
    athlete_id integer not null references ajr.athlete (id),
    family_name text,
    given_name text,
    country text,
    rating integer,
    rd integer,
    score integer,
    last_contest date,
    places_up_90d integer,
    score_change_90d integer,
    score_change_6m integer,
    wrl_place integer,
    places_up_6m integer,
    birth_year integer,
    trend integer[],
    last_competition_id integer,
    last_competition_name text,
    last_competition_rank text,
    last_competition_city text,
    entry text,
    primary key (weight, athlete_id)
)
"""

LEADERBOARD = """
create or replace function api.leaderboard(weight text, day date default current_date)
returns table (
    place bigint,
    athlete_id integer,
    family_name text,
    given_name text,
    country text,
    rating integer,
    rd integer,
    score integer,
    last_contest date,
    places_up_90d integer,
    score_change_90d integer,
    score_change_6m integer,
    wrl_place integer,
    places_up_6m integer,
    birth_year integer,
    trend integer[],
    last_competition_id integer,
    last_competition_name text,
    last_competition_rank text,
    last_competition_city text,
    entry text
)
language sql stable security definer
set search_path = ''
as $$
    -- today's table, built by the rating job
    select s.place, s.athlete_id, s.family_name, s.given_name, s.country,
           s.rating, s.rd, s.score, s.last_contest,
           s.places_up_90d, s.score_change_90d, s.score_change_6m, s.wrl_place,
           s.places_up_6m, s.birth_year, s.trend,
           s.last_competition_id, s.last_competition_name, s.last_competition_rank,
           s.last_competition_city, s.entry
    from ajr.leaderboard_snapshot s
    where s.weight = leaderboard.weight and s.day = leaderboard.day
    union all
    -- any other day: places, names, nations, ratings and years of birth only
    select b.place, b.athlete_id, a.family_name::text, a.given_name::text, co.ioc::text,
           round(b.rating)::integer, round(b.rd)::integer, round(b.score)::integer,
           b.last_contest,
           null::integer, null::integer, null::integer, null::integer,
           null::integer, a.dob_year, null::integer[],
           null::integer, null::text, null::text,
           null::text, null::text
    from ajr.board_at(leaderboard.weight, leaderboard.day) b
    join ajr.athlete a on a.id = b.athlete_id
    left join ajr.country co on co.id = a.country_id
    where not exists (
        select from ajr.leaderboard_snapshot s
        where s.weight = leaderboard.weight and s.day = leaderboard.day
    )
    order by 1, 3
$$
"""


def load_migration(name: str):
    """An earlier migration's module, to reuse its SQL."""
    path = next(Path(__file__).parent.glob(f"*{name}.py"))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def previous_leaderboard() -> str:
    """api.leaderboard as the "athlete page" migration created it."""
    return load_migration("bc0c985bd1f9_athlete_page").LEADERBOARD


def leaderboard_full() -> str:
    """The previous api.leaderboard as ajr.leaderboard_full: same query, now run by
    the rating job (as the owner), not by the site."""
    return (
        previous_leaderboard()
        .replace(
            "create function api.leaderboard(weight text, day date default current_date)",
            "create function ajr.leaderboard_full(weight text, day date)",
        )
        .replace("language sql stable security definer", "language sql stable")
        .replace("leaderboard.weight", "leaderboard_full.weight")
        .replace("leaderboard.day", "leaderboard_full.day")
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(leaderboard_full())
    op.execute("revoke execute on function ajr.leaderboard_full(text, date) from public")
    op.execute(SNAPSHOT)
    op.execute(LEADERBOARD)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop function api.leaderboard(text, date)")
    op.execute(previous_leaderboard())
    op.execute("revoke execute on function api.leaderboard(text, date) from public")
    op.execute("grant execute on function api.leaderboard(text, date) to anon, authenticated")
    op.execute("drop table ajr.leaderboard_snapshot")
    op.execute("drop function ajr.leaderboard_full(text, date)")
