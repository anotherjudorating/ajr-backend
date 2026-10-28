"""The records computed in SQL: each query lists the best rows of one record.

Every query returns the columns of ajr.record after `record` (place, athlete_id,
opponent_id, country_id, competition_id, weight, value, detail, day), best first,
and reads the temporary tables SETUP makes.
"""

TOP = 500  # rows kept per record

# The IJF World Tour (and the Olympics): where medals count.
WORLD_TOUR = "('Grand Slam', 'Grand Prix', 'Masters', 'World Championships', 'Olympic Games')"
MEDALS = "('gold', 'silver', 'bronze')"
# A score of an athlete whose rating is still a guess (a few contests) is not a record.
SETTLED_RD = 100

SETUP = [
    # How every athlete ended every individual competition (ajr.result_label). Only
    # brackets with one final: in some old competitions every contest is a "Final".
    """
    create temp table finish on commit drop as
    with bracket as (
        select competition_id, weight
        from ajr.contest
        group by competition_id, weight
        having count(*) filter (where round_name = 'Final') = 1
    )
    select distinct on (p.athlete_id, ct.competition_id, ct.weight)
           p.athlete_id, a.country_id, ct.competition_id, ct.weight,
           cm.date_from as day, cm.rank_name,
           ajr.result_label(ct.round_name, ct.winner_id = p.athlete_id) as result
    from ajr.contest ct
    join ajr.competition cm on cm.id = ct.competition_id
    cross join lateral (values (ct.blue_id), (ct.white_id)) p(athlete_id)
    join ajr.athlete a on a.id = p.athlete_id
    join bracket b on b.competition_id = ct.competition_id and b.weight = ct.weight
    where ct.winner_id is not null
      and cm.date_from is not null
      and not coalesce(cm.is_teams, false)
    order by p.athlete_id, ct.competition_id, ct.weight, ct.round nulls last, ct.fight_no desc
    """,
    f"""
    create temp table medal on commit drop as
    select * from finish where result in {MEDALS} and rank_name in {WORLD_TOUR}
    """,
    # Real fights (no byes, no walkovers), with the scores around them.
    """
    create temp table fight on commit drop as
    select rc.athlete_id, rc.opponent_id, rc.seq, rc.fought_on, rc.weight, rc.won,
           rc.win_probability, rc.rd_before, ct.competition_id,
           rc.rating_before, rc.rating_after,
           rc.rating_before - s.rd_factor * rc.rd_before as score_before
    from ajr.rating_change rc
    cross join ajr.rating_settings s
    join ajr.contest ct on ct.id = rc.contest_id
    where not coalesce(ct.bye, false) and ct.duration is distinct from '00:00:00'
    """,
]

