"""sitemap

api.sitemap(): what the site's sitemap lists, as one JSON document (the Data API
returns at most 1000 rows; one document is one row), from the tables the rating job
keeps:

- athletes: [id, last contest, rated contests] — every rated athlete; the site
  decides which are worth indexing;
- tournaments: [id, last day] — those with rated contests;
- nations: [IOC] — with a rating.

Revision ID: a9d4e6f2b371
Revises: f6a1d3b8c927
Create Date: 2026-11-10 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9d4e6f2b371"
down_revision: Union[str, Sequence[str], None] = "f6a1d3b8c927"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SITEMAP = """
create function api.sitemap()
returns json
language sql stable security definer
set search_path = ''
as $$
    select json_build_object(
        'athletes', (
            select json_agg(json_build_array(s.athlete_id, s.last_contest, s.contests)
                            order by s.athlete_id)
            from ajr.athlete_summary s
        ),
        'tournaments', (
            select json_agg(json_build_array(cm.id, coalesce(cm.date_to, cm.date_from))
                            order by cm.id)
            from ajr.competition cm
            join ajr.competition_stats st on st.competition_id = cm.id
        ),
        'nations', (
            select json_agg(distinct co.ioc)
            from ajr.nation_snapshot n
            join ajr.country co on co.id = n.country_id
            where co.ioc is not null
        )
    )
$$
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(SITEMAP)
    op.execute("revoke execute on function api.sitemap() from public")
    op.execute("grant execute on function api.sitemap() to anon, authenticated")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop function api.sitemap()")
