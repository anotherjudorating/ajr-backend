"""live chances: the entries, the chances of every round and of every contest's place

judobase's contest sheets have a weight's whole draw once the IJF publishes it (the
day before), every contest by its number; the medal chances play it (ajr/rating/chances.py):

- ajr.draw: a tournament's draws, every contest of a weight's bracket by its number,
  the ones not fought yet too (judobase's contest sheets, the day before);
- ajr.medal_chance: also the athlete's rating on the day, and the chance of reaching the quarter-finals, the semi-finals
  and the final;
- ajr.slot_chance: for every contest of the bracket by its number, who is in it with
  what chance and with what chance they win it (a contest fought: its two athletes,
  1 and 0; its id), the names and nation written in as in ajr.medal_chance.

api.competition_chances gives the rounds' chances too; api.competition_slots(id,
weight) the bracket's contests; api.upcoming_contest(id) a contest not fought yet with
its athletes' ratings on the day (ajr.state_on: as the engine takes them).

Revision ID: d7a3c5e9f104
Revises: b9f5d3a7c128
Create Date: 2026-11-26 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7a3c5e9f104"
down_revision: Union[str, Sequence[str], None] = "b9f5d3a7c128"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WEIGHT_ORDER = (
    "coalesce(array_position(array['-60', '-66', '-73', '-81', '-90', '-100', '+100',"
    " '-48', '-52', '-57', '-63', '-70', '-78', '+78'], mc.weight), 100)"
)

DRAW = """
create table ajr.draw (
    competition_id integer not null references ajr.competition (id),
    weight text not null,
    fight_no integer not null,
    contest_id integer,
    blue_id integer references ajr.athlete (id),
    white_id integer references ajr.athlete (id),
    winner_id integer references ajr.athlete (id),
    primary key (competition_id, weight, fight_no)
)
"""

SLOT = """
create table ajr.slot_chance (
    competition_id integer not null references ajr.competition (id),
    weight text not null,
    fight_no integer not null,
    athlete_id integer not null references ajr.athlete (id),
    round text not null,
    here double precision not null,
    wins double precision not null,
    contest_id integer,
    family_name text,
    given_name text,
    country text,
    primary key (competition_id, weight, fight_no, athlete_id)
)
"""

COMPETITION_CHANCES = f"""
create function api.competition_chances(competition_id integer)
returns table (
    weight text, athlete_id integer, family_name text, given_name text, country text,
    gold double precision, medal double precision,
    quarter double precision, semi double precision, final double precision,
    rating double precision
)
language sql stable security definer
set search_path = ''
as $$
    -- Names and nation as the rating job wrote them into the row.
    select mc.weight, mc.athlete_id, mc.family_name, mc.given_name, mc.country,
           mc.gold, mc.medal, mc.quarter, mc.semi, mc.final, mc.rating
    from ajr.medal_chance mc
    where mc.competition_id = competition_chances.competition_id
    order by {WEIGHT_ORDER}, mc.weight, mc.medal desc, mc.gold desc
$$
"""

OLD_COMPETITION_CHANCES = f"""
create function api.competition_chances(competition_id integer)
returns table (
    weight text, athlete_id integer, family_name text, given_name text, country text,
    gold double precision, medal double precision
)
language sql stable security definer
set search_path = ''
as $$
    select mc.weight, mc.athlete_id, mc.family_name, mc.given_name, mc.country,
           mc.gold, mc.medal
    from ajr.medal_chance mc
    where mc.competition_id = competition_chances.competition_id
    order by {WEIGHT_ORDER}, mc.weight, mc.medal desc, mc.gold desc
$$
"""

COMPETITION_SLOTS = """
create function api.competition_slots(competition_id integer, weight text)
returns table (
    fight_no integer, round text, athlete_id integer, family_name text, given_name text,
    country text, here double precision, wins double precision, contest_id integer
)
language sql stable security definer
set search_path = ''
as $$
    select s.fight_no, s.round, s.athlete_id, s.family_name, s.given_name, s.country,
           s.here, s.wins, s.contest_id
    from ajr.slot_chance s
    where s.competition_id = competition_slots.competition_id
      and s.weight = competition_slots.weight
    order by s.fight_no, s.here desc, s.wins desc
