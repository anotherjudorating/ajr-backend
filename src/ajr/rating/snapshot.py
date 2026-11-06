"""What the site reads that would be too heavy to compute per request, built ahead:
today's tables of every weight and the summaries behind the Explore lists.

A weight's full table (place and score changes, trend, IJF place, latest
competition: ajr.leaderboard_full) costs the database a few hundred milliseconds
of CPU, and the site asks for several at once; over the Data API that runs past
the 3-second limit. So the rating job builds today's tables on every run (also
when no result changed: names, IJF places or the day may have) into
ajr.leaderboard_snapshot, and api.leaderboard serves them from there.

The contest list of the Explore pages (ajr.contest_list) is rebuilt by the rating
run for the years it changed (refresh_contest_list), not on every run.

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


# Every rated contest (a real fight: ajr/rating/engine.py). An upset: the winner's
# chance <= 35%.
COMPETITION_STATS = text("""
    insert into ajr.competition_stats (competition_id, contests, accuracy, upsets)
    select ct.competition_id,
           count(*),
           avg((rc.win_probability > 0.5)::int) filter (where rc.win_probability <> 0.5),
           count(*) filter (where rc.win_probability <= 0.35)
    from ajr.rating_change rc
    join ajr.contest ct on ct.id = rc.contest_id
    where rc.won
    group by ct.competition_id
""")

ATHLETE_SUMMARY = text("""
    insert into ajr.athlete_summary
        (athlete_id, weight, last_contest, last_competition_id, contests, place, score,
         family_name, given_name, gender, country, birth_year, last_competition,
         weights, peak_score, peak_on, peak_weight)
    with counted as (
        select athlete_id, count(*) as contests from ajr.rating_change group by athlete_id
    ),
    -- the categories fought in, the latest first
    weights as (
        select athlete_id, array_agg(weight order by last desc, weight) as weights
        from (
            select athlete_id, weight, max(fought_on) as last
            from ajr.rating_change
            where weight is not null
            group by athlete_id, weight
        ) w
        group by athlete_id
    ),
    -- the best score at the end of a day of contests (the earliest such day)
    peaks as (
        select distinct on (rc.athlete_id) rc.athlete_id, rc.fought_on, rc.weight,
               round(rc.rating_after - s.rd_factor * rc.rd_after) as score
        from ajr.rating_change rc
        cross join ajr.rating_settings s
        where rc.next_fought_on > rc.fought_on and rc.weight is not null
        order by rc.athlete_id, rc.rating_after - s.rd_factor * rc.rd_after desc, rc.fought_on
    )
    -- weight: the table listing the athlete (their latest contest's, or the other one
    -- they fight most in: ajr/rating/ranking.py), and their place in it
    select rc.athlete_id, listed.weight, rc.fought_on, ct.competition_id, counted.contests,
           snapshot.place, snapshot.score,
           a.family_name, a.given_name, a.gender, co.ioc, a.dob_year, cm.name,
           weights.weights, peaks.score, peaks.fought_on, peaks.weight
    from ajr.rating_change rc
    join ajr.contest ct on ct.id = rc.contest_id
    join ajr.competition cm on cm.id = ct.competition_id
    join ajr.athlete a on a.id = rc.athlete_id
    left join ajr.country co on co.id = a.country_id
    join counted on counted.athlete_id = rc.athlete_id
    left join weights on weights.athlete_id = rc.athlete_id
    left join peaks on peaks.athlete_id = rc.athlete_id
    cross join lateral (
        select case when rc.listed_here then rc.weight
                    else (select min(l.weight) from ajr.rating_listing l
                          where l.contest_id = rc.contest_id and l.athlete_id = rc.athlete_id)
               end as weight
    ) listed
    left join ajr.leaderboard_snapshot snapshot
        on snapshot.athlete_id = rc.athlete_id and snapshot.weight = listed.weight
    where rc.next_fought_on = date '9999-12-31'
""")

# Every rated contest (a real fight: ajr/rating/engine.py) of the competitions from a year on,
# both athletes with their chance and rating change, as api.contests lists them.
CONTEST_LIST = text("""
    insert into ajr.contest_list
    select ct.id, ct.competition_id, cm.name, extract(year from cm.date_from)::integer,
           w.fought_on, ct.weight, ct.round_name, ct.round, ct.fight_no, ct.winner_id,
           ct.white_id, wa.family_name, wa.given_name, wc.ioc, w.win_probability,
           round(w.rating_after - w.rating_before)::integer,
           ct.blue_id, ba.family_name, ba.given_name, bc.ioc, b.win_probability,
           round(b.rating_after - b.rating_before)::integer,
           case when ct.winner_id = ct.white_id then w.win_probability else b.win_probability end
    from ajr.competition cm
    join ajr.contest ct on ct.competition_id = cm.id
    -- A contest has two rows, one per athlete: "not the other one" picks the same row,
    -- and the planner estimates it right (two equalities together it multiplies into
    -- one row of the 200 thousand, and loops over them for minutes).
    join ajr.rating_change w on w.contest_id = ct.id and w.athlete_id <> ct.blue_id
    join ajr.rating_change b on b.contest_id = ct.id and b.athlete_id <> ct.white_id
    join ajr.athlete wa on wa.id = ct.white_id
    left join ajr.country wc on wc.id = wa.country_id
    join ajr.athlete ba on ba.id = ct.blue_id
    left join ajr.country bc on bc.id = ba.country_id
    where (cast(:since as integer) is null
           or cm.date_from >= make_date(cast(:since as integer), 1, 1))
