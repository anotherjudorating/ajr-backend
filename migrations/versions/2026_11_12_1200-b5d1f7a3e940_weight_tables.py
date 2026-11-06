"""weight tables

Which weights' tables list an athlete (ajr/rating/ranking.py): every weight in which
they fought at least min_tournaments tournaments in the listing_days before their
latest contest, and when there is none the weight of their latest contest. So an
athlete fighting in two weights stands in both tables, and a try-on of another weight
leaves them in their own. Before, a table listed whoever's latest contest was in it.

The rating job writes it with the history: rating_change.listed_here (the row's own
weight lists the athlete) and ajr.rating_listing (the other weights listing them,
with the row's days and rating, which never change but for next_fought_on, so a table
is read from the indexes alone). ajr.board_at, which every table reads (today's, a past day's,
pound for pound, nations), takes both; the covering index carries listed_here so a
table is still read from the index alone.

Pound for pound (ajr.p4p_full) takes an athlete once, from the weight of their
bigger gap: one standing in two tables could be in the top 3 of both. The nations'
tables take each weight's best, so an athlete fighting in two weights can count in
both for their nation.

Until the next rating run (a full one: the settings change) every row is listed in
its own weight only, as before.

Revision ID: b5d1f7a3e940
Revises: a3c9e5f2d817
Create Date: 2026-11-12 12:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5d1f7a3e940"
down_revision: Union[str, Sequence[str], None] = "a3c9e5f2d817"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BOARD_INDEX = (
    "create index ix_rating_change_weight_fought_on_board on ajr.rating_change "
    "(weight, fought_on) include (next_fought_on, athlete_id, rating_after, rd_after{})"
)

RATING_LISTING = """
create table ajr.rating_listing (
    contest_id integer not null,
    athlete_id integer not null,
    weight text not null,
    fought_on date not null,
    next_fought_on date not null,
    rating_after double precision not null,
    rd_after double precision not null,
    primary key (contest_id, athlete_id, weight),
    foreign key (contest_id, athlete_id)
        references ajr.rating_change (contest_id, athlete_id) on delete cascade
)
"""

BOARD_AT = """
create or replace function ajr.board_at(p_weight text, p_day date)
returns table (athlete_id integer, rating double precision, rd double precision,
               score double precision, last_contest date, place bigint)
language sql
stable
set search_path = ''
as $$
    -- The athletes the table of p_weight lists on p_day: whose latest contest before
    -- it is in this weight and lists them here, or lists them in this weight from
    -- another one (rating_listing).
    with listed as (
        select rc.athlete_id, rc.rating_after, rc.rd_after, rc.fought_on
        from ajr.rating_change rc
        where rc.weight = p_weight
          and rc.fought_on <= p_day
          -- the same as the hiding below, but in a form the index can answer
          and rc.fought_on >= p_day - coalesce(
              (select hide_after_days from ajr.rating_settings), 1000000)
          and rc.next_fought_on > p_day
          and rc.listed_here
        union all
        select l.athlete_id, l.rating_after, l.rd_after, l.fought_on
        from ajr.rating_listing l
        where l.weight = p_weight
          and l.fought_on <= p_day
          and l.fought_on >= p_day - coalesce(
              (select hide_after_days from ajr.rating_settings), 1000000)
          and l.next_fought_on > p_day
    )
    select x.athlete_id,
           x.rating_after,
           rd.value,
           x.rating_after - s.rd_factor * rd.value,
           x.fought_on,
           rank() over (order by x.rating_after - s.rd_factor * rd.value desc)
    from listed x
    cross join ajr.rating_settings s
    cross join lateral (
        select least(s.max_rd, sqrt(x.rd_after ^ 2 + s.rd_growth ^ 2 * (p_day - x.fought_on)))
            as value
    ) rd
    where s.hide_after_days is null or p_day - x.fought_on <= s.hide_after_days
$$
"""


P4P_FULL = """
create or replace function ajr.p4p_full(gender text, day date)
returns table (place bigint, athlete_id integer, family_name text, given_name text,
               country text, weight text, weight_place bigint, rating integer, rd integer,
               score integer, gap integer, trend integer[])
language sql
stable
set search_path = ''
as $$
    -- trend: the score 150, 120, 90, 60 and 30 days ago and on the day, in any weight.
    -- An athlete in two weights' tables counts once, from the weight of the bigger gap.
    with boards as (
        select w.weight, b.*
        from unnest(case p4p_full.gender
                        when 'men' then array['-60', '-66', '-73', '-81', '-90', '-100', '+100']
                        when 'women' then array['-48', '-52', '-57', '-63', '-70', '-78', '+78']
                    end) w(weight)
        cross join lateral ajr.board_at(w.weight, p4p_full.day) b
    ),
    candidates as (
        select distinct on (c.athlete_id) c.*, c.score - pack.score as gap
        from boards c
        cross join lateral (
            select avg(o.score) as score
            from (
                select o.*
                from boards o
                where o.weight = c.weight and o.athlete_id <> c.athlete_id
                order by o.place
                limit 7
            ) o
        ) pack
        where c.place <= 3 and pack.score is not null
        order by c.athlete_id, c.score - pack.score desc
    )
    select rank() over (order by c.gap desc),
           c.athlete_id,
           a.family_name::text,
           a.given_name::text,
           co.ioc::text,
           c.weight,
           c.place,
           round(c.rating)::integer,
           round(c.rd)::integer,
           round(c.score)::integer,
           round(c.gap)::integer,
           array(
               select round(s.score)::integer
               from unnest(array[150, 120, 90, 60, 30, 0]) ago(days)
               left join lateral ajr.score_at(c.athlete_id, p4p_full.day - ago.days) s on true
               order by ago.days desc
           )
    from candidates c
    join ajr.athlete a on a.id = c.athlete_id
    left join ajr.country co on co.id = a.country_id
    order by 1, a.family_name
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
    op.execute("alter table ajr.rating_change add column listed_here boolean not null default true")
    op.execute("drop index ajr.ix_rating_change_weight_fought_on_board")
    op.execute(BOARD_INDEX.format(", listed_here"))
    op.execute(RATING_LISTING)
    op.execute(
        "create index ix_rating_listing_weight_fought_on on ajr.rating_listing "
        "(weight, fought_on) include (next_fought_on, athlete_id, rating_after, rd_after)"
    )
    op.execute(
        "alter table ajr.rating_settings "
        "add column min_tournaments integer, add column listing_days integer"
    )
    op.execute(BOARD_AT)
    op.execute(P4P_FULL)


def downgrade() -> None:
    """Downgrade schema."""
    rankings = load_migration("71f3c9a0b5e8_rankings_fast")
    op.execute(rankings.full("P4P", "gender").replace("create function", "create or replace function"))
    op.execute(load_migration("71f3c9a0b5e8_rankings_fast").board_at())
    op.execute("alter table ajr.rating_settings drop column min_tournaments, drop column listing_days")
    op.execute("drop table ajr.rating_listing")
    op.execute("drop index ajr.ix_rating_change_weight_fought_on_board")
    op.execute(BOARD_INDEX.format(""))
    op.execute("alter table ajr.rating_change drop column listed_here")
