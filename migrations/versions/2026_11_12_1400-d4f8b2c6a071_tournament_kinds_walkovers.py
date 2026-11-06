"""tournament kinds walkovers

What the rating will count, kept by the sync (nothing reads it yet: the rating
switches in a later release, with a full recompute):

- ajr.competition.kind: individual, team, age_group, kata, para, camp or military,
  from judobase's flags, age groups, status, code and name (ajr/sync/kinds.py;
  docs/audits/2026-11-06-tournaments.md), with judobase's ages and status. The sync
  writes them on every run; until its first run every competition is "individual".
- ajr.contest_walkover: the decided contests that were walkovers, not fights, as the
  sync finds them from each competition's contests and their events
  (ajr/sync/walkovers.py; docs/audits/2026-11-06-real-fights.md). A 0:00 contest is
  mostly a fight whose time was lost; filled as the sync fetches each competition
  again (the next full sync for all).

New columns of ajr.competition only (1,085 rows), not of ajr.contest, so the publish
does not resend the contests.

Revision ID: d4f8b2c6a071
Revises: c8e2a6f4b159
Create Date: 2026-11-12 14:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4f8b2c6a071"
down_revision: Union[str, Sequence[str], None] = "c8e2a6f4b159"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "alter table ajr.competition add column ages text[], add column status varchar, "
        "add column kind text not null default 'individual'"
    )
    op.execute(
        "create table ajr.contest_walkover ("
        " contest_id integer primary key references ajr.contest (id) on delete cascade,"
        " reason text not null)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop table ajr.contest_walkover")
    op.execute(
        "alter table ajr.competition drop column ages, drop column status, drop column kind"
    )