""")
CONTEST_LIST_DELETE = text("""
    delete from ajr.contest_list where cast(:since as integer) is null or year >= :since
""")
IS_EMPTY = text("select not exists (select from ajr.contest_list)")


def refresh_contest_list(session: Session, since: int | None) -> None:
    """Rebuild the contest list from the year `since` on (all with None): the rating
    rows of those years are new. An empty list (a fresh database) is built whole."""
    if since is not None and session.execute(IS_EMPTY).scalar():
        since = None
    session.execute(CONTEST_LIST_DELETE, {"since": since})
    rows = session.execute(CONTEST_LIST, {"since": since}).rowcount
    logger.info("Contest list from %s: %d rows", since or "the start", rows)


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


# How each athlete did at each tournament, per weight category of the contests: the
# result of their last contest (judobase counts the rounds down to the final, 0;
# labelled only in brackets with one final), their score before and after, contests,
# wins, and their rated contests before it. Read by the tournament's results and the
# athlete's history, and summed up per nation below. A walkover is not rated but is
# part of the bracket: a final won or lost by one still decides the medal, and it
# counts among the contests and wins; an athlete with no rated contest there has no
# row.
ATHLETE_COMPETITION = text("""
    insert into ajr.athlete_competition
    with rated as (
        select rc.athlete_id, rc.contest_id, rc.seq, rc.won,
               rc.rating_before - s.rd_factor * rc.rd_before as score_before,
               rc.rating_after - s.rd_factor * rc.rd_after as score_after,
               row_number() over (partition by rc.athlete_id order by rc.seq) - 1 as before
        from ajr.rating_change rc
        cross join ajr.rating_settings s
    ),
    walkovers as (
        select x.athlete_id, ct.id as contest_id, null::integer as seq,
               ct.winner_id = x.athlete_id as won, null::double precision as score_before,
               null::double precision as score_after, null::bigint as before
        from ajr.contest_walkover w
        join ajr.contest ct on ct.id = w.contest_id
        join ajr.competition cm on cm.id = ct.competition_id
        cross join lateral (values (ct.white_id), (ct.blue_id)) x(athlete_id)
        where ct.winner_id is not null and x.athlete_id is not null
          and cm.kind = 'individual'
          -- the weights the rating counts: an athlete has rated contests there
          and exists (select from ajr.rating_change rc
                      join ajr.contest o on o.id = rc.contest_id
                      where rc.athlete_id = x.athlete_id
                        and o.competition_id = ct.competition_id and o.weight = ct.weight)
    ),
    fights as (
        select f.athlete_id, ct.competition_id, ct.weight, ct.id, ct.round, ct.fight_no,
               ct.round_name, f.seq, f.won, f.score_before, f.score_after, f.before
        from (select * from rated union all select * from walkovers) f
        join ajr.contest ct on ct.id = f.contest_id
        where ct.weight is not null
    ),
    one_final as (
        select competition_id, weight
        from ajr.contest
        group by competition_id, weight
        having count(*) filter (where round_name = 'Final') = 1
    ),
    by_athlete as (
        select athlete_id, competition_id, weight,
               (array_agg(score_before order by seq) filter (where seq is not null))[1]
                   as score_before,
               (array_agg(score_after order by seq desc) filter (where seq is not null))[1]
                   as score_after,
               -- the last contest: the latest round (judobase counts down to the final,
               -- 0), the contest id when two have the same round and number
               (array_agg(round_name order by round nulls last, fight_no desc, id desc))[1]
                   as last_round,
               (array_agg(won order by round nulls last, fight_no desc, id desc))[1] as last_won,
               count(*) as contests,
               count(*) filter (where won) as wins,
               min(before) as contests_before
        from fights
        group by athlete_id, competition_id, weight
        having count(seq) > 0
    )
    select b.athlete_id, b.competition_id, b.weight,
           case when o.weight is not null then ajr.result_label(b.last_round, b.last_won) end,
           round(b.score_before), round(b.score_after), b.contests, b.wins, b.contests_before
    from by_athlete b
    left join one_final o on o.competition_id = b.competition_id and o.weight = b.weight
""")

# Per nation and tournament (individual ones): its athletes and their medals.
NATION_COMPETITION = text("""
    insert into ajr.nation_competition
        (country_id, competition_id, athletes, gold, silver, bronze)
    select a.country_id, r.competition_id, count(distinct r.athlete_id),
           count(*) filter (where r.result = 'gold'),
           count(*) filter (where r.result = 'silver'),
           count(*) filter (where r.result = 'bronze')
    from ajr.athlete_competition r
    join ajr.athlete a on a.id = r.athlete_id
    join ajr.competition cm on cm.id = r.competition_id
    where a.country_id is not null and not coalesce(cm.is_teams, false)
    group by a.country_id, r.competition_id
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
    session.execute(text("delete from ajr.athlete_competition"))
    rows = session.execute(ATHLETE_COMPETITION).rowcount
    logger.info("Athlete competitions: %d rows", rows)
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
