"""api for the site

The site reads the database through the Supabase Data API with the publishable
key (role anon). It sees only the `api` schema: functions that run with the
owner's rights (security definer) and return just what the pages need. The
`ajr` tables stay closed.

Revision ID: ead6ff26f31b
Revises: e762b902af13
Create Date: 2026-10-28 14:26:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ead6ff26f31b"
down_revision: Union[str, Sequence[str], None] = "e762b902af13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The table of a weight category on a day: the row of each athlete valid on that
# day, RD grown for the days since the contest, hidden after a year without
# contests (see ajr/rating/ranking.py, which does the same in Python).
BOARD_AT = """
create function ajr.board_at(p_weight text, p_day date)
returns table (
    athlete_id integer,
    rating double precision,
    rd double precision,
    score double precision,
    last_contest date,
    place bigint
)
language sql stable
set search_path = ''
as $$
    select rc.athlete_id,
           rc.rating_after,
           rd.value,
           rc.rating_after - s.rd_factor * rd.value,
           rc.fought_on,
           rank() over (order by rc.rating_after - s.rd_factor * rd.value desc)
    from ajr.rating_change rc
    cross join ajr.rating_settings s
    cross join lateral (
        select least(s.max_rd, sqrt(rc.rd_after ^ 2 + s.rd_growth ^ 2 * (p_day - rc.fought_on)))
            as value
    ) rd
    where rc.weight = p_weight
      and rc.fought_on <= p_day
      and rc.next_fought_on > p_day
      and (s.hide_after_days is null or p_day - rc.fought_on <= s.hide_after_days)
$$
"""

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
    score_change_6m integer
)
language sql stable security definer
set search_path = ''
as $$
    -- Changes are null when the athlete was not in the table back then (new or returning).
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
           round(now.score - d6m.score)::integer
    from ajr.board_at(leaderboard.weight, leaderboard.day) now
    join ajr.athlete a on a.id = now.athlete_id
    left join ajr.country co on co.id = a.country_id
    left join ajr.board_at(leaderboard.weight, leaderboard.day - 90) d90
        on d90.athlete_id = now.athlete_id
    left join ajr.board_at(leaderboard.weight, (leaderboard.day - interval '6 months')::date) d6m
        on d6m.athlete_id = now.athlete_id
    order by now.place, a.family_name
$$
"""

ATHLETE = """
create function api.athlete(athlete_id integer)
returns table (
    id integer,
    family_name text,
    given_name text,
    gender text,
    birth_year integer,
    country text,
    country_name text,
    weight text,
    rating integer,
    rd integer,
    score integer,
    place bigint,
    last_contest date,
    contests bigint
)
language sql stable security definer
set search_path = ''
as $$
    -- place is null when the athlete is hidden (a year without contests) or never rated.
    select a.id,
           a.family_name::text,
           a.given_name::text,
           a.gender::text,
           a.dob_year,
           co.ioc::text,
           co.name::text,
           latest.weight::text,
           round(latest.rating_after)::integer,
           round(rd.value)::integer,
           round(latest.rating_after - s.rd_factor * rd.value)::integer,
           board.place,
           latest.fought_on,
           (select count(*) from ajr.rating_change rc where rc.athlete_id = a.id)
    from ajr.athlete a
    cross join ajr.rating_settings s
    left join ajr.country co on co.id = a.country_id
    left join ajr.rating_change latest
        on latest.athlete_id = a.id and latest.next_fought_on = date '9999-12-31'
    left join lateral (
        select least(s.max_rd, sqrt(latest.rd_after ^ 2
                                    + s.rd_growth ^ 2 * (current_date - latest.fought_on)))
            as value
    ) rd on true
    left join lateral ajr.board_at(latest.weight, current_date) board
        on board.athlete_id = a.id
    where a.id = athlete.athlete_id
$$
"""

ATHLETE_HISTORY = """
create function api.athlete_history(athlete_id integer)
returns table (
    contest_id integer,
    fought_on date,
    competition_id integer,
    competition text,
    round text,
    weight text,
    opponent_id integer,
    opponent_family_name text,
    opponent_given_name text,
    opponent_country text,
    won boolean,
    win_probability double precision,
    rating_before integer,
    rating_after integer,
    rd_after integer
)
language sql stable security definer
set search_path = ''
as $$
    -- Latest first; within a day the later round (judobase counts down to the final) first.
    select rc.contest_id,
           rc.fought_on,
           cm.id,
           cm.name::text,
           ct.round_name::text,
           ct.weight::text,
           rc.opponent_id,
           o.family_name::text,
           o.given_name::text,
           co.ioc::text,
           rc.won,
           rc.win_probability,
           round(rc.rating_before)::integer,
           round(rc.rating_after)::integer,
           round(rc.rd_after)::integer
    from ajr.rating_change rc
    join ajr.contest ct on ct.id = rc.contest_id
    join ajr.competition cm on cm.id = ct.competition_id
    join ajr.athlete o on o.id = rc.opponent_id
    left join ajr.country co on co.id = o.country_id
    where rc.athlete_id = athlete_history.athlete_id
    order by rc.fought_on desc, ct.round nulls last, ct.fight_no desc
$$
"""

LAST_UPDATE = """
create function api.last_update()
returns timestamp with time zone
language sql stable security definer
set search_path = ''
as $$
    select max(finished_at) from ajr.job_run where type = 'rating' and status = 'success'
$$
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("create schema api")
    for statement in (BOARD_AT, LEADERBOARD, ATHLETE, ATHLETE_HISTORY, LAST_UPDATE):
        op.execute(statement)
    # Only the site's roles may call the api; functions are executable by anyone by default.
    op.execute("revoke execute on all functions in schema api from public")
    op.execute("revoke execute on function ajr.board_at(text, date) from public")
    op.execute("grant usage on schema api to anon, authenticated")
    op.execute("grant execute on all functions in schema api to anon, authenticated")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop schema api cascade")
    op.execute("drop function ajr.board_at(text, date)")
