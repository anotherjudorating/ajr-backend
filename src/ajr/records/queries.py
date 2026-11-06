"""The records computed in SQL: each query lists the best rows of one record.

Every query returns the columns of ajr.record after `record` (place, athlete_id,
opponent_id, country_id, competition_id, weight, value, detail, day), best first,
and reads the temporary tables SETUP makes, and weekly_place (every Sunday's top 10
of every weight, from the weekly tables: ajr/records/weekly.py).
"""

TOP = 500  # rows kept per record

# The IJF World Tour (and the Olympics): where medals count.
WORLD_TOUR = "('Grand Slam', 'Grand Prix', 'Masters', 'World Championships', 'Olympic Games')"
MEDALS = "('gold', 'silver', 'bronze')"
# A score of an athlete whose rating is still a guess (a few contests) is not a record.
SETTLED_RD = 100
# The data starts in 2009 and the ratings need about two years to settle (in 2009-10
# the favourite won 57-67% of contests and RDs were high, from 2011 on 68-71%), so
# the records that rest on ratings count from 2011; counts (medals, streaks,
# rivalries) use all the data. Also the start of the weekly records (weekly.py).
RATINGS_SINCE = "2011-01-01"

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
    order by p.athlete_id, ct.competition_id, ct.weight, ct.round nulls last, ct.fight_no desc,
             ct.id desc -- the same one every time when two have the same round and number
    """,
    f"""
    create temp table medal on commit drop as
    select * from finish where result in {MEDALS} and rank_name in {WORLD_TOUR}
    """,
    # Real fights (no byes, no walkovers), with the scores around them and the
    # opponent's rating before; the Sunday before the contest, for the weekly tables.
    """
    create temp table fight on commit drop as
    select rc.athlete_id, rc.opponent_id, rc.contest_id, rc.seq, rc.fought_on, rc.weight, rc.won,
           rc.win_probability, rc.rd_before, ct.competition_id,
           rc.rating_before, rc.rating_after, o.rating_before as opponent_rating,
           rc.rating_before - s.rd_factor * rc.rd_before as score_before,
           cm.rank_name, ct.round_name, coalesce(ct.golden_score, false) as golden_score,
           ct.duration,
           rc.fought_on - (extract(dow from rc.fought_on)::int
                           + case when extract(dow from rc.fought_on) = 0 then 7 else 0 end)
               as sunday_before
    from ajr.rating_change rc
    cross join ajr.rating_settings s
    join ajr.rating_change o on o.contest_id = rc.contest_id and o.athlete_id = rc.opponent_id
    join ajr.contest ct on ct.id = rc.contest_id
    join ajr.competition cm on cm.id = ct.competition_id
    where not coalesce(ct.bye, false) and ct.duration is distinct from '00:00:00'
    """,
    # The opponent's place on the Sunday before (their best, if in two weights).
    """
    create temp table ranked_fight on commit drop as
    select f.*, p.place as opponent_place
    from fight f
    join (
        select sunday, athlete_id, min(place) as place from weekly_place group by 1, 2
    ) p on p.sunday = f.sunday_before and p.athlete_id = f.opponent_id
    """,
    # Each athlete's main weight, the one with the most contests: the weight of the
    # records that have none of their own (medals, streaks, rivalries), for the
    # site's weight filter.
    """
    create temp table main_weight on commit drop as
    select distinct on (athlete_id) athlete_id, weight
    from (
        select athlete_id, weight, count(*) as contests
        from ajr.rating_change
        where weight is not null
        group by athlete_id, weight
    ) counted
    order by athlete_id, contests desc, weight
    """,
    # Those since the ratings settled.
    f"""
    create temp table rated_fight on commit drop as
    select * from fight where fought_on >= '{RATINGS_SINCE}'
    """,
]


# How much a meeting counts by the rating: 0 at 1900 (below the elite), 1 at 2500.
def strength(rating: str) -> str:
    return f"greatest(0, least(1, ({rating} - 1900) / 600))"


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
              and rc.fought_on >= '{RATINGS_SINCE}'
            order by rc.athlete_id, value desc
        ) best
        order by 1
        limit {TOP}
    """,
    "most_world_tour_medals": f"""
        select rank() over (order by count(*) desc, count(*) filter (where result = 'gold') desc),
               athlete_id, null::int, max(country_id), null::int,
               max(mw.weight), count(*),
               jsonb_build_object(
                   'gold', count(*) filter (where result = 'gold'),
                   'silver', count(*) filter (where result = 'silver'),
                   'bronze', count(*) filter (where result = 'bronze')
               ),
               max(day)
        from medal
        left join main_weight mw using (athlete_id)
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
               mw.weight, streak, jsonb_build_object('from', first_day), last_day
        from streaks
        left join main_weight mw using (athlete_id)
        order by 1
        limit {TOP}
    """,
    "most_world_tour_golds": f"""
        select rank() over (order by count(*) filter (where result = 'gold') desc, count(*) desc),
               athlete_id, null::int, max(country_id), null::int,
               max(mw.weight), count(*) filter (where result = 'gold'),
               jsonb_build_object(
                   'gold', count(*) filter (where result = 'gold'),
                   'silver', count(*) filter (where result = 'silver'),
                   'bronze', count(*) filter (where result = 'bronze')
               ),
               max(day)
        from medal
        left join main_weight mw using (athlete_id)
        group by athlete_id
        having count(*) filter (where result = 'gold') > 0
        order by 1
        limit {TOP}
    """,
    # World Tour competitions in a row won.
    "most_golds_in_row": f"""
        with starts as (
            select athlete_id, country_id, day, coalesce(result = 'gold', false) as gold,
                   count(*) filter (where not coalesce(result = 'gold', false))
                       over (partition by athlete_id order by day, competition_id) as misses
            from finish
            where rank_name in {WORLD_TOUR}
        ),
        streaks as (
            select distinct on (athlete_id) athlete_id, country_id, streak, first_day, last_day
            from (
                select athlete_id, max(country_id) as country_id,
                       count(*) filter (where gold) as streak,
                       min(day) filter (where gold) as first_day,
                       max(day) filter (where gold) as last_day
                from starts
                group by athlete_id, misses
            ) s
            where streak > 0
            order by athlete_id, streak desc, last_day
        )
        select rank() over (order by streak desc), athlete_id, null::int, country_id, null::int,
               mw.weight, streak, jsonb_build_object('from', first_day), last_day
        from streaks
        left join main_weight mw using (athlete_id)
        order by 1
        limit {TOP}
    """,
    # Years between the first and the last World Tour medal.
    "longest_medal_span": f"""
        select rank() over (order by value desc), athlete_id, null::int, country_id, null::int,
               weight, value, jsonb_build_object('medals', medals, 'from', first_day), last_day
        from (
            select athlete_id, max(country_id) as country_id, max(mw.weight) as weight,
                   count(*) as medals, min(day) as first_day, max(day) as last_day,
                   (max(day) - min(day)) / 365.25 as value
            from medal
            left join main_weight mw using (athlete_id)
            group by athlete_id
            having count(*) >= 2
        ) spans
        where value > 0
        order by 1
        limit {TOP}
    """,
    # The share of World Tour finals won, at least 10 finals.
    "best_finals_record": f"""
        select rank() over (order by value desc, finals desc), athlete_id, null::int, country_id,
               null::int, weight, value, jsonb_build_object('finals', finals, 'golds', golds),
               last_day
        from (
            select athlete_id, max(country_id) as country_id, max(mw.weight) as weight,
                   count(*) as finals, count(*) filter (where result = 'gold') as golds,
                   avg((result = 'gold')::int) as value, max(day) as last_day
            from medal
            left join main_weight mw using (athlete_id)
            where result in ('gold', 'silver')
            group by athlete_id
            having count(*) >= 10
        ) finals
        order by 1
        limit {TOP}
    """,
    # World Tour golds the rating gave the smallest chance of winning every contest of
    # the bracket (the product of the winner's chances), at least 3 contests.
    "least_likely_champion": f"""
        select rank() over (order by value), athlete_id, null::int, country_id, competition_id,
               weight, value, jsonb_build_object('contests', contests, 'min_chance', min_chance),
               day
        from (
            select m.athlete_id, m.country_id, m.competition_id, m.weight, m.day,
                   count(*) as contests, min(f.win_probability) as min_chance,
                   exp(sum(ln(f.win_probability))) as value
            from medal m
            join rated_fight f on f.athlete_id = m.athlete_id
                and f.competition_id = m.competition_id and f.weight = m.weight
            where m.result = 'gold'
            group by m.athlete_id, m.country_id, m.competition_id, m.weight, m.day
            having count(*) >= 3
        ) champions
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
    "youngest_grand_slam_gold": f"""
        select rank() over (order by value, day), athlete_id, null::int, country_id,
               competition_id, weight, value, jsonb_build_object('result', result), day
        from (
            select distinct on (m.athlete_id) m.*, extract(year from m.day) - a.dob_year as value
            from medal m
            join ajr.athlete a on a.id = m.athlete_id
            where m.rank_name = 'Grand Slam' and m.result = 'gold'
              and extract(year from m.day) - a.dob_year between 14 and 50
            order by m.athlete_id, m.day
        ) first_gold
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
               mw.weight, streak, jsonb_build_object('from', first_day), last_day
        from streaks
        left join main_weight mw using (athlete_id)
        order by 1
        limit {TOP}
    """,
    # The winner's chance before the contest, over an athlete in the top 10 of the
    # weight on the Sunday before; the contest and the loser's place in the detail.
    "biggest_upsets": f"""
        select rank() over (order by win_probability), athlete_id, opponent_id, null::int,
               competition_id, weight, win_probability,
               jsonb_build_object('contest', contest_id, 'opponent_place', opponent_place),
               fought_on
        from ranked_fight
        where won and opponent_place <= 10 and fought_on >= '{RATINGS_SINCE}'
        order by win_probability
        limit {TOP}
    """,
    # Wins as the underdog over an athlete in the top 10 of the weight.
    "giant_killer": f"""
        select rank() over (order by count(*) desc), athlete_id, null::int, null::int, null::int,
               max(mw.weight), count(*),
               jsonb_build_object(
                   'avg_chance', avg(win_probability),
                   'over_no1', count(*) filter (where opponent_place = 1)
               ),
               max(fought_on)
        from ranked_fight
        left join main_weight mw using (athlete_id)
        where won and win_probability < 0.5 and opponent_place <= 10
          and fought_on >= '{RATINGS_SINCE}'
        group by athlete_id
        order by 1
        limit {TOP}
    """,
    # Wins in golden score: the flag is filled from 2017 on (before, here and there).
    "golden_score_king": f"""
        select rank() over (order by count(*) filter (where won) desc), athlete_id, null::int,
               null::int, null::int, max(mw.weight), count(*) filter (where won),
               jsonb_build_object('contests', count(*), 'share', avg(won::int)),
               max(fought_on)
        from fight
        left join main_weight mw using (athlete_id)
        where golden_score and fought_on >= '2017-01-01'
        group by athlete_id
        having count(*) filter (where won) > 0
        order by 1
        limit {TOP}
    """,
    # World Tour contests in golden score (elsewhere the duration is unreliable), the
    # winner's side; seconds.
    "longest_contest": f"""
        select rank() over (order by seconds desc), athlete_id, opponent_id, null::int,
               competition_id, weight, seconds,
               jsonb_build_object('contest', contest_id, 'round', round_name), fought_on
        from (
            select *, extract(epoch from cast(duration as interval)) as seconds
            from fight
            where won and golden_score and rank_name in {WORLD_TOUR}
              and duration ~ '^[0-9]+:[0-9]{{2}}:[0-9]{{2}}$'
        ) timed
        where seconds between 1 and 3600
        order by seconds desc
        limit {TOP}
    """,
    # A pair's meetings, each by the weaker one's rating before it, less for a
    # one-sided score: sum(strength) x (1 - ((wins - losses) / meetings)^2).
    "greatest_rivalry": f"""
        select rank() over (order by value desc), athlete_id, opponent_id, null::int, null::int,
               weight, value,
               jsonb_build_object('wins', wins, 'losses', losses, 'contests', contests,
                                  'from', first_day),
               last_day
        from (
            select athlete_id, opponent_id, max(weight) as weight, count(*) as contests,
                   count(*) filter (where won) as wins, count(*) filter (where not won) as losses,
                   min(fought_on) as first_day, max(fought_on) as last_day,
                   sum({strength("least(rating_before, opponent_rating)")})
                   * (1 - power((count(*) filter (where won) - count(*) filter (where not won))
                                ::float / count(*), 2)) as value
            from fight
            where athlete_id < opponent_id
            group by athlete_id, opponent_id
        ) pairs
        where value > 0
        order by 1
        limit {TOP}
    """,
    # Years between a pair's first and last meeting, less for few meetings:
    # years x (meetings - 1) / (meetings + 1).
    "longest_rivalry": f"""
        select rank() over (order by value desc), athlete_id, opponent_id, null::int, null::int,
               weight, value,
               jsonb_build_object('wins', wins, 'losses', losses, 'contests', contests,
                                  'from', first_day, 'years', years),
               last_day
        from (
            select *, years * (contests - 1.0) / (contests + 1) as value
            from (
                select athlete_id, opponent_id, max(weight) as weight, count(*) as contests,
                       count(*) filter (where won) as wins,
                       count(*) filter (where not won) as losses,
                       min(fought_on) as first_day, max(fought_on) as last_day,
                       (max(fought_on) - min(fought_on)) / 365.25 as years
                from fight
                where athlete_id < opponent_id
                group by athlete_id, opponent_id
                having count(*) >= 2
            ) pairs
        ) scored
        where value > 0
        order by 1
        limit {TOP}
    """,
    # Wins beyond the chance, in the meetings where the athlete was the underdog, each
    # by the opponent's rating: sum((won - chance) x strength(opponent)).
    "nemesis": f"""
        select rank() over (order by value desc), athlete_id, opponent_id, null::int, null::int,
               weight, value,
               jsonb_build_object('wins', wins, 'losses', losses, 'contests', contests,
                                  'chance', chance, 'from', first_day),
               last_day
        from (
            select athlete_id, opponent_id, max(weight) as weight, count(*) as contests,
                   count(*) filter (where won) as wins, count(*) filter (where not won) as losses,
                   avg(win_probability) as chance,
                   min(fought_on) as first_day, max(fought_on) as last_day,
                   sum(case when win_probability < 0.5
                            then (won::int - win_probability) * {strength("opponent_rating")}
                            else 0 end) as value
            from fight
            group by athlete_id, opponent_id
        ) pairs
        where value > 0
        order by 1
        limit {TOP}
    """,
    # The average score before the competition of the 8 best entrants of every
    # weight; only competitions with at least 10 weights.
    "strongest_tournament": f"""
        with entrants as (
            select distinct on (athlete_id, competition_id)
                   athlete_id, competition_id, weight, score_before
            from rated_fight
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
        from rated_fight
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
}