RECORDS = {
    # The best score at the end of a day of contests, one row per athlete.
    "highest_rating": f"""
        select rank() over (order by value desc), athlete_id, null::int, null::int, null::int,
               weight, value, null::jsonb, day
        from (
            select distinct on (rc.athlete_id)
                   rc.athlete_id, rc.weight, rc.fought_on as day,
                   rc.rating_after - s.rd_factor * rc.rd_after as value
            from ajr.rating_change rc
            cross join ajr.rating_settings s
            where rc.next_fought_on > rc.fought_on and rc.weight is not null
            order by rc.athlete_id, value desc
        ) best
        order by 1
        limit {TOP}
    """,
    # Rating (skill) won at one competition by an athlete whose rating was settled.
    "biggest_tournament_gain": f"""
        select rank() over (order by value desc), athlete_id, null::int, null::int,
               competition_id, weight, value, null::jsonb, day
        from (
            select athlete_id, competition_id, max(weight) as weight, max(fought_on) as day,
                   (array_agg(rating_after order by seq desc))[1]
                   - (array_agg(rating_before order by seq))[1] as value,
                   (array_agg(rd_before order by seq))[1] as rd_before
            from fight
            group by athlete_id, competition_id
        ) gain
        where rd_before <= {SETTLED_RD}
        order by 1
        limit {TOP}
    """,
    "most_world_tour_medals": f"""
        select rank() over (order by count(*) desc, count(*) filter (where result = 'gold') desc),
               athlete_id, null::int, max(country_id), null::int, null, count(*),
               jsonb_build_object(
                   'gold', count(*) filter (where result = 'gold'),
                   'silver', count(*) filter (where result = 'silver'),
                   'bronze', count(*) filter (where result = 'bronze')
               ),
               max(day)
        from medal
        group by athlete_id
        order by 1
        limit {TOP}
    """,
    # World Tour competitions in a row with a medal; day: the last of them.
    "most_medals_in_row": f"""
        with starts as (
            select athlete_id, country_id, day, coalesce(result in {MEDALS}, false) as medal,
                   count(*) filter (where not coalesce(result in {MEDALS}, false))
                       over (partition by athlete_id order by day, competition_id) as misses
            from finish
            where rank_name in {WORLD_TOUR}
        ),
        streaks as (
            select distinct on (athlete_id) athlete_id, country_id, streak, first_day, last_day
            from (
                select athlete_id, max(country_id) as country_id,
                       count(*) filter (where medal) as streak,
                       min(day) filter (where medal) as first_day,
                       max(day) filter (where medal) as last_day
                from starts
                group by athlete_id, misses
            ) s
            where streak > 0
            order by athlete_id, streak desc, last_day
        )
        select rank() over (order by streak desc), athlete_id, null::int, country_id, null::int,
               null, streak, jsonb_build_object('from', first_day), last_day
        from streaks
        order by 1
        limit {TOP}
    """,
    # Age by years of birth (judobase has only the year).
    "youngest_grand_slam_medal": f"""
        select rank() over (order by value, day), athlete_id, null::int, country_id,
               competition_id, weight, value, jsonb_build_object('result', result), day
        from (
            select distinct on (m.athlete_id) m.*, extract(year from m.day) - a.dob_year as value
            from medal m
            join ajr.athlete a on a.id = m.athlete_id
            where m.rank_name = 'Grand Slam'
              and extract(year from m.day) - a.dob_year between 14 and 50
            order by m.athlete_id, m.day
        ) first_medal
        order by 1
        limit {TOP}
    """,
    "longest_winning_streak": f"""
        with numbered as (
            select athlete_id, fought_on, won,
                   count(*) filter (where not won) over (partition by athlete_id order by seq)
                       as losses
            from fight
        ),
        streaks as (
            select distinct on (athlete_id) athlete_id, streak, first_day, last_day
            from (
                select athlete_id, count(*) filter (where won) as streak,
                       min(fought_on) filter (where won) as first_day,
                       max(fought_on) filter (where won) as last_day
                from numbered
                group by athlete_id, losses
            ) s
            where streak > 0
            order by athlete_id, streak desc, last_day
        )
        select rank() over (order by streak desc), athlete_id, null::int, null::int, null::int,
               null, streak, jsonb_build_object('from', first_day), last_day
        from streaks
        order by 1
        limit {TOP}
    """,
    # The winner's chance before the contest.
    "biggest_upsets": f"""
        select rank() over (order by win_probability), athlete_id, opponent_id, null::int,
               competition_id, weight, win_probability, null::jsonb, fought_on
        from fight
        where won
        order by win_probability
        limit {TOP}
    """,
    # Wins with at most a 30% chance.
    "giant_killer": f"""
        select rank() over (order by count(*) desc), athlete_id, null::int, null::int, null::int,
               null, count(*), null::jsonb, max(fought_on)
        from fight
        where won and win_probability <= 0.3
        group by athlete_id
        order by 1
        limit {TOP}
    """,
    # Contests between the same two athletes; wins and losses of the first one.
    "most_frequent_rivalry": f"""
        select rank() over (order by count(*) desc), athlete_id, opponent_id, null::int,
               null::int, null, count(*),
               jsonb_build_object(
                   'wins', count(*) filter (where won),
                   'losses', count(*) filter (where not won)
               ),
               max(fought_on)
        from fight
        where athlete_id < opponent_id
        group by athlete_id, opponent_id
        order by 1
        limit {TOP}
    """,
    # The average score before the competition of the 8 best entrants of every
    # weight; only competitions with at least 10 weights.
    "strongest_tournament": f"""
        with entrants as (
            select distinct on (athlete_id, competition_id)
                   athlete_id, competition_id, weight, score_before
            from fight
            order by athlete_id, competition_id, seq
        ),
        best as (
            select *, row_number() over (
                partition by competition_id, weight order by score_before desc
            ) as n
            from entrants
        )
        select rank() over (order by avg(score_before) desc), null::int, null::int, null::int,
               competition_id, null, avg(score_before),
               jsonb_build_object('weights', count(distinct weight)), min(cm.date_from)
        from best
        join ajr.competition cm on cm.id = best.competition_id
        where n <= 8
        group by competition_id
        having count(distinct weight) >= 10
        order by 1
        limit {TOP}
    """,
    "most_nations_on_podium": f"""
        select rank() over (order by count(distinct country_id) desc), null::int, null::int,
               null::int, competition_id, null, count(distinct country_id), null::jsonb, min(day)
        from finish
        where result in {MEDALS}
        group by competition_id
        order by 1
        limit {TOP}
    """,
    # Log loss of the predictions (the winner's chance), at least 100 contests.
    "most_unpredictable_tournament": f"""
        select rank() over (order by avg(-ln(win_probability)) desc), null::int, null::int,
               null::int, competition_id, null, avg(-ln(win_probability)),
               jsonb_build_object(
                   'contests', count(*),
                   'favourites_won', avg((win_probability > 0.5)::int)
               ),
               min(fought_on)
        from fight
        where won
        group by competition_id
        having count(*) >= 100
        order by 1
        limit {TOP}
    """,
    "most_predictable_tournament": f"""
        select rank() over (order by avg(-ln(win_probability))), null::int, null::int,
               null::int, competition_id, null, avg(-ln(win_probability)),
               jsonb_build_object(
                   'contests', count(*),
                   'favourites_won', avg((win_probability > 0.5)::int)
               ),
               min(fought_on)
        from fight
        where won
        group by competition_id
        having count(*) >= 100
        order by 1
        limit {TOP}
    """,
    "most_medals_nation": f"""
        select rank() over (order by count(*) desc, count(*) filter (where result = 'gold') desc),
               null::int, null::int, country_id, null::int, null, count(*),
               jsonb_build_object(
                   'gold', count(*) filter (where result = 'gold'),
                   'silver', count(*) filter (where result = 'silver'),
                   'bronze', count(*) filter (where result = 'bronze')
               ),
               max(day)
        from medal
        where country_id is not null
        group by country_id
        order by 1
        limit {TOP}
    """,
    "most_medals_one_tournament": f"""
        select rank() over (order by count(*) desc, count(*) filter (where result = 'gold') desc),
               null::int, null::int, country_id, competition_id, null, count(*),
               jsonb_build_object(
                   'gold', count(*) filter (where result = 'gold'),
                   'silver', count(*) filter (where result = 'silver'),
                   'bronze', count(*) filter (where result = 'bronze')
               ),
               min(day)
        from medal
        where country_id is not null
        group by country_id, competition_id
        order by 1
        limit {TOP}
    """,
}
