"""p4p and teams

Two more tables for the rankings page, both built from the weight tables of a day
(ajr.board_at):

- api.p4p(gender): pound for pound. The candidates are the top 3 of every
  weight; each is measured against the 7 best others of their own weight (for
  the #1 that is #2-#8, for the #2 the #1 and #3-#8, so within a weight the
  order stays). gap is the score minus their average score. Best gap first.
- api.teams(kind): nations, kind men / women / mixed. A nation's rating is the
  average score of its best athlete in every weight; a weight without one counts
  as the last place of that weight's table. Also how many weights the nation
  leads among nations and in how many it is in the top 8 nations.

Revision ID: 4ae485321e30
Revises: bc0c985bd1f9
Create Date: 2026-10-28 18:54:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4ae485321e30"
down_revision: Union[str, Sequence[str], None] = "bc0c985bd1f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MEN = "array['-60', '-66', '-73', '-81', '-90', '-100', '+100']"
WOMEN = "array['-48', '-52', '-57', '-63', '-70', '-78', '+78']"

P4P = f"""
create function api.p4p(gender text, day date default current_date)
returns table (
    place bigint,
    athlete_id integer,
    family_name text,
    given_name text,
    country text,
    weight text,
    weight_place bigint,
    rating integer,
    rd integer,
    score integer,
    gap integer,
    trend integer[]
)
language sql stable security definer
set search_path = ''
as $$
    -- trend: the score 150, 120, 90, 60 and 30 days ago and on the day, in any weight.
    with boards as (
        select w.weight, b.*
        from unnest(case p4p.gender when 'men' then {MEN} when 'women' then {WOMEN} end) w(weight)
        cross join lateral ajr.board_at(w.weight, p4p.day) b
    )
    select rank() over (order by c.score - pack.score desc),
           c.athlete_id,
           a.family_name::text,
           a.given_name::text,
           co.ioc::text,
           c.weight,
           c.place,
           round(c.rating)::integer,
           round(c.rd)::integer,
           round(c.score)::integer,
           round(c.score - pack.score)::integer,
           array(
               select round(s.score)::integer
               from unnest(array[150, 120, 90, 60, 30, 0]) ago(days)
               left join lateral ajr.score_at(c.athlete_id, p4p.day - ago.days) s on true
               order by ago.days desc
           )
    from boards c
    join ajr.athlete a on a.id = c.athlete_id
    left join ajr.country co on co.id = a.country_id
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
    order by 1, a.family_name
$$
"""

TEAMS = f"""
create function api.teams(kind text, day date default current_date)
returns table (
    place bigint,
    country text,
    country_name text,
    rating integer,
    weights_led integer,
    weights_top8 integer,
    weights_filled integer
)
language sql stable security definer
set search_path = ''
as $$
    with boards as (
        select w.weight, b.athlete_id, b.score
        from unnest(case teams.kind
                        when 'men' then {MEN}
                        when 'women' then {WOMEN}
                        when 'mixed' then {MEN} || {WOMEN}
                    end) w(weight)
        cross join lateral ajr.board_at(w.weight, teams.day) b
    ),
    -- each nation's best athlete in every weight, and its place among the nations
    best as (
        select weight, country_id, score,
               rank() over (partition by weight order by score desc) as nation_place
        from (
            select distinct on (b.weight, a.country_id) b.weight, a.country_id, b.score
            from boards b
            join ajr.athlete a on a.id = b.athlete_id
            where a.country_id is not null
            order by b.weight, a.country_id, b.score desc
        ) by_nation
    ),
    -- what an empty weight counts as: the last place of its table
    last_place as (
        select weight, min(score) as score from boards group by weight
    ),
    nations as (
        select n.country_id,
               avg(coalesce(best.score, last_place.score)) as score,
               count(*) filter (where best.nation_place = 1) as led,
               count(*) filter (where best.nation_place <= 8) as top8,
               count(best.weight) as filled
        from (select distinct country_id from best) n
        cross join last_place
        left join best on best.country_id = n.country_id and best.weight = last_place.weight
        group by n.country_id
    )
    select rank() over (order by n.score desc),
           co.ioc::text,
           co.name::text,
           round(n.score)::integer,
           n.led::integer,
           n.top8::integer,
           n.filled::integer
    from nations n
    join ajr.country co on co.id = n.country_id
    order by 1, co.name
$$
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(P4P)
    op.execute(TEAMS)
    for function in ("api.p4p(text, date)", "api.teams(text, date)"):
        op.execute(f"revoke execute on function {function} from public")
        op.execute(f"grant execute on function {function} to anon, authenticated")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop function api.teams(text, date)")
    op.execute("drop function api.p4p(text, date)")
