"""history fast

The athlete's page, the contest page, the nations list and the sitemap read what the
rating job now keeps ready (previous migration, docs/audits/2026-11-08-b1-plan.md):

- api.athlete_history and api.contest_context read the history facts written into
  ajr.rating_change (one table, an athlete's rows together after the publish built it
  in athlete order; only the tournament's name is joined): ~5,000 pages for a long
  career on a copy of production, now ~60;
- api.athlete reads ajr.athlete_summary alone (no ajr.score_at, no ajr.board_at);
- api.nations reads ajr.nation_summary (2 pages, was 1,279);
- api.sitemap's tournaments are sorted after a scan instead of walking an index
  (42 pages, was 550); its athletes are read from the index alone.

Same arguments and columns. To release once the rating run and the publish after
the previous migration have filled the facts on production (no row with
competition_id null).

Revision ID: b8e3d5f0a241
Revises: a7d2c4e9f130
Create Date: 2026-11-14 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8e3d5f0a241"
down_revision: Union[str, Sequence[str], None] = "a7d2c4e9f130"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ATHLETE_HISTORY = """
create or replace function api.athlete_history(athlete_id integer, only_weight text DEFAULT NULL::text)
 RETURNS TABLE(contest_id integer, fought_on date, competition_id integer, competition text, round text, weight text, opponent_id integer, opponent_family_name text, opponent_given_name text, opponent_country text, won boolean, win_probability double precision, rating_before integer, rating_after integer, rd_after integer, rd_before integer, score_before integer, score_after integer, opponent_score integer, result text)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- Latest first; within a day the later round (judobase counts down to the final) first.
    -- weight is the category the contest counts for (an open-weight contest keeps the
    -- athlete's), and only_weight picks the contests of one category.
    -- One table: the contest's round, the opponent's name and rating before, and the
    -- tournament result are written into the row by the rating job
    -- (ajr/rating/snapshot.py, HISTORY_FACTS), and the publish keeps an athlete's rows
    -- together; only the tournament's name is looked up.
    select rc.contest_id,
           rc.fought_on,
           rc.competition_id,
           cm.name::text,
           rc.round_name,
           rc.weight::text,
           rc.opponent_id,
           rc.opponent_family_name,
           rc.opponent_given_name,
           rc.opponent_country,
           rc.won,
           rc.win_probability,
           round(rc.rating_before)::integer,
           round(rc.rating_after)::integer,
           round(rc.rd_after)::integer,
           round(rc.rd_before)::integer,
           round(rc.rating_before - s.rd_factor * rc.rd_before)::integer,
           round(rc.rating_after - s.rd_factor * rc.rd_after)::integer,
           round(rc.opponent_rating_before - s.rd_factor * rc.opponent_rd_before)::integer,
           rc.result
    from ajr.rating_change rc
    cross join ajr.rating_settings s
    join ajr.competition cm on cm.id = rc.competition_id
    where rc.athlete_id = athlete_history.athlete_id
      and (athlete_history.only_weight is null or rc.weight = athlete_history.only_weight)
    order by rc.fought_on desc, rc.round nulls last, rc.fight_no desc, rc.contest_id desc
$function$
"""

OLD_ATHLETE_HISTORY = """
create or replace function api.athlete_history(athlete_id integer, only_weight text DEFAULT NULL::text)
 RETURNS TABLE(contest_id integer, fought_on date, competition_id integer, competition text, round text, weight text, opponent_id integer, opponent_family_name text, opponent_given_name text, opponent_country text, won boolean, win_probability double precision, rating_before integer, rating_after integer, rd_after integer, rd_before integer, score_before integer, score_after integer, opponent_score integer, result text)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- Latest first; within a day the later round (judobase counts down to the final) first.
    -- weight is the category the contest counts for (an open-weight contest keeps
    -- the athlete's), and only_weight picks the contests of one category.
    -- result: how the athlete ended the competition (ajr.athlete_competition).
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
           r.result
    from ajr.rating_change rc
    cross join ajr.rating_settings s
    join ajr.contest ct on ct.id = rc.contest_id
    join ajr.competition cm on cm.id = ct.competition_id
    join ajr.athlete o on o.id = rc.opponent_id
    left join ajr.country co on co.id = o.country_id
    left join ajr.rating_change orc
        on orc.contest_id = rc.contest_id and orc.athlete_id = rc.opponent_id
    left join ajr.athlete_competition r
        on r.athlete_id = rc.athlete_id and r.competition_id = ct.competition_id
       and r.weight = ct.weight
    where rc.athlete_id = athlete_history.athlete_id
      and (athlete_history.only_weight is null or rc.weight = athlete_history.only_weight)
    order by rc.fought_on desc, ct.round nulls last, ct.fight_no desc, ct.id desc
$function$
"""

CONTEST_CONTEXT = """
create or replace function api.contest_context(contest_id integer)
 RETURNS TABLE(side text, kind text, contest_id integer, fought_on date, competition_id integer, competition text, round text, weight text, opponent_id integer, opponent_family_name text, opponent_given_name text, opponent_country text, won boolean, win_probability double precision, rating_before integer, rating_after integer, rd_after integer, rd_before integer, score_before integer, score_after integer, opponent_score integer, result text)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- Rows as api.athlete_history's (latest first): each athlete's contests at the
    -- tournament of this one (road), and the white athlete's contests against the blue
    -- one (meeting); this contest is among them.
    with c as (
        select ct.competition_id, ct.white_id, ct.blue_id
        from ajr.contest ct
        where ct.id = contest_context.contest_id
    ),
    picked as (
        select s.side, 'road' as kind, s.athlete_id, ct.id
        from c
        cross join lateral (values ('white', c.white_id), ('blue', c.blue_id)) s(side, athlete_id)
        join ajr.contest ct
            on ct.competition_id = c.competition_id and s.athlete_id in (ct.blue_id, ct.white_id)
        union all
        select 'white', 'meeting', c.white_id, ct.id
        from c
        join ajr.contest ct
            on (ct.blue_id = c.white_id and ct.white_id = c.blue_id)
            or (ct.white_id = c.white_id and ct.blue_id = c.blue_id)
    )
    select p.side,
           p.kind,
           rc.contest_id,
           rc.fought_on,
           rc.competition_id,
           cm.name::text,
           rc.round_name,
           rc.weight::text,
           rc.opponent_id,
           rc.opponent_family_name,
           rc.opponent_given_name,
           rc.opponent_country,
           rc.won,
           rc.win_probability,
           round(rc.rating_before)::integer,
           round(rc.rating_after)::integer,
           round(rc.rd_after)::integer,
           round(rc.rd_before)::integer,
           round(rc.rating_before - s.rd_factor * rc.rd_before)::integer,
           round(rc.rating_after - s.rd_factor * rc.rd_after)::integer,
           round(rc.opponent_rating_before - s.rd_factor * rc.opponent_rd_before)::integer,
           rc.result
    from picked p
    join ajr.rating_change rc on rc.contest_id = p.id and rc.athlete_id = p.athlete_id
    cross join ajr.rating_settings s
    join ajr.competition cm on cm.id = rc.competition_id
    order by p.side desc, p.kind desc, rc.fought_on desc, rc.round nulls last,
             rc.fight_no desc, rc.contest_id desc
$function$
"""

OLD_CONTEST_CONTEXT = """
create or replace function api.contest_context(contest_id integer)
 RETURNS TABLE(side text, kind text, contest_id integer, fought_on date, competition_id integer, competition text, round text, weight text, opponent_id integer, opponent_family_name text, opponent_given_name text, opponent_country text, won boolean, win_probability double precision, rating_before integer, rating_after integer, rd_after integer, rd_before integer, score_before integer, score_after integer, opponent_score integer, result text)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- Rows as api.athlete_history's (latest first): each athlete's contests at the
    -- tournament of this one (road), and the white athlete's contests against the blue
    -- one (meeting); this contest is among them.
    with c as (
        select ct.competition_id, ct.white_id, ct.blue_id
        from ajr.contest ct
        where ct.id = contest_context.contest_id
    ),
    picked as (
        select s.side, 'road' as kind, s.athlete_id, ct.id
        from c
        cross join lateral (values ('white', c.white_id), ('blue', c.blue_id)) s(side, athlete_id)
        join ajr.contest ct
            on ct.competition_id = c.competition_id and s.athlete_id in (ct.blue_id, ct.white_id)
        union all
        select 'white', 'meeting', c.white_id, ct.id
        from c
        join ajr.contest ct
            on (ct.blue_id = c.white_id and ct.white_id = c.blue_id)
            or (ct.white_id = c.white_id and ct.blue_id = c.blue_id)
    )
    select p.side,
           p.kind,
           rc.contest_id,
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
           r.result
    from picked p
    join ajr.rating_change rc on rc.contest_id = p.id and rc.athlete_id = p.athlete_id
    cross join ajr.rating_settings s
    join ajr.contest ct on ct.id = rc.contest_id
    join ajr.competition cm on cm.id = ct.competition_id
    join ajr.athlete o on o.id = rc.opponent_id
    left join ajr.country co on co.id = o.country_id
    left join ajr.rating_change orc
        on orc.contest_id = rc.contest_id and orc.athlete_id = rc.opponent_id
    left join ajr.athlete_competition r
        on r.athlete_id = rc.athlete_id and r.competition_id = ct.competition_id
       and r.weight = ct.weight
    order by p.side desc, p.kind desc, rc.fought_on desc, ct.round nulls last,
             ct.fight_no desc, ct.id desc
$function$
"""

ATHLETE = """
create or replace function api.athlete(athlete_id integer)
 RETURNS TABLE(id integer, family_name text, given_name text, gender text, birth_year integer, country text, country_name text, weight text, rating integer, rd integer, score integer, place bigint, last_contest date, contests bigint, wrl_place integer, weights text[], peak_score integer, peak_on date, peak_place bigint, score_change_90d integer, score_change_6m integer, places_up_90d integer, places_up_6m integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- Everything but the athlete's own row comes from ajr.athlete_summary, which the
    -- rating job fills on every run (ajr/rating/snapshot.py): rating, RD and score on
    -- the day of the run, the place (null when hidden: a year without contests), the
    -- changes over 90 days and 6 months, the peak and the place on its day.
    -- weights: the categories fought in, the latest first.
    select a.id,
           a.family_name::text,
           a.given_name::text,
           a.gender::text,
           a.dob_year,
           co.ioc::text,
           co.name::text,
           sm.weight,
           sm.rating,
           sm.rd,
           sm.score_today,
           sm.place::bigint,
           sm.last_contest,
           sm.contests::bigint,
           sm.wrl_place,
           coalesce(sm.weights, '{}'),
           sm.peak_score,
           sm.peak_on,
           sm.peak_place::bigint,
           sm.score_change_90d,
           sm.score_change_6m,
           sm.places_up_90d,
           sm.places_up_6m
    from ajr.athlete a
    left join ajr.country co on co.id = a.country_id
    left join ajr.athlete_summary sm on sm.athlete_id = a.id
    where a.id = athlete.athlete_id
$function$
"""

OLD_ATHLETE = """
create or replace function api.athlete(athlete_id integer)
 RETURNS TABLE(id integer, family_name text, given_name text, gender text, birth_year integer, country text, country_name text, weight text, rating integer, rd integer, score integer, place bigint, last_contest date, contests bigint, wrl_place integer, weights text[], peak_score integer, peak_on date, peak_place bigint, score_change_90d integer, score_change_6m integer, places_up_90d integer, places_up_6m integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
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
           sm.weight,
           round(now.rating)::integer,
           round(now.rd)::integer,
           round(now.score)::integer,
           board.place::bigint,
           sm.last_contest,
           sm.contests::bigint,
           w.place,
           coalesce(sm.weights, '{}'),
           sm.peak_score,
           sm.peak_on,
           (select b.place
            from ajr.board_at(sm.peak_weight, sm.peak_on) b
            where b.athlete_id = a.id),
           round(now.score - s90.score)::integer,
           round(now.score - s6m.score)::integer,
           board.places_up_90d,
           board.places_up_6m
    from ajr.athlete a
    left join ajr.country co on co.id = a.country_id
    -- the latest contest's weight and day, and the counts, as the job left them
    left join ajr.athlete_summary sm on sm.athlete_id = a.id
    left join lateral ajr.score_at(a.id, current_date) now on true
    left join lateral ajr.score_at(a.id, current_date - 90) s90 on true
    left join lateral ajr.score_at(a.id, (current_date - interval '6 months')::date) s6m on true
    left join ajr.leaderboard_snapshot board
        on board.athlete_id = a.id and board.weight = sm.weight
    left join ajr.wrl_ranking w on w.athlete_id = a.id and w.weight = sm.weight
    where a.id = athlete.athlete_id
$function$
"""

NATIONS = """
create or replace function api.nations()
 RETURNS TABLE(country text, name text, athletes integer, active integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- active: in a weight's table today. From ajr.nation_summary (the rating job).
    select n.country, n.name, n.athletes, n.active
    from ajr.nation_summary n
    order by n.name
$function$
"""

OLD_NATIONS = """
create or replace function api.nations()
 RETURNS TABLE(country text, name text, athletes integer, active integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- active: in a weight's table today
    select co.ioc::text, co.name::text, count(*)::integer, count(s.place)::integer
    from ajr.athlete_summary s
    join ajr.athlete a on a.id = s.athlete_id
    join ajr.country co on co.id = a.country_id
    where co.ioc is not null
    group by co.ioc, co.name
    order by co.name
$function$
"""

SITEMAP = """
create or replace function api.sitemap()
 RETURNS json
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    select json_build_object(
        'athletes', (
            select json_agg(json_build_array(s.athlete_id, s.last_contest, s.contests)
                            order by s.athlete_id)
            from ajr.athlete_summary s
        ),
        'tournaments', (
            select json_agg(json_build_array(cm.id, coalesce(cm.date_to, cm.date_from))
                            -- + 0: without it the planner walks competition's index and
                            -- probes competition_stats per row (550 pages for 779 rows)
                            order by cm.id + 0)
            from ajr.competition cm
            join ajr.competition_stats st on st.competition_id = cm.id
        ),
        'nations', (
            select json_agg(distinct co.ioc)
            from ajr.nation_snapshot n
            join ajr.country co on co.id = n.country_id
            where co.ioc is not null
        )
    )
$function$
"""

OLD_SITEMAP = """
create or replace function api.sitemap()
 RETURNS json
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    select json_build_object(
        'athletes', (
            select json_agg(json_build_array(s.athlete_id, s.last_contest, s.contests)
                            order by s.athlete_id)
            from ajr.athlete_summary s
        ),
        'tournaments', (
            select json_agg(json_build_array(cm.id, coalesce(cm.date_to, cm.date_from))
                            order by cm.id)
            from ajr.competition cm
            join ajr.competition_stats st on st.competition_id = cm.id
        ),
        'nations', (
            select json_agg(distinct co.ioc)
            from ajr.nation_snapshot n
            join ajr.country co on co.id = n.country_id
            where co.ioc is not null
        )
    )
$function$
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(ATHLETE_HISTORY)
    op.execute(CONTEST_CONTEXT)
    op.execute(ATHLETE)
    op.execute(NATIONS)
    op.execute(SITEMAP)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(OLD_ATHLETE_HISTORY)
    op.execute(OLD_CONTEST_CONTEXT)
    op.execute(OLD_ATHLETE)
    op.execute(OLD_NATIONS)
    op.execute(OLD_SITEMAP)
