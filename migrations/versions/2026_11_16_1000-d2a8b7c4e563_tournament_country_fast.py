"""tournament country fast

The tournament and country pages read what the rating job now keeps ready (previous
migration, docs/audits/2026-11-08-b2-plan.md): the bracket, the results and the
chances from ajr.contest_list, ajr.athlete_competition and ajr.medal_chance alone, the
tournaments list from ajr.competition_stats, the country page from ajr.nation_summary,
a nation's best per weight from an index of today's tables, its latest tournaments from
an index that stops after `top` rows. A Worlds' bracket: ~14,800 pages, now ~25.

Same arguments and columns. Drops the two indexes the old bodies read. To release
once the publish after the previous migration has filled the columns on production.

Revision ID: d2a8b7c4e563
Revises: c9f4e6a1b352
Create Date: 2026-11-16 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2a8b7c4e563"
down_revision: Union[str, Sequence[str], None] = "c9f4e6a1b352"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_INDEXES = [
    "create index ix_athlete_competition_competition_results on ajr.athlete_competition "
    "(competition_id) include (athlete_id, weight, result, score_before, score_after, "
    "contests, wins, contests_before)",
    "create index ix_leaderboard_snapshot_country_score on ajr.leaderboard_snapshot "
    "(country, score desc)",
]

COMPETITION_CONTESTS = """
create or replace function api.competition_contests(competition_id integer, only_weight text DEFAULT NULL::text)
 RETURNS TABLE(contest_id integer, weight text, round text, winner_id integer, white_id integer, white_family_name text, white_given_name text, white_country text, white_chance double precision, white_score_before integer, white_score_after integer, blue_id integer, blue_family_name text, blue_given_name text, blue_country text, blue_chance double precision, blue_score_before integer, blue_score_after integer, real_fight boolean)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- Decided contests of the bracket, by weight, from the final back to the first round:
    -- the rated ones (real_fight, with chances and scores) and the walkovers of the rated
    -- categories (no chance, no scores). One table: the rating job writes both kinds into
    -- ajr.contest_list, and the publish keeps a tournament's rows together.
    select l.contest_id, l.weight, l.round, l.winner_id,
           l.white_id, l.white_family_name, l.white_given_name, l.white_country,
           l.white_chance, l.white_score_before, l.white_score_after,
           l.blue_id, l.blue_family_name, l.blue_given_name, l.blue_country,
           l.blue_chance, l.blue_score_before, l.blue_score_after, l.real_fight
    from ajr.contest_list l
    where l.competition_id = competition_contests.competition_id
      and (competition_contests.only_weight is null
           or l.weight = competition_contests.only_weight)
    order by coalesce(array_position(array['-60', '-66', '-73', '-81', '-90', '-100', '+100', '-48', '-52', '-57', '-63', '-70', '-78', '+78'], l.weight), 100), l.weight, l.round_no nulls last, l.fight_no, l.contest_id
