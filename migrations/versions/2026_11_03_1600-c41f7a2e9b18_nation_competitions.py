"""nation competitions

ajr.nation_competition: per nation and tournament, its athletes there and their
medals (ajr.result_label: only in brackets with one final). Built by the rating
job (ajr/rating/snapshot.py). api.country_tournaments read the whole contest
history of a nation's athletes per request: for a big nation tens of thousands of
rows, and when they are not in the database's cache, past the Data API's limit.
Now it reads the nation's latest rows here.

Revision ID: c41f7a2e9b18
Revises: 8b3e61f0c2d7
Create Date: 2026-11-03 16:00:00

"""

import importlib.util
from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c41f7a2e9b18"
down_revision: Union[str, Sequence[str], None] = "8b3e61f0c2d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = """
create table ajr.nation_competition (
    country_id integer not null references ajr.country (id),
    competition_id integer not null references ajr.competition (id),
    athletes integer not null,
    gold integer not null,
    silver integer not null,
    bronze integer not null,
    primary key (country_id, competition_id)
)
"""

COUNTRY_TOURNAMENTS = """
create or replace function api.country_tournaments(ioc text, top integer default 10)
returns table (
    id integer,
    name text,
    rank_name text,
    date_from date,
    athletes integer,
    gold integer,
    silver integer,
    bronze integer
)
language sql stable security definer
set search_path = ''
as $$
    select cm.id, cm.name::text, cm.rank_name::text, cm.date_from,
           n.athletes, n.gold, n.silver, n.bronze
    from ajr.country co
    join ajr.nation_competition n on n.country_id = co.id
    join ajr.competition cm on cm.id = n.competition_id
    where co.ioc = country_tournaments.ioc
    order by cm.date_from desc, cm.id
    limit country_tournaments.top
$$
"""


def load_migration(name: str):
    """An earlier migration's module, to reuse its SQL."""
    path = next(Path(__file__).parent.glob(f"*{name}.py"))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(TABLE)
    op.execute(COUNTRY_TOURNAMENTS)


def downgrade() -> None:
    """Downgrade schema."""
    previous = load_migration("5d1c2b7e9a40_country").COUNTRY_TOURNAMENTS
    op.execute(previous.replace("create function", "create or replace function"))
    op.execute("drop table ajr.nation_competition")
