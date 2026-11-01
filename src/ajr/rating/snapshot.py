"""Today's tables of every weight, built ahead for the site.

A weight's full table (place and score changes, trend, IJF place, latest
competition: ajr.leaderboard_full) costs the database a few hundred milliseconds
of CPU, and the site asks for several at once; over the Data API that runs past
the 3-second limit. So the rating job builds today's tables on every run (also
when no result changed: names, IJF places or the day may have) into
ajr.leaderboard_snapshot, and api.leaderboard serves them from there.
"""

import logging

from sqlalchemy import text
from sqlmodel import Session

from ajr.rating.ranking import WEIGHTS

logger = logging.getLogger(__name__)

REBUILD = text("""
    insert into ajr.leaderboard_snapshot
    select w.weight, current_date, l.*
    from unnest(cast(:weights as text[])) w(weight)
    cross join lateral ajr.leaderboard_full(w.weight, current_date) l
""")


def refresh_snapshot(session: Session) -> None:
    """Replace the snapshot with today's tables (in the caller's transaction, so the
    site never sees it empty)."""
    session.execute(text("delete from ajr.leaderboard_snapshot"))
    rows = session.execute(REBUILD, {"weights": WEIGHTS}).rowcount
    logger.info("Leaderboard snapshot: %d rows", rows)
