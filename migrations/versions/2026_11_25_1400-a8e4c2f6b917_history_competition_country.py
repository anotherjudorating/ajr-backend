"""tournament's country in the athlete's history

The athlete page's results list each tournament with its country's flag, as the
tournaments' lists do: api.athlete_history gives the tournament's country (the
competition's, one lookup by its key a row).

Revision ID: a8e4c2f6b917
Revises: f6c2e0d4a831
Create Date: 2026-11-25 14:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8e4c2f6b917"
down_revision: Union[str, Sequence[str], None] = "f6c2e0d4a831"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SIGNATURE = "api.athlete_history(integer, text)"

ATHLETE_HISTORY = """
CREATE FUNCTION api.athlete_history(athlete_id integer, only_weight text DEFAULT NULL::text)
 RETURNS TABLE(contest_id integer, fought_on date, competition_id integer, competition text, competition_rank text, round text, weight text, opponent_id integer, opponent_family_name text, opponent_given_name text, opponent_country text, won boolean, win_probability double precision, rating_before integer, rating_after integer, rd_after integer, rd_before integer, score_before integer, score_after integer, opponent_score integer, result text, competition_country text)
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
    -- together; only the tournament's name and country are looked up.
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
           rc.result,
           co.ioc::text  -- the tournament's country
    from ajr.rating_change rc
    cross join ajr.rating_settings s
    join ajr.competition cm on cm.id = rc.competition_id
    left join ajr.country co on co.id = cm.country_id
    left join ajr.contest ct on ct.id = rc.contest_id
    where rc.athlete_id = athlete_history.athlete_id
      and (athlete_history.only_weight is null or rc.weight = athlete_history.only_weight)
    order by rc.fought_on desc, rc.round nulls last, rc.fight_no desc, rc.contest_id desc
$function$
"""

OLD_ATHLETE_HISTORY = """
CREATE FUNCTION api.athlete_history(athlete_id integer, only_weight text DEFAULT NULL::text)
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


def replace(sql: str) -> None:
    op.execute(f"drop function {SIGNATURE}")  # its columns change
    op.execute(sql)
    op.execute(f"revoke execute on function {SIGNATURE} from public")
    op.execute(f"grant execute on function {SIGNATURE} to anon, authenticated")


def upgrade() -> None:
    """Upgrade schema."""
    replace(ATHLETE_HISTORY)


def downgrade() -> None:
    """Downgrade schema."""
    replace(OLD_ATHLETE_HISTORY)
