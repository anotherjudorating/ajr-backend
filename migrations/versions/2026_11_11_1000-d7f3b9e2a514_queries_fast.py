"""queries fast

Indexes that let the site's calls read what they answer and not the rows around it
(docs/audits/2026-11-05-queries.md, F1, F5, F6). Same rows, except where a tie now
has a fixed order.

- ajr.board_at (a weight's table on a day; the contest page twice, the athlete's
  peak place, every past day's table) read each candidate row of the weight's recent
  contests from the table before keeping one in seven: about 3,000 pages for one
  table on production, whose rows lie in no order. The index on (weight, fought_on)
  now carries the columns board_at reads, so it answers from the index alone: about
  30 pages. It replaces the plain one.
- The home page: api.home_leaders and api.biggest_movers read the whole snapshot
  (5,400 rows) for the top places, now an index on the place; api.upcoming walked the
  tournaments from 2009 on, now from a month ago (none lasts longer).
- The country page's history (api.country_history) read one page per week of the
  nation's history, which is stored by day: an index on (country, day) carrying the
  place and rating, replacing the plain one.
- A tournament's results (api.competition_results) read one page per athlete, the
  rows being stored by athlete: an index on the competition carrying the columns,
  replacing the plain one.
- Ties: api.home_leaders and api.competition_results end their order with the
  athlete. ix_athlete_summary_weight is dropped (no call uses it).

An index answers alone only for the table's pages that VACUUM has marked visible;
autovacuum marks them again after a big publish.

Revision ID: d7f3b9e2a514
Revises: c5e2a8d1f379
Create Date: 2026-11-11 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7f3b9e2a514"
down_revision: Union[str, Sequence[str], None] = "c5e2a8d1f379"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (new index, the one it replaces or None, the replaced one's definition)
INDEXES = [
    (
        "create index ix_rating_change_weight_fought_on_board on ajr.rating_change "
        "(weight, fought_on) include (next_fought_on, athlete_id, rating_after, rd_after)",
        "ajr.ix_rating_change_weight_fought_on",
        "create index ix_rating_change_weight_fought_on on ajr.rating_change (weight, fought_on)",
    ),
    (
        "create index ix_leaderboard_snapshot_place on ajr.leaderboard_snapshot (place)",
        None,
        None,
    ),
    (
        "create index ix_nation_history_country_id_day on ajr.nation_history "
        "(country_id, day) include (place, rating)",
        "ajr.ix_nation_history_country_id",
        "create index ix_nation_history_country_id on ajr.nation_history (country_id, day)",
    ),
    (
        "create index ix_athlete_competition_competition_results on ajr.athlete_competition "
        "(competition_id) include (athlete_id, weight, result, score_before, score_after, "
        "contests, wins, contests_before)",
        "ajr.ix_athlete_competition_competition",
        "create index ix_athlete_competition_competition on ajr.athlete_competition "
        "(competition_id)",
    ),
]

DROPPED = "create index ix_athlete_summary_weight on ajr.athlete_summary (weight)"


def load_migration(name: str):
    """An earlier migration's module, to reuse its SQL."""
    import importlib.util
    from pathlib import Path

    path = next(Path(__file__).parent.glob(f"*{name}.py"))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rewrite(sql: str, *changes: tuple[str, str]) -> str:
    """An earlier function's SQL as a replacement, with the given changes."""
    sql = sql.replace("create function", "create or replace function")
    for old, new in changes:
        assert old in sql, old
        sql = sql.replace(old, new)
    return sql


def functions() -> list[tuple[str, str]]:
    """(the new SQL, the old SQL) of each changed function."""
    home = load_migration("e7a9d3c15f62_home")
    results = load_migration("f6a1d3b8c927_athlete_competitions_api")
    old = [
        rewrite(home.HOME_LEADERS),
        rewrite(home.UPCOMING),
        results.COMPETITION_RESULTS,
    ]
    new = [
        rewrite(
            home.HOME_LEADERS,
            (', l.place\n$$', ", l.place, l.athlete_id\n$$"),
        ),
        rewrite(
            home.UPCOMING,
            (
                "    where coalesce(cm.date_to, cm.date_from) >= current_date\n",
                "    where coalesce(cm.date_to, cm.date_from) >= current_date\n"
                "      -- none lasts a month: the index on the start stops there\n"
                "      and cm.date_from >= current_date - 30\n",
            ),
        ),
        rewrite(
            results.COMPETITION_RESULTS,
            (
                "             r.score_after desc\n",
                "             r.score_after desc, r.athlete_id\n",
            ),
        ),
    ]
    return list(zip(new, old, strict=True))


def upgrade() -> None:
    """Upgrade schema."""
    for create, replaced, _ in INDEXES:
        op.execute(create)
        if replaced:
            op.execute(f"drop index {replaced}")
    op.execute("drop index ajr.ix_athlete_summary_weight")
    for sql, _ in functions():
        op.execute(sql)


def downgrade() -> None:
    """Downgrade schema."""
    for _, sql in functions():
        op.execute(sql)
    op.execute(DROPPED)
    for create, _, definition in reversed(INDEXES):
        if definition:
            op.execute(definition)
        op.execute(f"drop index ajr.{create.split()[2]}")
