"""round stages

judobase names the same stage of a draw differently: "Round 4" (counted from the
start), "Round of 16", "best 16" are the same 1/8 final, and the site showed R4, R16
or BES. ajr.contest.stage holds one code per contest, from the final: F, 1/2, 1/4,
1/8, 1/16, 1/32, 1/64, 1/128; BR (bronze), REP (repechage); R1, R2… for the tours of
a round robin or of pools; null when unknown ("?"). ajr.fill_stages sets it (here for
every contest, then the sync for the competitions it saves):

- an explicit name wins (Final, Semi-Final, Quarter-Final, Round of N, best N,
  Bronze, Repechage…): judobase's round number is wrong at some events;
- "Round N" in a knockout draw (one with a quarter- or semi-final, or a named
  Round of N) is the stage of its round number, which judobase counts down to the
  final (0 the final, 1 the semi-finals, 2 the quarter-finals, 3 the 1/8…);
- otherwise "Round N" is a tour (R{N}).

The rating job copies the stage where the round was copied (rating_change.round_name,
contest_list.round), ajr.result_label says where an athlete went out with it, and
api.contest returns it. The medals, 5th and 7th still come from judobase's names.

Revision ID: b3f9d1a7c286
Revises: a1e7c3d5f642
Create Date: 2026-11-24 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3f9d1a7c286"
down_revision: Union[str, Sequence[str], None] = "a1e7c3d5f642"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FILL_STAGES = """
create function ajr.fill_stages(only_competitions integer[] default null)
returns void
language sql
set search_path = ''
as $$
    with draw as (
        -- a knockout draw: its stages named somewhere
        select competition_id, weight,
               bool_or(round_name ~* '^(quarter|semi)[ -]?final$'
                       or round_name ~* '^(round of|best) [0-9]+$') as knockout
        from ajr.contest
        where only_competitions is null or competition_id = any(only_competitions)
        group by competition_id, weight
    ),
    named as (
        select ct.id, ct.round, d.knockout,
               btrim(regexp_replace(coalesce(ct.round_name, ''), '[^A-Za-z0-9 -]', '', 'g')) as name
        from ajr.contest ct
        join draw d on d.competition_id = ct.competition_id
                   and d.weight is not distinct from ct.weight
    ),
    staged as (
        select id,
               case
                   when name ~* '^final$' then 'F'
                   when name ~* '^semi[ -]?final$' then '1/2'
                   when name ~* '^quarter[ -]?final$' then '1/4'
                   when name ~* '^bronze' then 'BR'
                   when name ~* '^repechage' then 'REP'
                   when name ~* '^(round of|best) [0-9]+$'
                       then '1/' || (substring(name from '[0-9]+$')::integer / 2)
                   when name ~* '^round [0-9]+$' and knockout and round >= 3
                       then '1/' || power(2, round)::integer
                   when name ~* '^round [0-9]+$' then 'R' || substring(name from '[0-9]+$')
               end as stage
        from named
    )
    update ajr.contest ct
       set stage = s.stage
      from staged s
     where s.id = ct.id and ct.stage is distinct from s.stage
$$
"""

# Where an athlete went out: the medal, 5th, 7th from judobase's round names, else
# the stage of the last contest lost.
RESULT_LABEL = """
create function ajr.result_label(round_name text, won boolean, stage text)
returns text
language sql
immutable
as $$
    select case
               when round_name = 'Final' then case when won then 'gold' else 'silver' end
               when round_name = 'Bronze' then case when won then 'bronze' else '5th' end
               when won then null
               when round_name = 'Repechage' then '7th'
               else coalesce(stage, round_name)
           end
$$
"""

CONTEST = """
CREATE OR REPLACE FUNCTION api.contest(contest_id integer)
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
           ct.stage,  -- the stage, from the final (ajr.fill_stages)
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
CREATE OR REPLACE FUNCTION api.contest(contest_id integer)
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


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("alter table ajr.contest add column stage text")
    op.execute(FILL_STAGES)
    op.execute("select ajr.fill_stages()")
    # the contest list of the years no run rebuilds soon (the history and the
    # tournaments' results are rebuilt by every rating run)
    op.execute(
        "update ajr.contest_list l set round = ct.stage from ajr.contest ct"
        " where ct.id = l.contest_id and l.round is distinct from ct.stage"
    )
    op.execute(RESULT_LABEL)
    op.execute(CONTEST)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(OLD_CONTEST)
    op.execute("drop function ajr.result_label(text, boolean, text)")
    op.execute("drop function ajr.fill_stages(integer[])")
    op.execute("alter table ajr.contest drop column stage")
