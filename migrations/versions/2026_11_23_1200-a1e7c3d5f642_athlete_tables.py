"""athlete tables

api.athlete also returns every table that lists the athlete today (`tables`: the
weight, the place, the places gained in 90 days and 6 months, the IJF place), from
ajr.leaderboard_snapshot: the page's weight tabs show the picked weight's place and
changes in the header, not only the listing weight's. A new column changes the
function's result type: dropped and created again.

Revision ID: a1e7c3d5f642
Revises: f2d6b8c4e531
Create Date: 2026-11-23 12:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1e7c3d5f642"
down_revision: Union[str, Sequence[str], None] = "f2d6b8c4e531"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SIGNATURE = "api.athlete(integer)"

ATHLETE = """
create or replace function api.athlete(athlete_id integer)
 RETURNS TABLE(id integer, family_name text, given_name text, gender text, birth_year integer, country text, country_name text, weight text, rating integer, rd integer, score integer, place bigint, last_contest date, contests bigint, wrl_place integer, weights text[], peak_score integer, peak_on date, peak_place bigint, peak_weight text, score_change_90d integer, score_change_6m integer, places_up_90d integer, places_up_6m integer, tables jsonb)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- Everything but the athlete's own row comes from ajr.athlete_summary, which the
    -- rating job fills on every run (ajr/rating/snapshot.py): rating, RD and score on
    -- the day of the run, the place (null when hidden: a year without contests), the
    -- changes over 90 days and 6 months, the peak, the place on its day and its weight
    -- (the site links the peak to that weight's table on that day).
    -- weights: the categories fought in, the latest first.
    -- tables: every table listing the athlete today (one, or two when they fight in
    -- two weights: ajr/rating/ranking.py), with the place, the places gained in 90
    -- days and 6 months and the IJF place in that weight: the weight tabs of the page
    -- show the picked weight's.
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
           sm.peak_weight::text,
           sm.score_change_90d,
           sm.score_change_6m,
           sm.places_up_90d,
           sm.places_up_6m,
           (select coalesce(jsonb_agg(jsonb_build_object(
                       'weight', ls.weight, 'place', ls.place,
                       'places_up_90d', ls.places_up_90d, 'places_up_6m', ls.places_up_6m,
                       'wrl_place', ls.wrl_place) order by ls.place), '[]')
            from ajr.leaderboard_snapshot ls
            where ls.athlete_id = a.id)
    from ajr.athlete a
    left join ajr.country co on co.id = a.country_id
    left join ajr.athlete_summary sm on sm.athlete_id = a.id
    where a.id = athlete.athlete_id
$function$
"""

OLD_ATHLETE = """
create or replace function api.athlete(athlete_id integer)
 RETURNS TABLE(id integer, family_name text, given_name text, gender text, birth_year integer, country text, country_name text, weight text, rating integer, rd integer, score integer, place bigint, last_contest date, contests bigint, wrl_place integer, weights text[], peak_score integer, peak_on date, peak_place bigint, peak_weight text, score_change_90d integer, score_change_6m integer, places_up_90d integer, places_up_6m integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- Everything but the athlete's own row comes from ajr.athlete_summary, which the
    -- rating job fills on every run (ajr/rating/snapshot.py): rating, RD and score on
    -- the day of the run, the place (null when hidden: a year without contests), the
    -- changes over 90 days and 6 months, the peak, the place on its day and its weight
    -- (the site links the peak to that weight's table on that day).
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
           sm.peak_weight::text,
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


def replace(definition: str) -> None:
    op.execute(f"drop function {SIGNATURE}")
    op.execute(definition)
    op.execute(f"revoke execute on function {SIGNATURE} from public")
    op.execute(f"grant execute on function {SIGNATURE} to anon, authenticated")


def upgrade() -> None:
    """Upgrade schema."""
    replace(ATHLETE)


def downgrade() -> None:
    """Downgrade schema."""
    replace(OLD_ATHLETE)
