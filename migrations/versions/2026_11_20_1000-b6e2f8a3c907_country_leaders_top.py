"""country leaders top

api.country_leaders returns the nation's best five in every weight today (it was the
best one), for the country page's weight picker: "All weights" shows the first of
each weight, a weight its five. Same columns, same index
(ix_leaderboard_snapshot_country_leaders); at most 70 rows. The first row of a weight
is the old answer, so the site before this change reads it as before.

Revision ID: b6e2f8a3c907
Revises: a5d1e7f2b896
Create Date: 2026-11-20 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6e2f8a3c907"
down_revision: Union[str, Sequence[str], None] = "a5d1e7f2b896"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WEIGHT_ORDER = (
    "array['-60', '-66', '-73', '-81', '-90', '-100', '+100', "
    "'-48', '-52', '-57', '-63', '-70', '-78', '+78']"
)

COUNTRY_LEADERS = f"""
create or replace function api.country_leaders(ioc text)
 RETURNS TABLE(weight text, athlete_id integer, family_name text, given_name text, place integer, score integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
    -- The nation's best five in every weight today, best first (a tie in score goes
    -- to the better place), weights in the site's order:
    -- ix_leaderboard_snapshot_country_leaders alone.
    select b.weight, b.athlete_id, b.family_name, b.given_name, b.place, b.score
    from (
        select l.weight::text, l.athlete_id, l.family_name::text, l.given_name::text,
               l.place::integer, l.score::integer,
               row_number() over (partition by l.weight order by l.score desc, l.place) as n
        from ajr.leaderboard_snapshot l
        where l.country = country_leaders.ioc
    ) b
    where b.n <= 5
    order by coalesce(array_position({WEIGHT_ORDER}, b.weight), 100), b.n
$function$
"""

OLD_COUNTRY_LEADERS = f"""
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
    order by coalesce(array_position({WEIGHT_ORDER}, b.weight), 100)
$function$
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(COUNTRY_LEADERS)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(OLD_COUNTRY_LEADERS)
