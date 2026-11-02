"""home

What the home page needs, in one call each:

- api.home_leaders(top): the top of every weight's table today (the snapshot),
  with the change of place and score over 90 days.
- api.biggest_movers(top, pool): of the top `pool` of every weight who were in
  their table 90 days ago, the biggest score changes since, up or down.
- api.recent_upsets(days, top): the least likely wins of the tournaments that
  started in the last `days` days (real fights, a winner's chance of 35% or less),
  both athletes with their score before the contest.
- api.upcoming(top): World Tour tournaments (Olympic Games, World Championships,
  Masters, Grand Slams, Grand Prix) not over yet, the soonest first.

Revision ID: e7a9d3c15f62
Revises: c41f7a2e9b18
Create Date: 2026-11-04 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a9d3c15f62"
down_revision: Union[str, Sequence[str], None] = "c41f7a2e9b18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Men, then women, lightest first.
WEIGHT_ORDER = (
    "array_position(array['-60', '-66', '-73', '-81', '-90', '-100', '+100',"
    " '-48', '-52', '-57', '-63', '-70', '-78', '+78'], {})"
)

HOME_LEADERS = f"""
create function api.home_leaders(top integer default 7)
returns table (
    weight text,
    place integer,
    athlete_id integer,
    family_name text,
    given_name text,
    country text,
    score integer,
    places_up_90d integer,
    score_change_90d integer
)
language sql stable security definer
set search_path = ''
as $$
    select l.weight, l.place::integer, l.athlete_id, l.family_name, l.given_name, l.country,
           l.score, l.places_up_90d, l.score_change_90d
    from ajr.leaderboard_snapshot l
    where l.place <= home_leaders.top
    order by {WEIGHT_ORDER.format("l.weight")}, l.place
$$
"""

BIGGEST_MOVERS = """
create function api.biggest_movers(top integer default 5, pool integer default 20)
returns table (
    weight text,
    place integer,
    athlete_id integer,
    family_name text,
    given_name text,
    country text,
    score integer,
    places_up_90d integer,
    score_change_90d integer
)
language sql stable security definer
set search_path = ''
as $$
    select l.weight, l.place::integer, l.athlete_id, l.family_name, l.given_name, l.country,
           l.score, l.places_up_90d, l.score_change_90d
    from ajr.leaderboard_snapshot l
    where l.place <= biggest_movers.pool
      and l.places_up_90d is not null
      and l.score_change_90d <> 0
    order by abs(l.score_change_90d) desc, l.score desc
    limit biggest_movers.top
$$
"""

RECENT_UPSETS = """
create function api.recent_upsets(days integer default 30, top integer default 4)
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
    select ct.id, cm.id, cm.name::text, ct.weight::text, ct.round_name::text, w.fought_on,
           w.athlete_id, wa.family_name::text, wa.given_name::text, wc.ioc::text,
           w.win_probability, round(w.rating_before - s.rd_factor * w.rd_before)::integer,
           l.athlete_id, la.family_name::text, la.given_name::text, lc.ioc::text,
           round(l.rating_before - s.rd_factor * l.rd_before)::integer
    from ajr.competition cm
    join ajr.contest ct on ct.competition_id = cm.id
    join ajr.rating_change w on w.contest_id = ct.id and w.athlete_id = ct.winner_id
    join ajr.rating_change l on l.contest_id = ct.id and l.athlete_id <> ct.winner_id
    cross join ajr.rating_settings s
    join ajr.athlete wa on wa.id = w.athlete_id
    left join ajr.country wc on wc.id = wa.country_id
    join ajr.athlete la on la.id = l.athlete_id
    left join ajr.country lc on lc.id = la.country_id
    where cm.date_from between current_date - recent_upsets.days and current_date
      and not coalesce(ct.bye, false) and ct.duration is distinct from '00:00:00'
      and w.win_probability <= 0.35
    order by w.win_probability, ct.id
    limit recent_upsets.top
$$
"""

UPCOMING = """
create function api.upcoming(top integer default 3)
returns table (
    id integer,
    name text,
    rank_name text,
    city text,
    country text,
    date_from date,
    date_to date
)
language sql stable security definer
set search_path = ''
as $$
    select cm.id, cm.name::text, cm.rank_name::text, cm.city::text, co.ioc::text,
           cm.date_from, cm.date_to
    from ajr.competition cm
    left join ajr.country co on co.id = cm.country_id
    where coalesce(cm.date_to, cm.date_from) >= current_date
      and not coalesce(cm.is_teams, false)
      and cm.rank_name in ('Olympic Games', 'World Championships', 'Masters',
                           'Grand Slam', 'Grand Prix')
    order by cm.date_from, cm.id
    limit upcoming.top
$$
"""

FUNCTIONS = {
    "api.home_leaders(integer)": HOME_LEADERS,
    "api.biggest_movers(integer, integer)": BIGGEST_MOVERS,
    "api.recent_upsets(integer, integer)": RECENT_UPSETS,
    "api.upcoming(integer)": UPCOMING,
}


def upgrade() -> None:
    """Upgrade schema."""
    for signature, sql in FUNCTIONS.items():
        op.execute(sql)
        op.execute(f"revoke execute on function {signature} from public")
        op.execute(f"grant execute on function {signature} to anon, authenticated")


def downgrade() -> None:
    """Downgrade schema."""
    for signature in FUNCTIONS:
        op.execute(f"drop function {signature}")
