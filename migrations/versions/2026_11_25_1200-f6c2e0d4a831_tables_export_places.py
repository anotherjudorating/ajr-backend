"""places on the next run, nations from the tables

The tables job wrote the athletes' places only on a run with a day to compute (a new
Monday, or days made stale): after the release that brought them nothing was written
until the next Monday. ajr.tables_export now says for which version the places files
were written (none yet: on the next run, every week until then at once).

The nations' weeks come from the same tables now (the mixed nations table of every
Monday, ajr/tables), and a nation's 90 days and 6 months in the snapshot from that
table of the week (ajr/rating/snapshot.py): ajr.nation_history, the records job's
weekly nations ranking, goes.

Revision ID: f6c2e0d4a831
Revises: e5b1d9c3f720
Create Date: 2026-11-25 12:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6c2e0d4a831"
down_revision: Union[str, Sequence[str], None] = "e5b1d9c3f720"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("alter table ajr.tables_export add column places_version text")
    op.execute("drop table ajr.nation_history")
    op.execute("drop table if exists published.nation_history")


def downgrade() -> None:
    """Downgrade schema (the records job of that version fills the table again)."""
    op.execute(
        """
        create table ajr.nation_history (
            day date not null,
            country_id integer not null references ajr.country (id),
            place integer not null,
            rating integer not null,
            primary key (day, country_id)
        )
        """
    )
    op.execute(
        "create index ix_nation_history_country_id_day on ajr.nation_history "
        "(country_id, day) include (place, rating)"
    )
    op.execute("alter table ajr.tables_export drop column places_version")