$$
"""


# An athlete's rating on the day of a contest in `weight`, as the engine takes it
# (ajr/rating/engine.py): the latest one, its RD grown for the days since, and a move
# to another weight's handicap (a share of the skill: a minus up, a plus down); a new
# athlete's the initial one.
STATE_ON = """
create function ajr.state_on(athlete integer, day date, weight text)
returns table (skill double precision, rd double precision, volatility double precision)
language sql stable
set search_path = ''
as $$
    with s as (select * from ajr.rating_settings limit 1),
    w as (select array['-60', '-66', '-73', '-81', '-90', '-100', '+100'] as men,
                 array['-48', '-52', '-57', '-63', '-70', '-78', '+78'] as women),
    latest as (
        select rc.rating_after, rc.rd_after, rc.volatility_after, rc.fought_on
        from ajr.rating_change rc
        where rc.athlete_id = state_on.athlete and rc.next_fought_on = date '9999-12-31'
        limit 1
    ),
    last_weight as (
        select rc.weight from ajr.rating_change rc, w
        where rc.athlete_id = state_on.athlete
          and (rc.weight = any(w.men) or rc.weight = any(w.women))
        order by rc.fought_on desc, rc.seq desc
        limit 1
    ),
    base as (
        select coalesce(l.rating_after, s.initial_rating) as skill,
               case when l.rd_after is null then s.initial_rd
                    else least(sqrt(l.rd_after ^ 2 + s.rd_growth ^ 2
                                    * greatest(0, state_on.day - l.fought_on)), s.max_rd)
               end as rd,
               coalesce(l.volatility_after, s.initial_volatility) as volatility,
               coalesce(s.move_handicap, 0) as handicap
        from s left join latest l on true
    )
    select b.skill + case
               when lw.weight is null or lw.weight = state_on.weight then 0
               when lw.weight = any(w.men) and state_on.weight = any(w.men)
                 then b.handicap * b.skill * case when array_position(w.men, state_on.weight)
                                                    > array_position(w.men, lw.weight) then -1 else 1 end
               when lw.weight = any(w.women) and state_on.weight = any(w.women)
                 then b.handicap * b.skill * case when array_position(w.women, state_on.weight)
                                                    > array_position(w.women, lw.weight) then -1 else 1 end
               else 0 end,
           b.rd, b.volatility
    from base b cross join w left join last_weight lw on true
$$
"""

# A contest of a draw not fought yet, both its athletes known: the two athletes and their
# ratings on the day, for the site to work out what each result would do.
UPCOMING_CONTEST = """
create function api.upcoming_contest(contest_id integer)
returns table (
    contest_id integer, competition_id integer, competition text, competition_rank text,
    city text, country text, day date, weight text, round text,
    white_id integer, white_family_name text, white_given_name text, white_country text,
    white_skill double precision, white_rd double precision, white_volatility double precision,
    blue_id integer, blue_family_name text, blue_given_name text, blue_country text,
    blue_skill double precision, blue_rd double precision, blue_volatility double precision,
    tau double precision, rd_factor double precision
)
language sql stable security definer
set search_path = ''
as $$
    select d.contest_id, d.competition_id, cm.name::text, cm.rank_name::text, cm.city::text,
           cc.ioc::text, greatest(cm.date_from, current_date), d.weight,
           (select sc.round from ajr.slot_chance sc
             where sc.competition_id = d.competition_id and sc.weight = d.weight
               and sc.fight_no = d.fight_no limit 1),
           w.id, w.family_name::text, w.given_name::text, wc.ioc::text, ws.skill, ws.rd, ws.volatility,
           b.id, b.family_name::text, b.given_name::text, bc.ioc::text, bs.skill, bs.rd, bs.volatility,
           s.tau, s.rd_factor
    from ajr.draw d
    join ajr.competition cm on cm.id = d.competition_id
    left join ajr.country cc on cc.id = cm.country_id
    join ajr.athlete w on w.id = d.white_id
    left join ajr.country wc on wc.id = w.country_id
    join ajr.athlete b on b.id = d.blue_id
    left join ajr.country bc on bc.id = b.country_id
    cross join lateral ajr.state_on(d.white_id, greatest(cm.date_from, current_date), d.weight) ws
    cross join lateral ajr.state_on(d.blue_id, greatest(cm.date_from, current_date), d.weight) bs
    cross join (select * from ajr.rating_settings limit 1) s
    where d.contest_id = upcoming_contest.contest_id
      and d.winner_id is null
      and not exists (select from ajr.contest ct
                      where ct.id = d.contest_id and ct.winner_id is not null)
