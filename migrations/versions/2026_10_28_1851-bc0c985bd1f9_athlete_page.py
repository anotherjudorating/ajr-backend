"""athlete page

What the athlete page needs, and fixes found while building the rankings page:

- ajr.score_at: an athlete's rating, RD and score on a day, in whatever weight.
  The rating is one for all weights, so a change over 90 days or 6 months is
  counted from it, also for athletes who were not in this weight's table then
  (they fought in another weight, or were hidden for a year without contests).
  It stays null only for athletes with no rating back then.
- api.leaderboard: those changes, and `entry` for athletes not in the table
  90 days ago: 'new' (first time in this weight) or 'returning'.
- api.athlete: the weights the athlete fought in, the peak score (with its day
  and the place on that day) and the changes over 90 days and 6 months.
- api.athlete_history: only_weight (the contests of one weight category), the
  score before and after, the opponent's score and the athlete's result at the
  competition (gold, silver, bronze, 5th, 7th or the round they lost in).

Revision ID: bc0c985bd1f9
Revises: fbd2c1b2e12c
Create Date: 2026-10-28 18:51:00

"""

import importlib.util
from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bc0c985bd1f9"
down_revision: Union[str, Sequence[str], None] = "fbd2c1b2e12c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The row valid on the day (the athlete's latest contest up to it), RD grown since.
SCORE_AT = """
create function ajr.score_at(p_athlete_id integer, p_day date)
returns table (
    rating double precision,
    rd double precision,
    score double precision,
    weight text
)
language sql stable
set search_path = ''
as $$
    select rc.rating_after,
           rd.value,
           rc.rating_after - s.rd_factor * rd.value,
           rc.weight::text
    from ajr.rating_change rc
    cross join ajr.rating_settings s
    cross join lateral (
        select least(s.max_rd, sqrt(rc.rd_after ^ 2 + s.rd_growth ^ 2 * (p_day - rc.fought_on)))
            as value
    ) rd
    where rc.athlete_id = p_athlete_id
      and rc.fought_on <= p_day
      and rc.next_fought_on > p_day
$$
"""

# How an athlete ended a competition, from their last decided contest in it:
# gold/silver (the final), bronze/5th (a bronze contest), 7th (lost a repechage),
# the round they lost in, or null while still in (or in pools).
RESULT_LABEL = """
create function ajr.result_label(round_name text, won boolean)
returns text
language sql immutable
as $$
    select case
               when round_name = 'Final' then case when won then 'gold' else 'silver' end
               when round_name = 'Bronze' then case when won then 'bronze' else '5th' end
               when won then null
               when round_name = 'Repechage' then '7th'
               else round_name
           end
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
    -- Place changes are null when the athlete was not in the table back then;
    -- score changes only when the athlete had no rating at all.
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
           round(now.score - s90.score)::integer,
           round(now.score - s6m.score)::integer,
           w.place,
           (d6m.place - now.place)::integer,
           a.dob_year,
           array[round(d150.score), round(d120.score), round(d90.score),
                 round(d60.score), round(d30.score), round(now.score)]::integer[],
           cm.id,
           cm.name::text,
           cm.rank_name::text,
           cm.city::text,
           case
               when d90.athlete_id is not null then null
               when exists (
                   select from ajr.rating_change earlier
                   where earlier.athlete_id = now.athlete_id
                     and earlier.weight = leaderboard.weight
                     and earlier.fought_on <= leaderboard.day - 90
               ) then 'returning'
               else 'new'
           end
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
    left join lateral ajr.score_at(now.athlete_id, leaderboard.day - 90) s90 on true
    left join lateral ajr.score_at(now.athlete_id, (leaderboard.day - interval '6 months')::date) s6m
        on true
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
    contests bigint,
    wrl_place integer,
    weights text[],
    peak_score integer,
    peak_on date,
    peak_place bigint,
    score_change_90d integer,
    score_change_6m integer,
    places_up_90d integer,
    places_up_6m integer
)
language sql stable security definer
set search_path = ''
as $$
    -- place is null when the athlete is hidden (a year without contests) or never rated.
    -- weights: the categories fought in, the latest first.
    -- The peak is the best score at the end of a day of contests; peak_place is the
    -- place in that day's table.
    select a.id,
           a.family_name::text,
           a.given_name::text,
           a.gender::text,
           a.dob_year,
           co.ioc::text,
           co.name::text,
           latest.weight::text,
           round(latest.rating_after)::integer,
           round(now.rd)::integer,
           round(now.score)::integer,
           board.place,
           latest.fought_on,
           (select count(*) from ajr.rating_change rc where rc.athlete_id = a.id),
           w.place,
           array(
               select rc.weight::text
               from ajr.rating_change rc
               where rc.athlete_id = a.id and rc.weight is not null
               group by rc.weight
               order by max(rc.fought_on) desc
           ),
           round(peak.score)::integer,
           peak.fought_on,
           (select b.place
            from ajr.board_at(peak.weight, peak.fought_on) b
            where b.athlete_id = a.id),
           round(now.score - s90.score)::integer,
           round(now.score - s6m.score)::integer,
           (d90.place - board.place)::integer,
           (d6m.place - board.place)::integer
    from ajr.athlete a
    cross join ajr.rating_settings s
    left join ajr.country co on co.id = a.country_id
    left join ajr.rating_change latest
        on latest.athlete_id = a.id and latest.next_fought_on = date '9999-12-31'
    left join lateral ajr.score_at(a.id, current_date) now on true
    left join lateral ajr.score_at(a.id, current_date - 90) s90 on true
    left join lateral ajr.score_at(a.id, (current_date - interval '6 months')::date) s6m on true
    left join lateral (
        select rc.fought_on, rc.weight, rc.rating_after - s.rd_factor * rc.rd_after as score
        from ajr.rating_change rc
        where rc.athlete_id = a.id
          and rc.next_fought_on > rc.fought_on  -- the last contest of its day
          and rc.weight is not null
        order by score desc, rc.fought_on
        limit 1
    ) peak on true
    left join lateral ajr.board_at(latest.weight, current_date) board
        on board.athlete_id = a.id
    left join lateral ajr.board_at(latest.weight, current_date - 90) d90
        on d90.athlete_id = a.id
    left join lateral ajr.board_at(latest.weight, (current_date - interval '6 months')::date) d6m
        on d6m.athlete_id = a.id
    left join ajr.wrl_ranking w on w.athlete_id = a.id and w.weight = latest.weight
    where a.id = athlete.athlete_id
$$
"""

