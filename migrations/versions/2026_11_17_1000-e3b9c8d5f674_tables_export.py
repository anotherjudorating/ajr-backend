"""tables export

ajr.tables_export: the state of the past days' tables in R2 (ajr/tables,
docs/audits/2026-11-08-r2-tables-plan.md) — from which day the files are stale (the
rating job sets pending_from to the day it rated from), and what the bucket's manifest
holds (version, last day) after the last upload. One row; published with the rest, so
a working copy restored from production knows it too.

Revision ID: e3b9c8d5f674
Revises: d2a8b7c4e563
Create Date: 2026-11-17 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3b9c8d5f674"
down_revision: Union[str, Sequence[str], None] = "d2a8b7c4e563"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "create table ajr.tables_export ("
        " id integer primary key check (id = 1),"
        " pending_from date,"
        " version text,"
        " last_day date,"
        " updated_at timestamptz not null default now())"
    )
    op.execute("insert into ajr.tables_export (id) values (1)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop table ajr.tables_export")
