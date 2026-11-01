"""popular matchups

The head-to-head page lists popular matchups: the pairs people open most, once
there are enough openings to tell (100 in all); until then a fixed list the site
passes.

- ajr.matchup_views: how many times each pair was opened (a < b).
- api.count_matchup(a, b): the site calls it when it shows a pair's comparison.
  Anyone can call it: the counts only order the list, they are never shown.
- api.popular_matchups(fallback, top): the `top` most opened pairs, or the pairs
  of `fallback` ([a1, b1, a2, b2, ...]) while there are fewer than 100 openings;
  each with both athletes, their scores today, the first one's wins and losses
  against the second and their last meeting.

Revision ID: 06a683118231
Revises: a780ebc52e26
Create Date: 2026-11-01 22:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "06a683118231"
down_revision: Union[str, Sequence[str], None] = "a780ebc52e26"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MATCHUP_VIEWS = """
create table ajr.matchup_views (
    a integer not null references ajr.athlete (id),
    b integer not null references ajr.athlete (id),
    views integer not null default 0,
    primary key (a, b),
    check (a < b)
)
"""

COUNT_MATCHUP = """
create function api.count_matchup(a integer, b integer)
returns void
language sql volatile security definer
set search_path = ''
as $$
    insert into ajr.matchup_views (a, b, views)
    select least(count_matchup.a, count_matchup.b), greatest(count_matchup.a, count_matchup.b), 1
    where count_matchup.a <> count_matchup.b
      and exists (select from ajr.athlete where id = count_matchup.a)
      and exists (select from ajr.athlete where id = count_matchup.b)
    on conflict (a, b) do update set views = ajr.matchup_views.views + 1
$$
"""

POPULAR_MATCHUPS = """
create function api.popular_matchups(fallback integer[], top integer default 5)
returns table (
    a integer,
    a_family_name text,
    a_given_name text,
    a_country text,
    a_score integer,
    b integer,
    b_family_name text,
    b_given_name text,
    b_country text,
    b_score integer,
    weight text,
    wins integer,
    losses integer,
    last_meeting date
)
language sql stable security definer
set search_path = ''
as $$
    with enough as (
        select coalesce(sum(views), 0) >= 100 as value from ajr.matchup_views
    ),
    pairs as (
        -- the most opened pairs, once there are enough openings
        (select v.a, v.b, row_number() over (order by v.views desc, v.a, v.b) as n
         from ajr.matchup_views v
         where (select value from enough)
         order by n
         limit popular_matchups.top)
        union all
        -- until then the site's list, in its order
        select popular_matchups.fallback[2 * i - 1], popular_matchups.fallback[2 * i], i
        from generate_series(1, coalesce(array_length(popular_matchups.fallback, 1), 0) / 2) i
        where not (select value from enough)
    )
    select p.a, x.family_name::text, x.given_name::text, xc.ioc::text, round(xs.score)::integer,
           p.b, y.family_name::text, y.given_name::text, yc.ioc::text, round(ys.score)::integer,
           xs.weight,
           m.wins::integer, m.losses::integer, m.last_meeting
    from pairs p
    join ajr.athlete x on x.id = p.a
    join ajr.athlete y on y.id = p.b
    left join ajr.country xc on xc.id = x.country_id
    left join ajr.country yc on yc.id = y.country_id
    left join lateral ajr.score_at(p.a, current_date) xs on true
    left join lateral ajr.score_at(p.b, current_date) ys on true
    cross join lateral (
        select count(*) filter (where rc.won) as wins,
               count(*) filter (where not rc.won) as losses,
               max(rc.fought_on) as last_meeting
        from ajr.rating_change rc
        where rc.athlete_id = p.a and rc.opponent_id = p.b
    ) m
    order by p.n
$$
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(MATCHUP_VIEWS)
    op.execute(COUNT_MATCHUP)
    op.execute(POPULAR_MATCHUPS)
    for function in ("api.count_matchup(integer, integer)", "api.popular_matchups(integer[], integer)"):
        op.execute(f"revoke execute on function {function} from public")
        op.execute(f"grant execute on function {function} to anon, authenticated")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop function api.popular_matchups(integer[], integer)")
    op.execute("drop function api.count_matchup(integer, integer)")
    op.execute("drop table ajr.matchup_views")
