"""leaderboard details

More columns in api.leaderboard for the rankings page: place change over 6
months, year of birth, a trend of the score over half a year (for a sparkline)
and the competition of the athlete's latest contest. New columns go at the end,
so the existing ones keep their places.

Revision ID: fbd2c1b2e12c
Revises: 9542ffd9954e
Create Date: 2026-10-28 17:13:00

"""

import importlib.util
from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fbd2c1b2e12c"
down_revision: Union[str, Sequence[str], None] = "9542ffd9954e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEADERBOARD = """
create function api.leaderboard(weight text, day date default current_date)
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
    last_competition_city text
)
language sql stable security definer
set search_path = ''
as $$
    -- Changes are null when the athlete was not in the table back then (new or returning).
    -- trend: the score 150, 120, 90, 60 and 30 days ago and on the day (null where not listed).
    select now.place,
           now.athlete_id,
           a.family_name::text,
           a.given_name::text,
           co.ioc::text,
           round(now.rating)::integer,
           round(now.rd)::integer,
           round(now.score)::integer,
           now.last_contest,
           (d90.place - now.place)::integer,
           round(now.score - d90.score)::integer,
           round(now.score - d6m.score)::integer,
           w.place,
           (d6m.place - now.place)::integer,
           a.dob_year,
           array[round(d150.score), round(d120.score), round(d90.score),
                 round(d60.score), round(d30.score), round(now.score)]::integer[],
           cm.id,
           cm.name::text,
           cm.rank_name::text,
           cm.city::text
    from ajr.board_at(leaderboard.weight, leaderboard.day) now
    join ajr.athlete a on a.id = now.athlete_id
    left join ajr.country co on co.id = a.country_id
    left join ajr.board_at(leaderboard.weight, leaderboard.day - 30) d30
        on d30.athlete_id = now.athlete_id
    left join ajr.board_at(leaderboard.weight, leaderboard.day - 60) d60
        on d60.athlete_id = now.athlete_id
    left join ajr.board_at(leaderboard.weight, leaderboard.day - 90) d90
        on d90.athlete_id = now.athlete_id
    left join ajr.board_at(leaderboard.weight, leaderboard.day - 120) d120
        on d120.athlete_id = now.athlete_id
    left join ajr.board_at(leaderboard.weight, leaderboard.day - 150) d150
        on d150.athlete_id = now.athlete_id
    left join ajr.board_at(leaderboard.weight, (leaderboard.day - interval '6 months')::date) d6m
        on d6m.athlete_id = now.athlete_id
    -- The WRL is the current one: no place to show for a table of another day.
    left join ajr.wrl_ranking w
        on w.athlete_id = now.athlete_id
       and w.weight = leaderboard.weight
       and leaderboard.day = current_date
    -- The row of the athlete's latest contest up to the day, and its competition.
    left join ajr.rating_change latest
        on latest.athlete_id = now.athlete_id
       and latest.weight = leaderboard.weight
       and latest.fought_on <= leaderboard.day
       and latest.next_fought_on > leaderboard.day
    left join ajr.contest ct on ct.id = latest.contest_id
    left join ajr.competition cm on cm.id = ct.competition_id
    order by now.place, a.family_name
$$
"""


def grant() -> None:
    op.execute("revoke execute on function api.leaderboard(text, date) from public")
    op.execute("grant execute on function api.leaderboard(text, date) to anon, authenticated")


def upgrade() -> None:
    """Upgrade schema."""
    # The result columns change, so the function is dropped and created again.
    op.execute("drop function api.leaderboard(text, date)")
    op.execute(LEADERBOARD)
    grant()


def previous_leaderboard() -> str:
    """api.leaderboard as the "world ranking list" migration created it."""
    path = next(Path(__file__).parent.glob("*9542ffd9954e_world_ranking_list.py"))
    spec = importlib.util.spec_from_file_location("world_ranking_list", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.leaderboard(with_wrl=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop function api.leaderboard(text, date)")
    op.execute(previous_leaderboard())
    grant()