$$
"""

# The tournaments' list: also the ones to come this year (their contests, accuracy and
# upsets null), the site lists them as Upcoming.
COMPETITIONS = """
create or replace function api.competitions(for_year integer DEFAULT NULL::integer, ranks text[] DEFAULT NULL::text[])
 RETURNS TABLE(id integer, name text, rank_name text, city text, country text, country_name text, date_from date, date_to date, contests integer, accuracy double precision, upsets integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- Individual tournaments with rated contests, from ajr.competition_stats alone (the
    -- rating job copies the tournament's columns into it), and the individual ones to
    -- come, not fought yet; ranks are rank_name values.
    select x.* from (
        select st.competition_id, st.name, st.rank_name, st.city, st.country, st.country_name,
               st.date_from, st.date_to, st.contests, st.accuracy, st.upsets
        from ajr.competition_stats st
        union all
        select cm.id, cm.name::text, cm.rank_name::text, cm.city::text, co.ioc::text, co.name::text,
               cm.date_from, cm.date_to, null::integer, null::double precision, null::integer
        from ajr.competition cm
        left join ajr.country co on co.id = cm.country_id
        where cm.date_from > current_date and cm.kind = 'individual'
          and not coalesce(cm.is_teams, false)
          and not exists (select from ajr.competition_stats st where st.competition_id = cm.id)
    ) x
    where (competitions.for_year is null
           or x.date_from between make_date(competitions.for_year, 1, 1)
                              and make_date(competitions.for_year, 12, 31))
      and (competitions.ranks is null or x.rank_name = any(competitions.ranks))
    order by x.date_from desc, x.competition_id
$function$
"""

OLD_COMPETITIONS = """
create or replace function api.competitions(for_year integer DEFAULT NULL::integer, ranks text[] DEFAULT NULL::text[])
 RETURNS TABLE(id integer, name text, rank_name text, city text, country text, country_name text, date_from date, date_to date, contests integer, accuracy double precision, upsets integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- Individual tournaments with rated contests, from ajr.competition_stats alone (the
    -- rating job copies the tournament's columns into it); ranks are rank_name values.
    select st.competition_id, st.name, st.rank_name, st.city, st.country, st.country_name,
           st.date_from, st.date_to, st.contests, st.accuracy, st.upsets
    from ajr.competition_stats st
    where (competitions.for_year is null
           or st.date_from between make_date(competitions.for_year, 1, 1)
                               and make_date(competitions.for_year, 12, 31))
      and (competitions.ranks is null or st.rank_name = any(competitions.ranks))
    order by st.date_from desc, st.competition_id
$function$
"""

def grant(signature: str) -> None:
    op.execute(f"revoke execute on function {signature} from public")
    op.execute(f"grant execute on function {signature} to anon, authenticated")


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(DRAW)
    op.execute(SLOT)
    for column in ("quarter", "semi", "final"):
        op.execute(
            f"alter table ajr.medal_chance add column {column} double precision not null default 0"
        )
    op.execute("alter table ajr.medal_chance add column rating double precision")
    op.execute("drop function api.competition_chances(integer)")
    op.execute(COMPETITION_CHANCES)
    grant("api.competition_chances(integer)")
    op.execute(COMPETITION_SLOTS)
    grant("api.competition_slots(integer, text)")
    op.execute(STATE_ON)
    op.execute(UPCOMING_CONTEST)
    grant("api.upcoming_contest(integer)")
    op.execute(COMPETITIONS)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(OLD_COMPETITIONS)
    op.execute("drop function api.upcoming_contest(integer)")
    op.execute("drop function ajr.state_on(integer, date, text)")
    op.execute("drop function api.competition_slots(integer, text)")
    op.execute("drop function api.competition_chances(integer)")
    op.execute(OLD_COMPETITION_CHANCES)
    grant("api.competition_chances(integer)")
    for column in ("quarter", "semi", "final", "rating"):
        op.execute(f"alter table ajr.medal_chance drop column {column}")
    op.execute("drop table ajr.slot_chance")
    op.execute("drop table ajr.draw")
