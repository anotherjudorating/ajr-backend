"""nations' history in R2

ajr.nation_history (every week's mixed nations ranking, 131 thousand rows, 28 MB) was
published to production for one function, api.country_history (the country page's
chart). The tables job now puts a file per nation in R2 (places/<version>/nations/,
ajr/tables), as it does the athletes' places, and the table stays in the working copy
only (ajr/publish NOT_PUBLISHED): the rating's snapshot reads it there (a nation's 90
days and 6 months).

Production's rows go (the working copy is the one with the `published` schema: its
rows stay, its copy of what production had goes).

Revision ID: e5b1d9c3f720
Revises: c4a0e2b8d397
Create Date: 2026-11-25 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5b1d9c3f720"
down_revision: Union[str, Sequence[str], None] = "c4a0e2b8d397"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COUNTRY_HISTORY = """
create function api.country_history(ioc text)
returns table (day date, place integer, rating integer)
language sql stable security definer
set search_path = ''
as $$
    select h.day, h.place, h.rating
    from ajr.nation_history h
    join ajr.country co on co.id = h.country_id
    where co.ioc = country_history.ioc
    order by h.day
$$
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("drop function api.country_history(text)")
    op.execute(
        """
        do $$ begin
            if to_regnamespace('published') is null then
                truncate ajr.nation_history;
            end if;
        end $$
        """
    )
    op.execute("drop table if exists published.nation_history")


def downgrade() -> None:
    """Downgrade schema (production's rows come back with the next publish, once
    nation_history is published again)."""
    op.execute(COUNTRY_HISTORY)
    op.execute("revoke execute on function api.country_history(text) from public")
    op.execute("grant execute on function api.country_history(text) to anon, authenticated")
