"""athlete aliases

judobase opens a new profile when an athlete changes nations (and sometimes enters
one twice at a tournament, in a weight and in the open category), so one person has
two ids and two rating histories, the second starting from scratch.
ajr.athlete_alias names the second ids and the main one (the id fought under last);
the sync loads it from ajr/sync/data/athlete_aliases.csv (169 people checked by hand
on 2026-11-06), writes the main id in the contests instead of an alias, and marks
their competitions changed, so the next rating run rates each athlete as one.
Created empty here: the first sync after the release fills it.

api.canonical_athlete(athlete_id): the main id of an alias (null for any other id),
for the site to send an old athlete page to the main one.

Revision ID: f1b7d4a9c362
Revises: e8a4c1f6b293
Create Date: 2026-11-12 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1b7d4a9c362"
down_revision: Union[str, Sequence[str], None] = "e8a4c1f6b293"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ATHLETE_ALIAS = """
create table ajr.athlete_alias (
    alias_id integer primary key references ajr.athlete (id),
    athlete_id integer not null references ajr.athlete (id),
    check (alias_id <> athlete_id)
)
"""

CANONICAL_ATHLETE = """
create function api.canonical_athlete(athlete_id integer)
returns integer
language sql stable security definer
set search_path = ''
as $$
    select a.athlete_id from ajr.athlete_alias a where a.alias_id = canonical_athlete.athlete_id
$$
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(ATHLETE_ALIAS)
    op.execute(CANONICAL_ATHLETE)
    op.execute("revoke execute on function api.canonical_athlete(integer) from public")
    op.execute("grant execute on function api.canonical_athlete(integer) to anon, authenticated")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop function api.canonical_athlete(integer)")
    op.execute("drop table ajr.athlete_alias")
