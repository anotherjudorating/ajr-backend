"""listing by the majors

An athlete with no weight of 3 tournaments in a year (one who fights rarely) stood in
the table of their latest contest's weight: a world champion's one Grand Prix in the
next weight up moved them there for weeks, out of their own. Now that fallback is the
weight of their latest Olympics, Worlds or continental championships in the year, else
the weight of most tournaments (ajr/rating/ranking.py). A setting of its own, so the
next rating run is a full one (every row's listing again) and the tables in R2 a new
version.

Revision ID: b9f5d3a7c128
Revises: a8e4c2f6b917
Create Date: 2026-11-25 16:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b9f5d3a7c128"
down_revision: Union[str, Sequence[str], None] = "a8e4c2f6b917"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("alter table ajr.rating_settings add column listing_majors boolean")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("alter table ajr.rating_settings drop column listing_majors")
