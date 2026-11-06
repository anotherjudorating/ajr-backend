"""move handicap

A setting of the rating: on a change of weight category, the athlete's rating moves
by move_handicap (a share of it), down when moving to a heavier weight and up when
moving to a lighter one (ajr/rating/engine.py; docs/audits/2026-11-06-weight-ratings.md).
The row the job saved has none, so the next rating run sees the settings changed and
rates everything again.

Revision ID: a3c9e5f2d817
Revises: f1b7d4a9c362
Create Date: 2026-11-12 11:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3c9e5f2d817"
down_revision: Union[str, Sequence[str], None] = "f1b7d4a9c362"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("alter table ajr.rating_settings add column move_handicap double precision")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("alter table ajr.rating_settings drop column move_handicap")
