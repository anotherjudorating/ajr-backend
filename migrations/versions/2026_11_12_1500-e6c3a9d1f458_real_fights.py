"""real fights

The rating counts only real fights (ajr/rating/engine.py, RatingParams.real_fights_only;
docs/audits/2026-11-06-real-fights.md): contests of individual seniors' events
(ajr.competition.kind), in the 14 weight categories, no walkovers
(ajr.contest_walkover). Before, every decided contest counted: the Paralympic Games
Tokyo 2020, a training camp, the open category and the odd weights (-55, -44, -93) of
a few old championships, and 1,699 walkovers. Measured on the bench
(.claude/skills/rating-experiment, experiment real_fights): log loss 2025-26 -0.8
thousandths (significant), elsewhere within noise.

What the site shows of a contest that is not rated:
- a walkover of a counted category stays in the tournament's bracket
  (api.competition_contests: no chance, no scores, real_fight false) and decides the
  medal (ajr.athlete_competition, ajr/rating/snapshot.py); api.contest says which
  walkover it was (walkover: fusen or likely, a new column at the end);
- the other kinds of event and the other categories are not shown, as nothing reads
  them but through the rating.

The settings row the job saved has no real_fights_only, so the next rating run rates
everything again.

Revision ID: e6c3a9d1f458
Revises: d4f8b2c6a071
Create Date: 2026-11-12 15:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6c3a9d1f458"
down_revision: Union[str, Sequence[str], None] = "d4f8b2c6a071"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONTEST = """
create function api.contest(contest_id integer)
 RETURNS TABLE(contest_id integer, competition_id integer, competition text, competition_rank text, city text, day date, weight text, round text, duration text, golden_score boolean, winner_id integer, white_id integer, white_family_name text, white_given_name text, white_country text, white_place_before bigint, white_ippon integer, white_waza integer, white_yuko integer, white_shido integer, white_win_probability double precision, white_rating_before integer, white_rating_after integer, white_rd_before integer, white_rd_after integer, white_score_before integer, white_score_after integer, blue_id integer, blue_family_name text, blue_given_name text, blue_country text, blue_place_before bigint, blue_ippon integer, blue_waza integer, blue_yuko integer, blue_shido integer, blue_win_probability double precision, blue_rating_before integer, blue_rating_after integer, blue_rd_before integer, blue_rd_after integer, blue_score_before integer, blue_score_after integer, walkover text)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- Place: in the weight's table the day before the contest. No rating rows for
    -- a contest that was not fought or not rated (a bye, a walkover, not decided yet,
    -- another kind of event or category). walkover: ajr.contest_walkover's reason
    -- (fusen: tagged Fusen-Gachi; likely: nothing was fought), null for a fight.
    select ct.id,
           cm.id,
           cm.name::text,
           cm.rank_name::text,
           cm.city::text,
           coalesce(white_rc.fought_on, ct.started_at::date, cm.date_from),
           ct.weight::text,
           ct.round_name::text,
           ct.duration::text,
           ct.golden_score,
           ct.winner_id,
           ct.white_id,
           white_a.family_name::text,
           white_a.given_name::text,
           white_co.ioc::text,
           (select b.place
            from ajr.board_at(white_rc.weight, white_rc.fought_on - 1) b
            where b.athlete_id = ct.white_id),
           ct.ippon_w,
           ct.waza_w,
           ct.yuko_w,
           ct.penalty_w,
           white_rc.win_probability,
           round(white_rc.rating_before)::integer,
           round(white_rc.rating_after)::integer,
           round(white_rc.rd_before)::integer,
           round(white_rc.rd_after)::integer,
           round(white_rc.rating_before - s.rd_factor * white_rc.rd_before)::integer,
           round(white_rc.rating_after - s.rd_factor * white_rc.rd_after)::integer,
           ct.blue_id,
           blue_a.family_name::text,
           blue_a.given_name::text,
           blue_co.ioc::text,
           (select b.place
            from ajr.board_at(blue_rc.weight, blue_rc.fought_on - 1) b
            where b.athlete_id = ct.blue_id),
           ct.ippon_b,
           ct.waza_b,
           ct.yuko_b,
           ct.penalty_b,
           blue_rc.win_probability,
           round(blue_rc.rating_before)::integer,
           round(blue_rc.rating_after)::integer,
           round(blue_rc.rd_before)::integer,
           round(blue_rc.rd_after)::integer,
           round(blue_rc.rating_before - s.rd_factor * blue_rc.rd_before)::integer,
           round(blue_rc.rating_after - s.rd_factor * blue_rc.rd_after)::integer,
           (select w.reason::text from ajr.contest_walkover w where w.contest_id = ct.id)
    from ajr.contest ct
    join ajr.competition cm on cm.id = ct.competition_id
    cross join ajr.rating_settings s
    left join ajr.athlete white_a on white_a.id = ct.white_id
    left join ajr.country white_co on white_co.id = white_a.country_id
    left join ajr.rating_change white_rc
        on white_rc.contest_id = ct.id and white_rc.athlete_id = ct.white_id
    left join ajr.athlete blue_a on blue_a.id = ct.blue_id
    left join ajr.country blue_co on blue_co.id = blue_a.country_id
    left join ajr.rating_change blue_rc
        on blue_rc.contest_id = ct.id and blue_rc.athlete_id = ct.blue_id
    where ct.id = contest.contest_id
