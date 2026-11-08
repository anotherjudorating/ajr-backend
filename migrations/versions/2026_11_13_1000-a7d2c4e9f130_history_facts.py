"""history facts

The athlete's page read the whole history scattered over the database: for each of a
long career's ~400 contests its own rating row, the opponent's row of the contest,
the contest, the tournament, the opponent and their nation, the tournament result —
about 5,000 pages on a copy of production, seconds on Supabase Nano when they are not
in its cache (docs/audits/2026-11-08-site-load.md). The rating job now writes these
facts once (docs/audits/2026-11-08-b1-plan.md):

- ajr.rating_change: the contest's tournament, round, number and round name, the
  opponent's rating and RD before it, their name and nation, and how the athlete ended
  the tournament (ajr/rating/snapshot.py, HISTORY_FACTS). The publish builds the table
  anew in athlete order when its columns change (ajr/publish, SWAP_ORDER), so an
  athlete's rows sit on a few pages.
- ajr.athlete_summary: what api.athlete computed per request — rating, RD and score on
  the day of the run, their change over 90 days and 6 months, the places gained, the
  place on the day of the peak, the IJF place.
- ajr.nation_summary: every nation with a rated athlete, how many, how many in a table
  today (api.nations read athlete_summary and athlete whole).
- indexes for api.last_update and api.sitemap.

The columns are empty until the next rating run fills them and the publish after it
sends rating_change whole (in athlete order); the functions switch to them in the next
migration.

Revision ID: a7d2c4e9f130
Revises: e6c3a9d1f458
Create Date: 2026-11-13 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7d2c4e9f130"
down_revision: Union[str, Sequence[str], None] = "e6c3a9d1f458"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HISTORY_COLUMNS = [
    ("competition_id", "integer"),
    ("round", "integer"),
    ("fight_no", "integer"),
    ("round_name", "text"),
    ("opponent_rating_before", "double precision"),
    ("opponent_rd_before", "double precision"),
    ("opponent_family_name", "text"),
    ("opponent_given_name", "text"),
    ("opponent_country", "text"),
    ("result", "text"),
]
SUMMARY_COLUMNS = [
    ("rating", "integer"),
    ("rd", "integer"),
    ("score_today", "integer"),
    ("score_change_90d", "integer"),
    ("score_change_6m", "integer"),
    ("places_up_90d", "integer"),
    ("places_up_6m", "integer"),
    ("peak_place", "integer"),
    ("wrl_place", "integer"),
]


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "alter table ajr.rating_change "
        + ", ".join(f"add column {name} {kind}" for name, kind in HISTORY_COLUMNS)
    )
    op.execute(
        "alter table ajr.athlete_summary "
        + ", ".join(f"add column {name} {kind}" for name, kind in SUMMARY_COLUMNS)
    )
    op.execute(
        "create table ajr.nation_summary ("
        " country_id integer primary key references ajr.country (id),"
        " country text not null, name text,"
        " athletes integer not null, active integer not null)"
    )
    op.execute(
        "create index ix_job_run_last_rating on ajr.job_run (finished_at desc) "
        "where type = 'rating' and status = 'success'"
    )
    op.execute(
        "create index ix_athlete_summary_sitemap on ajr.athlete_summary (athlete_id) "
        "include (last_contest, contests)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop index ajr.ix_athlete_summary_sitemap")
    op.execute("drop index ajr.ix_job_run_last_rating")
    op.execute("drop table ajr.nation_summary")
    op.execute(
        "alter table ajr.athlete_summary "
        + ", ".join(f"drop column {name}" for name, _ in SUMMARY_COLUMNS)
    )
    op.execute(
        "alter table ajr.rating_change "
        + ", ".join(f"drop column {name}" for name, _ in HISTORY_COLUMNS)
    )
