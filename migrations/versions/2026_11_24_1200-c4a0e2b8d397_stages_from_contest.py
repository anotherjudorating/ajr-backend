"""stages read from the contest

The round stages (b3f9d1a7c286) were copied into every rating_change row: the first
publish after the release sent all 452 thousand rows again, with the whole contest
table, and the production database ran out of disk. The history keeps judobase's round
name; api.athlete_history and api.contest_context read the stage from the contest
(one lookup by its key a row).

Revision ID: c4a0e2b8d397
Revises: b3f9d1a7c286
Create Date: 2026-11-24 12:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4a0e2b8d397"
down_revision: Union[str, Sequence[str], None] = "b3f9d1a7c286"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ATHLETE_HISTORY = """
CREATE OR REPLACE FUNCTION api.athlete_history(athlete_id integer, only_weight text DEFAULT NULL::text)
 RETURNS TABLE(contest_id integer, fought_on date, competition_id integer, competition text, competition_rank text, round text, weight text, opponent_id integer, opponent_family_name text, opponent_given_name text, opponent_country text, won boolean, win_probability double precision, rating_before integer, rating_after integer, rd_after integer, rd_before integer, score_before integer, score_after integer, opponent_score integer, result text)
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
           cm.rank_name::text,
           coalesce(ct.stage, rc.round_name),  -- the stage (ajr.fill_stages)
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
    left join ajr.contest ct on ct.id = rc.contest_id
    where rc.athlete_id = athlete_history.athlete_id
      and (athlete_history.only_weight is null or rc.weight = athlete_history.only_weight)
    order by rc.fought_on desc, rc.round nulls last, rc.fight_no desc, rc.contest_id desc
$function$
"""

CONTEST_CONTEXT = """
CREATE OR REPLACE FUNCTION api.contest_context(contest_id integer)
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
           coalesce(ct.stage, rc.round_name),  -- the stage (ajr.fill_stages)
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
    left join ajr.contest ct on ct.id = rc.contest_id
    order by p.side desc, p.kind desc, rc.fought_on desc, rc.round nulls last,
             rc.fight_no desc, rc.contest_id desc
$function$
"""

OLD_ATHLETE_HISTORY = """
CREATE OR REPLACE FUNCTION api.athlete_history(athlete_id integer, only_weight text DEFAULT NULL::text)
 RETURNS TABLE(contest_id integer, fought_on date, competition_id integer, competition text, competition_rank text, round text, weight text, opponent_id integer, opponent_family_name text, opponent_given_name text, opponent_country text, won boolean, win_probability double precision, rating_before integer, rating_after integer, rd_after integer, rd_before integer, score_before integer, score_after integer, opponent_score integer, result text)
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
           cm.rank_name::text,
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

OLD_CONTEST_CONTEXT = """
CREATE OR REPLACE FUNCTION api.contest_context(contest_id integer)
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


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(ATHLETE_HISTORY)
    op.execute(CONTEST_CONTEXT)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(OLD_ATHLETE_HISTORY)
    op.execute(OLD_CONTEST_CONTEXT)
