"""athlete competitions

How each athlete did at each tournament, computed once by the rating job instead of
from the whole history on every request: ajr.athlete_competition, one row per
athlete, competition and weight category of the contests (an athlete in their
weight and in the open category has two): how they ended it (ajr.result_label of
their last contest; only in brackets with one final), their score before their first
contest and after their last, contests, wins, and their rated contests before it.
Contests without a weight category have no row (9, all at the Paralympic Games Tokyo
2020).

The rating job builds it (ajr/rating/snapshot.py), on its working copy, and builds
ajr.nation_competition from it; the next update run publishes it whole. Created
empty here: filling it is a pass over the whole history, too long for production.
The API reads it from the next migration on.

Revision ID: e4b9c2d7a815
Revises: c3e7a1f9d204
Create Date: 2026-11-09 11:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4b9c2d7a815"
down_revision: Union[str, Sequence[str], None] = "c3e7a1f9d204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ATHLETE_COMPETITION = """
create table ajr.athlete_competition (
    athlete_id integer not null references ajr.athlete (id),
    competition_id integer not null references ajr.competition (id),
    weight text not null, -- of the contests (judobase's), not the athlete's category
    result text,
    score_before integer not null,
    score_after integer not null,
    contests integer not null,
    wins integer not null,
    contests_before integer not null, -- the athlete's rated contests before this one
    primary key (athlete_id, competition_id, weight)
)
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(ATHLETE_COMPETITION)
    op.execute(
        "create index ix_athlete_competition_competition on ajr.athlete_competition (competition_id)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop table ajr.athlete_competition")
