"""What the site reads that would be too heavy to compute per request, built ahead:
today's tables of every weight and the summaries behind the Explore lists.

A weight's full table (place and score changes, trend, IJF place, latest
competition: ajr.leaderboard_full) costs the database a few hundred milliseconds
of CPU, and the site asks for several at once; over the Data API that runs past
the 3-second limit. So the rating job builds today's tables on every run (also
when no result changed: names, IJF places or the day may have) into
ajr.leaderboard_snapshot, and api.leaderboard serves them from there.

Likewise today's pound-for-pound and nations tables (ajr.p4p_snapshot,
ajr.teams_snapshot), which api.p4p and api.teams serve; the nations' places and
ratings for the country page (ajr.nation_snapshot) and every nation's medals at
every tournament (ajr.nation_competition); the Explore lists: ajr.competition_stats
(per tournament: real fights, how often the favourite won, upsets) and
ajr.athlete_summary (per athlete: the weight, the latest contest and tournament,
today's place and score); and the medal chances at tournaments with a published
draw (ajr/rating/chances.py).
"""

import logging
from datetime import date

from sqlalchemy import text
from sqlmodel import Session

from ajr.rating.chances import medal_chances
from ajr.rating.engine import RatingParams
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


# Per nation and tournament (individual ones): its athletes and their medals. How an
# athlete ended a tournament: their last contest there (judobase counts the rounds
# down to the final, 0), labelled only in brackets with one final.
NATION_COMPETITION = text("""
    insert into ajr.nation_competition
        (country_id, competition_id, athletes, gold, silver, bronze)
    with ended as (
        select ct.competition_id, ct.weight, rc.athlete_id,
               (array_agg(ct.round_name order by ct.round nulls last, ct.fight_no desc))[1]
                   as last_round,
               (array_agg(rc.won order by ct.round nulls last, ct.fight_no desc))[1] as last_won
        from ajr.rating_change rc
        join ajr.contest ct on ct.id = rc.contest_id
        join ajr.competition cm on cm.id = ct.competition_id
        where not coalesce(cm.is_teams, false)
        group by ct.competition_id, ct.weight, rc.athlete_id
    ),
    one_final as (
        select competition_id, weight
        from ajr.contest
        group by competition_id, weight
        having count(*) filter (where round_name = 'Final') = 1
    ),
    results as (
        select a.country_id, e.competition_id, e.athlete_id,
               case when o.weight is not null
                    then ajr.result_label(e.last_round, e.last_won) end as result
        from ended e
        join ajr.athlete a on a.id = e.athlete_id
        left join one_final o on o.competition_id = e.competition_id and o.weight = e.weight
        where a.country_id is not null
    )
    select country_id, competition_id, count(distinct athlete_id),
           count(*) filter (where result = 'gold'),
           count(*) filter (where result = 'silver'),
           count(*) filter (where result = 'bronze')
    from results
    group by country_id, competition_id
""")


# Today's pound-for-pound and nations tables, as api.p4p and api.teams serve them.
P4P_SNAPSHOT = text("""
    insert into ajr.p4p_snapshot
    select g.gender, current_date, p.*
    from unnest(array['men', 'women']) g(gender)
    cross join lateral ajr.p4p_full(g.gender, current_date) p
""")
TEAMS_SNAPSHOT = text("""
    insert into ajr.teams_snapshot
    select k.kind, current_date, t.*
    from unnest(array['men', 'women', 'mixed']) k(kind)
    cross join lateral ajr.teams_full(k.kind, current_date) t
""")


def refresh_snapshot(session: Session) -> None:
    """Replace today's tables, nations rankings and the Explore summaries (in the
    caller's transaction, so the site never sees them empty)."""
    session.execute(text("delete from ajr.leaderboard_snapshot"))
    rows = session.execute(REBUILD, {"weights": WEIGHTS}).rowcount
    logger.info("Leaderboard snapshot: %d rows", rows)
    session.execute(text("delete from ajr.p4p_snapshot"))
    session.execute(P4P_SNAPSHOT)
    session.execute(text("delete from ajr.teams_snapshot"))
    session.execute(TEAMS_SNAPSHOT)
    session.execute(text("delete from ajr.nation_snapshot"))
    session.execute(NATION_SNAPSHOT, {"men": WEIGHTS[:7], "women": WEIGHTS[7:]})
    session.execute(text("delete from ajr.nation_competition"))
    rows = session.execute(NATION_COMPETITION).rowcount
    logger.info("Nation competitions: %d rows", rows)
    session.execute(text("delete from ajr.competition_stats"))
    session.execute(COMPETITION_STATS)
    session.execute(text("delete from ajr.athlete_summary"))
    rows = session.execute(ATHLETE_SUMMARY).rowcount
    logger.info("Athlete summary: %d rows", rows)
    refresh_chances(session)


# The parameters the rating was computed with, to play brackets with the same.
SETTINGS = text("""
    select initial_rating, initial_rd, max_rd, rd_growth, initial_volatility, tau
    from ajr.rating_settings
""")


def refresh_chances(session: Session, today: date | None = None) -> None:
    """Replace the medal chances: a draw can appear and results come in at any run."""
    settings = session.execute(SETTINGS).mappings().first()
    params = RatingParams(**settings) if settings else RatingParams()
    rows = medal_chances(session.connection(), today or date.today(), params)
    session.execute(text("delete from ajr.medal_chance"))
    if rows:
        session.execute(
            text("""insert into ajr.medal_chance (competition_id, weight, athlete_id, gold, medal)
                    values (:competition_id, :weight, :athlete_id, :gold, :medal)"""),
            rows,
        )
    logger.info("Medal chances: %d rows", len(rows))
