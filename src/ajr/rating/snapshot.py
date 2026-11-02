"""What the site reads that would be too heavy to compute per request, built ahead:
today's tables of every weight and the summaries behind the Explore lists.

A weight's full table (place and score changes, trend, IJF place, latest
competition: ajr.leaderboard_full) costs the database a few hundred milliseconds
of CPU, and the site asks for several at once; over the Data API that runs past
the 3-second limit. So the rating job builds today's tables on every run (also
when no result changed: names, IJF places or the day may have) into
ajr.leaderboard_snapshot, and api.leaderboard serves them from there.

Likewise today's nations rankings (ajr.nation_snapshot, for the country page),
ranked as api.teams ranks them but from the tables just built; and the Explore
lists: ajr.competition_stats (per tournament: real fights, how often the favourite
won, upsets) and ajr.athlete_summary (per athlete: the weight, the latest contest
and tournament, today's place and score).
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


# A nation's rating: the average score of its best athlete in every weight of the
# kind; a weight without one counts as the last place of that weight's table.
NATION_SNAPSHOT = text("""
    insert into ajr.nation_snapshot (kind, country_id, place, rating)
    with kinds (kind, weights) as (
        values ('men', cast(:men as text[])), ('women', cast(:women as text[])),
               ('mixed', cast(:men as text[]) || cast(:women as text[]))
    ),
    best as (
        select distinct on (l.weight, a.country_id) l.weight, a.country_id, l.score
        from ajr.leaderboard_snapshot l
        join ajr.athlete a on a.id = l.athlete_id
        where a.country_id is not null
        order by l.weight, a.country_id, l.score desc
    ),
    last_place as (
        select weight, min(score) as score from ajr.leaderboard_snapshot group by weight
    ),
    nations as (
        select k.kind, n.country_id, avg(coalesce(b.score, lp.score)) as score
        from kinds k
        join last_place lp on lp.weight = any(k.weights)
        cross join (
            select distinct b.country_id
            from best b
            join kinds k2 on b.weight = any(k2.weights)
        ) n
        left join best b on b.country_id = n.country_id and b.weight = lp.weight
        group by k.kind, n.country_id
        having count(b.weight) > 0
    )
    select kind, country_id, rank() over (partition by kind order by score desc),
           round(score)
    from nations
""")


def refresh_snapshot(session: Session) -> None:
    """Replace today's tables, nations rankings and the Explore summaries (in the
    caller's transaction, so the site never sees them empty)."""
    session.execute(text("delete from ajr.leaderboard_snapshot"))
    rows = session.execute(REBUILD, {"weights": WEIGHTS}).rowcount
    logger.info("Leaderboard snapshot: %d rows", rows)
    session.execute(text("delete from ajr.nation_snapshot"))
    session.execute(NATION_SNAPSHOT, {"men": WEIGHTS[:7], "women": WEIGHTS[7:]})
    session.execute(text("delete from ajr.competition_stats"))
    session.execute(COMPETITION_STATS)
    session.execute(text("delete from ajr.athlete_summary"))
    rows = session.execute(ATHLETE_SUMMARY).rowcount
    logger.info("Athlete summary: %d rows", rows)