$function$
"""

OLD_COMPETITION_CONTESTS = """
create or replace function api.competition_contests(competition_id integer, only_weight text DEFAULT NULL::text)
 RETURNS TABLE(contest_id integer, weight text, round text, winner_id integer, white_id integer, white_family_name text, white_given_name text, white_country text, white_chance double precision, white_score_before integer, white_score_after integer, blue_id integer, blue_family_name text, blue_given_name text, blue_country text, blue_chance double precision, blue_score_before integer, blue_score_after integer, real_fight boolean)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- Decided contests, by weight, from the final back to the first round: the rated
    -- ones, and the walkovers of the categories the rating counts (not rated:
    -- no chance, no scores). real_fight: rated (a 0:00 contest is, unless a walkover).
    select x.contest_id, x.weight, x.round, x.winner_id,
           x.white_id, x.white_family_name, x.white_given_name, x.white_country,
           x.white_chance, x.white_score_before, x.white_score_after,
           x.blue_id, x.blue_family_name, x.blue_given_name, x.blue_country,
           x.blue_chance, x.blue_score_before, x.blue_score_after, x.real_fight
    from (
        select ct.id, ct.weight::text, ct.round_name::text, ct.winner_id,
               ct.white_id, w.family_name::text, w.given_name::text, wc.ioc::text,
               wr.win_probability,
               round(wr.rating_before - s.rd_factor * wr.rd_before)::integer,
               round(wr.rating_after - s.rd_factor * wr.rd_after)::integer,
               ct.blue_id, b.family_name::text, b.given_name::text, bc.ioc::text,
               br.win_probability,
               round(br.rating_before - s.rd_factor * br.rd_before)::integer,
               round(br.rating_after - s.rd_factor * br.rd_after)::integer,
               true as real_fight, ct.round, ct.fight_no
        from ajr.contest ct
        cross join ajr.rating_settings s
        join ajr.rating_change wr on wr.contest_id = ct.id and wr.athlete_id <> ct.blue_id
        join ajr.rating_change br on br.contest_id = ct.id and br.athlete_id <> ct.white_id
        join ajr.athlete w on w.id = ct.white_id
        left join ajr.country wc on wc.id = w.country_id
        join ajr.athlete b on b.id = ct.blue_id
        left join ajr.country bc on bc.id = b.country_id
        where ct.competition_id = competition_contests.competition_id
          and (competition_contests.only_weight is null
               or ct.weight = competition_contests.only_weight)
        union all
        select ct.id, ct.weight::text, ct.round_name::text, ct.winner_id,
               ct.white_id, w.family_name::text, w.given_name::text, wc.ioc::text,
               null, null, null,
               ct.blue_id, b.family_name::text, b.given_name::text, bc.ioc::text,
               null, null, null,
               false, ct.round, ct.fight_no
        from ajr.contest ct
        join ajr.competition cm on cm.id = ct.competition_id
        join ajr.athlete w on w.id = ct.white_id
        left join ajr.country wc on wc.id = w.country_id
        join ajr.athlete b on b.id = ct.blue_id
        left join ajr.country bc on bc.id = b.country_id
        where ct.competition_id = competition_contests.competition_id
          and (competition_contests.only_weight is null
               or ct.weight = competition_contests.only_weight)
          and ct.winner_id is not null and cm.kind = 'individual'
          and ct.weight = any(array['-60', '-66', '-73', '-81', '-90', '-100', '+100', '-48', '-52', '-57', '-63', '-70', '-78', '+78'])
          and exists (select from ajr.contest_walkover cw where cw.contest_id = ct.id)
    ) x(contest_id, weight, round, winner_id, white_id, white_family_name,
        white_given_name, white_country, white_chance, white_score_before,
        white_score_after, blue_id, blue_family_name, blue_given_name, blue_country,
        blue_chance, blue_score_before, blue_score_after, real_fight, round_no, fight_no)
    order by coalesce(array_position(array['-60', '-66', '-73', '-81', '-90', '-100', '+100', '-48', '-52', '-57', '-63', '-70', '-78', '+78'], x.weight), 100), x.weight, x.round_no nulls last, x.fight_no