$function$
"""

OLD_CONTEST = """
create function api.contest(contest_id integer)
 RETURNS TABLE(contest_id integer, competition_id integer, competition text, competition_rank text, city text, day date, weight text, round text, duration text, golden_score boolean, winner_id integer, white_id integer, white_family_name text, white_given_name text, white_country text, white_place_before bigint, white_ippon integer, white_waza integer, white_yuko integer, white_shido integer, white_win_probability double precision, white_rating_before integer, white_rating_after integer, white_rd_before integer, white_rd_after integer, white_score_before integer, white_score_after integer, blue_id integer, blue_family_name text, blue_given_name text, blue_country text, blue_place_before bigint, blue_ippon integer, blue_waza integer, blue_yuko integer, blue_shido integer, blue_win_probability double precision, blue_rating_before integer, blue_rating_after integer, blue_rd_before integer, blue_rd_after integer, blue_score_before integer, blue_score_after integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- Place: in the weight's table the day before the contest. No rating rows for
    -- a contest that was not fought (bye, not decided yet).
    select ct.id,
           cm.id,
           cm.name::text,
           cm.rank_name::text,
           cm.city::text,
           coalesce(white_rc.fought_on, ct.started_at::date, cm.date_from),
           ct.weight::text,
           ct.round_name::text,
           ct.duration::text,
           ct.golden_score,
           ct.winner_id,
           ct.white_id,
           white_a.family_name::text,
           white_a.given_name::text,
           white_co.ioc::text,
           (select b.place
            from ajr.board_at(white_rc.weight, white_rc.fought_on - 1) b
            where b.athlete_id = ct.white_id),
           ct.ippon_w,
           ct.waza_w,
           ct.yuko_w,
           ct.penalty_w,
           white_rc.win_probability,
           round(white_rc.rating_before)::integer,
           round(white_rc.rating_after)::integer,
           round(white_rc.rd_before)::integer,
           round(white_rc.rd_after)::integer,
           round(white_rc.rating_before - s.rd_factor * white_rc.rd_before)::integer,
           round(white_rc.rating_after - s.rd_factor * white_rc.rd_after)::integer,
           ct.blue_id,
           blue_a.family_name::text,
           blue_a.given_name::text,
           blue_co.ioc::text,
           (select b.place
            from ajr.board_at(blue_rc.weight, blue_rc.fought_on - 1) b
            where b.athlete_id = ct.blue_id),
           ct.ippon_b,
           ct.waza_b,
           ct.yuko_b,
           ct.penalty_b,
           blue_rc.win_probability,
           round(blue_rc.rating_before)::integer,
           round(blue_rc.rating_after)::integer,
           round(blue_rc.rd_before)::integer,
           round(blue_rc.rd_after)::integer,
           round(blue_rc.rating_before - s.rd_factor * blue_rc.rd_before)::integer,
           round(blue_rc.rating_after - s.rd_factor * blue_rc.rd_after)::integer
    from ajr.contest ct
    join ajr.competition cm on cm.id = ct.competition_id
    cross join ajr.rating_settings s
    left join ajr.athlete white_a on white_a.id = ct.white_id
    left join ajr.country white_co on white_co.id = white_a.country_id
    left join ajr.rating_change white_rc
        on white_rc.contest_id = ct.id and white_rc.athlete_id = ct.white_id
    left join ajr.athlete blue_a on blue_a.id = ct.blue_id
    left join ajr.country blue_co on blue_co.id = blue_a.country_id
    left join ajr.rating_change blue_rc
        on blue_rc.contest_id = ct.id and blue_rc.athlete_id = ct.blue_id
    where ct.id = contest.contest_id
$function$
"""

COMPETITION_CONTESTS = """
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

OLD_COMPETITION_CONTESTS = """
create or replace function api.competition_contests(competition_id integer, only_weight text DEFAULT NULL::text)
 RETURNS TABLE(contest_id integer, weight text, round text, winner_id integer, white_id integer, white_family_name text, white_given_name text, white_country text, white_chance double precision, white_score_before integer, white_score_after integer, blue_id integer, blue_family_name text, blue_given_name text, blue_country text, blue_chance double precision, blue_score_before integer, blue_score_after integer, real_fight boolean)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- Decided contests, by weight, from the final back to the first round.
    -- real_fight: not a bye, not a 0:00 walkover.
    select ct.id, ct.weight::text, ct.round_name::text, ct.winner_id,
           ct.white_id, w.family_name::text, w.given_name::text, wc.ioc::text,
           wr.win_probability,
           round(wr.rating_before - s.rd_factor * wr.rd_before)::integer,
           round(wr.rating_after - s.rd_factor * wr.rd_after)::integer,
           ct.blue_id, b.family_name::text, b.given_name::text, bc.ioc::text,
           br.win_probability,
           round(br.rating_before - s.rd_factor * br.rd_before)::integer,
           round(br.rating_after - s.rd_factor * br.rd_after)::integer,
           not coalesce(ct.bye, false) and ct.duration is distinct from '00:00:00'
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
    order by coalesce(array_position(array['-60', '-66', '-73', '-81', '-90', '-100', '+100', '-48', '-52', '-57', '-63', '-70', '-78', '+78'], ct.weight), 100), ct.weight, ct.round nulls last, ct.fight_no
$function$
"""


def contest(sql: str) -> None:
    op.execute("drop function api.contest(integer)")
    op.execute(sql)
    op.execute("revoke execute on function api.contest(integer) from public")
    op.execute("grant execute on function api.contest(integer) to anon, authenticated")


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("alter table ajr.rating_settings add column real_fights_only boolean")
    contest(CONTEST)
    op.execute(COMPETITION_CONTESTS)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(OLD_COMPETITION_CONTESTS)
    contest(OLD_CONTEST)
    op.execute("alter table ajr.rating_settings drop column real_fights_only")