ATHLETE_HISTORY = """
create function api.athlete_history(athlete_id integer, only_weight text default null)
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
    rd_after integer,
    rd_before integer,
    score_before integer,
    score_after integer,
    opponent_score integer,
    result text
)
language sql stable security definer
set search_path = ''
as $$
    -- Latest first; within a day the later round (judobase counts down to the final) first.
    -- weight is the category the contest counts for (an open-weight contest keeps
    -- the athlete's), and only_weight picks the contests of one category.
    -- result: how the athlete ended the competition (ajr.result_label).
    select rc.contest_id,
           rc.fought_on,
           cm.id,
           cm.name::text,
           ct.round_name::text,
           rc.weight::text,
           rc.opponent_id,
           o.family_name::text,
           o.given_name::text,
           co.ioc::text,
           rc.won,
           rc.win_probability,
           round(rc.rating_before)::integer,
           round(rc.rating_after)::integer,
           round(rc.rd_after)::integer,
           round(rc.rd_before)::integer,
           round(rc.rating_before - s.rd_factor * rc.rd_before)::integer,
           round(rc.rating_after - s.rd_factor * rc.rd_after)::integer,
           round(orc.rating_before - s.rd_factor * orc.rd_before)::integer,
           result.value
    from ajr.rating_change rc
    cross join ajr.rating_settings s
    join ajr.contest ct on ct.id = rc.contest_id
    join ajr.competition cm on cm.id = ct.competition_id
    join ajr.athlete o on o.id = rc.opponent_id
    left join ajr.country co on co.id = o.country_id
    left join ajr.rating_change orc
        on orc.contest_id = rc.contest_id and orc.athlete_id = rc.opponent_id
    left join lateral (
        select ajr.result_label(last.round_name, last.winner_id = rc.athlete_id) as value
        from ajr.contest last
        where last.competition_id = ct.competition_id
          and last.weight = ct.weight
          and rc.athlete_id in (last.blue_id, last.white_id)
          and last.winner_id is not null
          -- in some old competitions every contest is a "Final": no result there
          and (select count(*)
               from ajr.contest final
               where final.competition_id = ct.competition_id
                 and final.weight = ct.weight
                 and final.round_name = 'Final') = 1
        order by last.round nulls last, last.fight_no desc
        limit 1
    ) result on true
    where rc.athlete_id = athlete_history.athlete_id
      and (athlete_history.only_weight is null or rc.weight = athlete_history.only_weight)
    order by rc.fought_on desc, ct.round nulls last, ct.fight_no desc
$$
"""


def load_migration(name: str):
    """An earlier migration's module, to rebuild its functions on downgrade."""
    path = next(Path(__file__).parent.glob(f"*{name}.py"))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def previous_functions() -> list[str]:
    """api.leaderboard, api.athlete and api.athlete_history as they were before."""
    return [
        load_migration("fbd2c1b2e12c_leaderboard_details").LEADERBOARD,
        load_migration("9542ffd9954e_world_ranking_list").athlete(with_wrl=True),
        load_migration("ead6ff26f31b_api_for_the_site").ATHLETE_HISTORY,
    ]


def grant_api() -> None:
    op.execute("revoke execute on all functions in schema api from public")
    op.execute("grant execute on all functions in schema api to anon, authenticated")


def drop_api_functions() -> None:
    """Their result columns change, so they are dropped and created again."""
    op.execute("drop function api.leaderboard(text, date)")
    op.execute("drop function api.athlete(integer)")


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(SCORE_AT)
    op.execute(RESULT_LABEL)
    op.execute("revoke execute on function ajr.score_at(integer, date) from public")
    op.execute("revoke execute on function ajr.result_label(text, boolean) from public")
    drop_api_functions()
    op.execute("drop function api.athlete_history(integer)")
    for function in (LEADERBOARD, ATHLETE, ATHLETE_HISTORY):
        op.execute(function)
    grant_api()


def downgrade() -> None:
    """Downgrade schema."""
    drop_api_functions()
    op.execute("drop function api.athlete_history(integer, text)")
    for function in previous_functions():
        op.execute(function)
    grant_api()
    op.execute("drop function ajr.result_label(text, boolean)")
    op.execute("drop function ajr.score_at(integer, date)")
