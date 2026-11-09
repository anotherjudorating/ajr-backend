"""athlete history rank

api.athlete_history also returns the tournament's level (competition.rank_name, as
competition_rank), for the medal table of the athlete page: medals by level, each
level's tournaments with the athlete's result. The function already joins the
competition: one more column, no more reads. A new column changes the function's
result type, so it is dropped and created again.

Revision ID: a5d1e7f2b896
Revises: f4c0d9e6a785
Create Date: 2026-11-19 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a5d1e7f2b896"
down_revision: Union[str, Sequence[str], None] = "f4c0d9e6a785"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SIGNATURE = "api.athlete_history(integer, text)"

ATHLETE_HISTORY = """
create or replace function api.athlete_history(athlete_id integer, only_weight text DEFAULT NULL::text)
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

OLD_ATHLETE_HISTORY = """
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

def replace(definition: str) -> None:
    op.execute(f"drop function {SIGNATURE}")
    op.execute(definition)
    op.execute(f"revoke execute on function {SIGNATURE} from public")
    op.execute(f"grant execute on function {SIGNATURE} to anon, authenticated")


def upgrade() -> None:
    """Upgrade schema."""
    replace(ATHLETE_HISTORY)


def downgrade() -> None:
    """Downgrade schema."""
    replace(OLD_ATHLETE_HISTORY)