$function$
"""

COMPETITION_RESULTS = """
create or replace function api.competition_results(competition_id integer)
 RETURNS TABLE(athlete_id integer, family_name text, given_name text, gender text, country text, weight text, result text, score_before integer, score_after integer, contests integer, wins integer, contests_before integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- result: gold, silver, bronze, 5th, 7th, the round lost in, or null (still in,
    -- pools, or a bracket where every contest is a "Final"). Names and nation as the
    -- rating job wrote them into the row.
    select r.athlete_id, r.family_name, r.given_name, r.gender, r.country,
           r.weight, r.result, r.score_before, r.score_after, r.contests, r.wins,
           r.contests_before
    from ajr.athlete_competition r
    where r.competition_id = competition_results.competition_id
    order by coalesce(array_position(array['-60', '-66', '-73', '-81', '-90', '-100', '+100', '-48', '-52', '-57', '-63', '-70', '-78', '+78'], r.weight), 100), r.weight,
             array_position(array['gold', 'silver', 'bronze', '5th', '7th'], r.result) nulls last,
             r.score_after desc, r.athlete_id
$function$
"""

OLD_COMPETITION_RESULTS = """
create or replace function api.competition_results(competition_id integer)
 RETURNS TABLE(athlete_id integer, family_name text, given_name text, gender text, country text, weight text, result text, score_before integer, score_after integer, contests integer, wins integer, contests_before integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- result: gold, silver, bronze, 5th, 7th, the round lost in, or null (still in,
    -- pools, or a bracket where every contest is a "Final").
    select r.athlete_id, a.family_name::text, a.given_name::text, a.gender::text, co.ioc::text,
           r.weight, r.result, r.score_before, r.score_after, r.contests, r.wins,
           r.contests_before
    from ajr.athlete_competition r
    join ajr.athlete a on a.id = r.athlete_id
    left join ajr.country co on co.id = a.country_id
    where r.competition_id = competition_results.competition_id
    order by coalesce(array_position(array['-60', '-66', '-73', '-81', '-90', '-100', '+100', '-48', '-52', '-57', '-63', '-70', '-78', '+78'], r.weight), 100), r.weight,
             array_position(array['gold', 'silver', 'bronze', '5th', '7th'], r.result) nulls last,
             r.score_after desc, r.athlete_id
$function$
"""

COMPETITIONS = """
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

OLD_COMPETITIONS = """
create or replace function api.competitions(for_year integer DEFAULT NULL::integer, ranks text[] DEFAULT NULL::text[])
 RETURNS TABLE(id integer, name text, rank_name text, city text, country text, country_name text, date_from date, date_to date, contests integer, accuracy double precision, upsets integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- Individual tournaments with contests (no kata, no team events); ranks are
    -- rank_name values, e.g. array['Grand Slam', 'Grand Prix'].
    select cm.id, cm.name::text, cm.rank_name::text, cm.city::text, co.ioc::text, co.name::text,
           cm.date_from, cm.date_to, st.contests, st.accuracy, st.upsets
    from ajr.competition cm
    join ajr.competition_stats st on st.competition_id = cm.id
    left join ajr.country co on co.id = cm.country_id
    where not coalesce(cm.is_teams, false)
      and (competitions.for_year is null
           or cm.date_from between make_date(competitions.for_year, 1, 1)
                               and make_date(competitions.for_year, 12, 31))
      and (competitions.ranks is null or cm.rank_name = any(competitions.ranks))
    order by cm.date_from desc, cm.id
$function$
"""

COUNTRY = """
create or replace function api.country(ioc text)
 RETURNS TABLE(country text, name text, athletes integer, place integer, place_men integer, place_women integer, rating integer, place_90d integer, rating_90d integer, place_6m integer, rating_6m integer, top1 integer, top8 integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- Everything from ajr.nation_summary, which the rating job fills on every run; a
    -- nation without a rated athlete has no row there: 0 athletes, the rest null.
    select co.ioc::text, co.name::text, coalesce(n.athletes, 0),
           n.place, n.place_men, n.place_women, n.rating,
           n.place_90d, n.rating_90d, n.place_6m, n.rating_6m, n.top1, n.top8
    from ajr.country co
    left join ajr.nation_summary n on n.country_id = co.id
    where co.ioc = country.ioc
$function$
"""

OLD_COUNTRY = """
create or replace function api.country(ioc text)
 RETURNS TABLE(country text, name text, athletes integer, place integer, place_men integer, place_women integer, rating integer, place_90d integer, rating_90d integer, place_6m integer, rating_6m integer, top1 integer, top8 integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- athletes: rated ever. The past: the latest week on or before the day.
    select co.ioc::text, co.name::text,
           (select count(*)::integer
            from ajr.athlete_summary s
            where s.country = co.ioc),  -- ix_athlete_summary_country
           mixed.place, men.place, women.place, mixed.rating,
           d90.place, d90.rating, m6.place, m6.rating,
           best.top1, best.top8
    from ajr.country co
    left join ajr.nation_snapshot mixed on mixed.kind = 'mixed' and mixed.country_id = co.id
    left join ajr.nation_snapshot men on men.kind = 'men' and men.country_id = co.id
    left join ajr.nation_snapshot women on women.kind = 'women' and women.country_id = co.id
    left join ajr.nation_history d90
        on d90.country_id = co.id
       and d90.day = (select max(h.day) from ajr.nation_history h where h.day <= current_date - 90)
    left join ajr.nation_history m6
        on m6.country_id = co.id
       and m6.day = (select max(h.day) from ajr.nation_history h
                     where h.day <= current_date - interval '6 months')
    cross join lateral (
        select max(top.score)::integer as top1, round(avg(top.score))::integer as top8
        from (
            select l.score
            from ajr.leaderboard_snapshot l
            where l.country = co.ioc  -- ix_leaderboard_snapshot_country_score
            order by l.score desc
            limit 8
        ) top
    ) best
    where co.ioc = country.ioc
$function$
"""

COUNTRY_LEADERS = """
create or replace function api.country_leaders(ioc text)
 RETURNS TABLE(weight text, athlete_id integer, family_name text, given_name text, place integer, score integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- The nation's best in every weight today: ix_leaderboard_snapshot_country_leaders
    -- alone. A tie in score goes to the better place.
    select b.weight, b.athlete_id, b.family_name, b.given_name, b.place, b.score
    from (
        select distinct on (l.weight) l.weight::text, l.athlete_id, l.family_name::text,
               l.given_name::text, l.place::integer, l.score::integer
        from ajr.leaderboard_snapshot l
        where l.country = country_leaders.ioc
        order by l.weight, l.score desc, l.place
    ) b
    order by coalesce(array_position(array['-60', '-66', '-73', '-81', '-90', '-100', '+100', '-48', '-52', '-57', '-63', '-70', '-78', '+78'], b.weight), 100)
$function$
"""

OLD_COUNTRY_LEADERS = """
create or replace function api.country_leaders(ioc text)
 RETURNS TABLE(weight text, athlete_id integer, family_name text, given_name text, place integer, score integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    select b.weight, b.athlete_id, b.family_name, b.given_name, b.place, b.score
    from (
        select distinct on (l.weight) l.weight::text, l.athlete_id, a.family_name::text,
               a.given_name::text, l.place::integer, l.score::integer
        from ajr.leaderboard_snapshot l
        join ajr.athlete a on a.id = l.athlete_id
        join ajr.country co on co.id = a.country_id
        where co.ioc = country_leaders.ioc
        order by l.weight, l.score desc
    ) b
    order by array_position(array['-60', '-66', '-73', '-81', '-90', '-100', '+100', '-48', '-52', '-57', '-63', '-70', '-78', '+78'], b.weight)
$function$
"""

COUNTRY_TOURNAMENTS = """
create or replace function api.country_tournaments(ioc text, top integer DEFAULT 10)
 RETURNS TABLE(id integer, name text, rank_name text, date_from date, athletes integer, gold integer, silver integer, bronze integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- The nation's latest tournaments: ix_nation_competition_country_date gives them
    -- newest first, so the scan stops after `top` rows whatever the plan (the join to
    -- country made the planner sort the nation's whole list, 900 pages for Japan).
    select n.competition_id, cm.name::text, cm.rank_name::text, n.date_from,
           n.athletes, n.gold, n.silver, n.bronze
    from ajr.nation_competition n
    join ajr.competition cm on cm.id = n.competition_id
    where n.country = country_tournaments.ioc
    order by n.date_from desc, n.competition_id
    limit country_tournaments.top
$function$
"""

OLD_COUNTRY_TOURNAMENTS = """
create or replace function api.country_tournaments(ioc text, top integer DEFAULT 10)
 RETURNS TABLE(id integer, name text, rank_name text, date_from date, athletes integer, gold integer, silver integer, bronze integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    select cm.id, cm.name::text, cm.rank_name::text, cm.date_from,
           n.athletes, n.gold, n.silver, n.bronze
    from ajr.country co
    join ajr.nation_competition n on n.country_id = co.id
    join ajr.competition cm on cm.id = n.competition_id
    where co.ioc = country_tournaments.ioc
    order by cm.date_from desc, cm.id
    limit country_tournaments.top
$function$
"""

COMPETITION_CHANCES = """
create or replace function api.competition_chances(competition_id integer)
 RETURNS TABLE(weight text, athlete_id integer, family_name text, given_name text, country text, gold double precision, medal double precision)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- Names and nation as the rating job wrote them into the row.
    select mc.weight, mc.athlete_id, mc.family_name, mc.given_name, mc.country,
           mc.gold, mc.medal
    from ajr.medal_chance mc
    where mc.competition_id = competition_chances.competition_id
    order by coalesce(array_position(array['-60', '-66', '-73', '-81', '-90', '-100', '+100', '-48', '-52', '-57', '-63', '-70', '-78', '+78'], mc.weight), 100), mc.weight, mc.medal desc, mc.gold desc
$function$
"""

OLD_COMPETITION_CHANCES = """
create or replace function api.competition_chances(competition_id integer)
 RETURNS TABLE(weight text, athlete_id integer, family_name text, given_name text, country text, gold double precision, medal double precision)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    select mc.weight, mc.athlete_id, a.family_name::text, a.given_name::text, co.ioc::text,
           mc.gold, mc.medal
    from ajr.medal_chance mc
    join ajr.athlete a on a.id = mc.athlete_id
    left join ajr.country co on co.id = a.country_id
    where mc.competition_id = competition_chances.competition_id
    order by coalesce(array_position(array['-60', '-66', '-73', '-81', '-90', '-100', '+100', '-48', '-52', '-57', '-63', '-70', '-78', '+78'], mc.weight), 100), mc.weight, mc.medal desc, mc.gold desc
$function$
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(COMPETITION_CONTESTS)
    op.execute(COMPETITION_RESULTS)
    op.execute(COMPETITIONS)
    op.execute(COUNTRY)
    op.execute(COUNTRY_LEADERS)
    op.execute(COUNTRY_TOURNAMENTS)
    op.execute(COMPETITION_CHANCES)
    op.execute("drop index ajr.ix_athlete_competition_competition_results")
    op.execute("drop index ajr.ix_leaderboard_snapshot_country_score")


def downgrade() -> None:
    """Downgrade schema."""
    for index in OLD_INDEXES:
        op.execute(index)
    op.execute(OLD_COMPETITION_CONTESTS)
    op.execute(OLD_COMPETITION_RESULTS)
    op.execute(OLD_COMPETITIONS)
    op.execute(OLD_COUNTRY)
    op.execute(OLD_COUNTRY_LEADERS)
    op.execute(OLD_COUNTRY_TOURNAMENTS)
    op.execute(OLD_COMPETITION_CHANCES)
