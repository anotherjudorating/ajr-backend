"""What the site reads that would be too heavy to compute per request, built ahead:
today's tables of every weight and the summaries behind the Explore lists.

A weight's full table (place and score changes, trend, IJF place, latest
competition: ajr.leaderboard_full) costs the database a few hundred milliseconds
of CPU, and the site asks for several at once; over the Data API that runs past
the 3-second limit. So the rating job builds today's tables on every run (also
when no result changed: names, IJF places or the day may have) into
ajr.leaderboard_snapshot, and api.leaderboard serves them from there.

Likewise the Explore lists: ajr.competition_stats (per tournament: real fights,
how often the favourite won, upsets) and ajr.athlete_summary (per athlete: the
weight, the latest contest and tournament, today's place and score).
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


# Real fights only: no byes, no 0:00 walkovers. An upset: the winner's chance <= 35%.
COMPETITION_STATS = text("""
    insert into ajr.competition_stats (competition_id, contests, accuracy, upsets)
    select ct.competition_id,
           count(*),
           avg((rc.win_probability > 0.5)::int) filter (where rc.win_probability <> 0.5),
           count(*) filter (where rc.win_probability <= 0.35)
    from ajr.rating_change rc
    join ajr.contest ct on ct.id = rc.contest_id
    where rc.won and not coalesce(ct.bye, false) and ct.duration is distinct from '00:00:00'
    group by ct.competition_id
""")

ATHLETE_SUMMARY = text("""
    insert into ajr.athlete_summary
        (athlete_id, weight, last_contest, last_competition_id, contests, place, score)
    select rc.athlete_id, rc.weight, rc.fought_on, ct.competition_id, counted.contests,
           snapshot.place, snapshot.score
    from ajr.rating_change rc
    join ajr.contest ct on ct.id = rc.contest_id
    join (
        select athlete_id, count(*) as contests from ajr.rating_change group by athlete_id
    ) counted on counted.athlete_id = rc.athlete_id
    left join ajr.leaderboard_snapshot snapshot on snapshot.athlete_id = rc.athlete_id
    where rc.next_fought_on = date '9999-12-31'
""")


def refresh_snapshot(session: Session) -> None:
    """Replace today's tables and the Explore summaries (in the caller's transaction,
    so the site never sees them empty)."""
    session.execute(text("delete from ajr.leaderboard_snapshot"))
    rows = session.execute(REBUILD, {"weights": WEIGHTS}).rowcount
    logger.info("Leaderboard snapshot: %d rows", rows)
    session.execute(text("delete from ajr.competition_stats"))
    session.execute(COMPETITION_STATS)
    session.execute(text("delete from ajr.athlete_summary"))
    rows = session.execute(ATHLETE_SUMMARY).rowcount
    logger.info("Athlete summary: %d rows", rows)
