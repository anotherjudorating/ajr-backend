"""athlete peak weight

api.athlete also returns the weight of the athlete's peak (athlete_summary.peak_weight),
so the site can link the peak to that weight's table on that day. A new column changes
the function's result type: dropped and created again.

Revision ID: c7a3e9f1d208
Revises: b6e2f8a3c907
Create Date: 2026-11-21 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7a3e9f1d208"
down_revision: Union[str, Sequence[str], None] = "b6e2f8a3c907"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SIGNATURE = "api.athlete(integer)"

ATHLETE = """
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

OLD_ATHLETE = """
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
