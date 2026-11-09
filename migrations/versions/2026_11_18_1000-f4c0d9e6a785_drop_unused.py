"""drop unused

ajr.olympic_cycle and competition.olympic_cycle_id (with its index): written by the
sync every run since the first migration, read by nothing (no SQL function, no page).
wrl_ranking.points: synced, never shown (the tables show the IJF place only).
docs/audits/2026-11-08-dead-code-debt.md, 4.1 and 4.3.

Revision ID: f4c0d9e6a785
Revises: e3b9c8d5f674
Create Date: 2026-11-18 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4c0d9e6a785"
down_revision: Union[str, Sequence[str], None] = "e3b9c8d5f674"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("alter table ajr.competition drop column olympic_cycle_id")  # its index and key too
    op.execute("drop table ajr.olympic_cycle")
    op.execute("alter table ajr.wrl_ranking drop column points")


def downgrade() -> None:
    """Downgrade schema. The values come back with the next sync."""
    op.execute("alter table ajr.wrl_ranking add column points integer not null default 0")
    op.execute(
        "create table ajr.olympic_cycle ("
        " id integer primary key,"
        " name varchar not null,"
        " date_from date not null,"
        " date_to date not null)"
    )
    op.execute(
        "alter table ajr.competition add column olympic_cycle_id integer"
        " references ajr.olympic_cycle (id)"
    )
    op.execute(
        "create index ix_ajr_competition_olympic_cycle_id on ajr.competition (olympic_cycle_id)"
    )
