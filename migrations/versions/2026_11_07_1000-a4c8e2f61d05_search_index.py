"""search index

api.search_index(): everything the site's search boxes look in, as one JSON
document, so the browser searches itself: a search no longer reaches the
database (each was a pass over every athlete; under load they took the small
instance's few connections from the pages). The site serves it from its cache
and the CDN, refreshed with the data.

The Data API returns at most 1000 rows; one document is one row. Lists of arrays
keep it small (about 1 MB, a third of that compressed), each list in the order
the search shows it:

- athletes: [id, family name, given name, IOC, gender, weight, place, score] —
  rated athletes, those in a table today first by score, then the latest to fight
  (as api.search);
- tournaments: [id, name, IOC, first day, last day] — individual ones with
  contests and the coming World Tour ones, the coming ones first, the soonest
  first, then the latest;
- nations: [IOC, name] — with rated athletes, the most athletes first.

Revision ID: a4c8e2f61d05
Revises: 71f3c9a0b5e8
Create Date: 2026-11-07 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4c8e2f61d05"
down_revision: Union[str, Sequence[str], None] = "71f3c9a0b5e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEARCH_INDEX = """
create function api.search_index()
returns json
language sql stable security definer
set search_path = ''
as $$
    select json_build_object(
        'athletes', (
            select json_agg(json_build_array(a.id, a.family_name, a.given_name, co.ioc, a.gender,
                                             s.weight, s.place, s.score)
                            order by s.score desc nulls last, s.last_contest desc, a.id)
            from ajr.athlete_summary s
            join ajr.athlete a on a.id = s.athlete_id
            left join ajr.country co on co.id = a.country_id
        ),
        'tournaments', (
            select json_agg(json_build_array(cm.id, cm.name, co.ioc, cm.date_from, cm.date_to)
                            order by cm.date_from >= current_date desc,
                                     case when cm.date_from >= current_date then cm.date_from end,
                                     cm.date_from desc, cm.id)
            from ajr.competition cm
            left join ajr.country co on co.id = cm.country_id
            where not coalesce(cm.is_teams, false)
              and (exists (select from ajr.competition_stats st where st.competition_id = cm.id)
                   or (cm.date_from >= current_date
                       and cm.rank_name in ('Olympic Games', 'World Championships', 'Masters',
                                            'Grand Slam', 'Grand Prix')))
        ),
        'nations', (
            select json_agg(json_build_array(n.ioc, n.name) order by n.athletes desc, n.ioc)
            from (
                select co.ioc, co.name, count(*) as athletes
                from ajr.athlete_summary s
                join ajr.athlete a on a.id = s.athlete_id
                join ajr.country co on co.id = a.country_id
                where co.ioc is not null
                group by co.ioc, co.name
            ) n
        )
    )
$$
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(SEARCH_INDEX)
    op.execute("revoke execute on function api.search_index() from public")
    op.execute("grant execute on function api.search_index() to anon, authenticated")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop function api.search_index()")
