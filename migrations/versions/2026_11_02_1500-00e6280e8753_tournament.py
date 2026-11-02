"""tournament

What the tournament page and its weight pages need:

- api.competition(competition_id): the tournament (name, level, place, dates),
  its stats (ajr.competition_stats: real fights, how often the favourite won,
  upsets) and its weights in the site's order.
- api.competition_results(competition_id): every athlete of every weight: how
  they ended it (ajr.result_label; only in brackets with one final, as in the
  records), their score before their first contest and after their last, the
  contests and wins. Medals, medals by nation and the biggest gains come from it.
- api.competition_contests(competition_id, only_weight): every decided contest,
  both athletes with their chance and their score before and after, in bracket
  order (from the final back). Upsets come from it.

Revision ID: 00e6280e8753
Revises: 246c9fcfbe4a
Create Date: 2026-11-02 15:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "00e6280e8753"
down_revision: Union[str, Sequence[str], None] = "246c9fcfbe4a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Men, then women, lightest first; anything else (open weight) last.
WEIGHT_ORDER = (
    "coalesce(array_position(array['-60', '-66', '-73', '-81', '-90', '-100', '+100',"
    " '-48', '-52', '-57', '-63', '-70', '-78', '+78'], {}), 100)"
)

COMPETITION = f"""
create function api.competition(competition_id integer)
returns table (
    id integer,
    name text,
    rank_name text,
    city text,
    country text,
    country_name text,
    date_from date,
    date_to date,
    contests integer,
    accuracy double precision,
    upsets integer,
    weights text[]
)
language sql stable security definer
set search_path = ''
as $$
    select cm.id, cm.name::text, cm.rank_name::text, cm.city::text, co.ioc::text, co.name::text,
           cm.date_from, cm.date_to, st.contests, st.accuracy, st.upsets,
           array(
               select w.weight
               from (
                   select distinct ct.weight::text as weight
                   from ajr.contest ct
                   where ct.competition_id = cm.id and ct.weight is not null
               ) w
               order by {WEIGHT_ORDER.format("w.weight")}, w.weight
           )
    from ajr.competition cm
    left join ajr.competition_stats st on st.competition_id = cm.id
    left join ajr.country co on co.id = cm.country_id
    where cm.id = competition.competition_id
$$
"""

COMPETITION_RESULTS = f"""
create function api.competition_results(competition_id integer)
returns table (
    athlete_id integer,
    family_name text,
    given_name text,
    gender text,
    country text,
    weight text,
    result text,
    score_before integer,
    score_after integer,
    contests integer,
    wins integer
)
language sql stable security definer
set search_path = ''
as $$
    -- result: gold, silver, bronze, 5th, 7th, the round lost in, or null (still in,
    -- pools, or a bracket where every contest is a "Final").
    with fights as (
        select rc.athlete_id, ct.weight, ct.round, ct.fight_no, ct.round_name, rc.seq, rc.won,
               rc.rating_before - s.rd_factor * rc.rd_before as score_before,
               rc.rating_after - s.rd_factor * rc.rd_after as score_after
        from ajr.contest ct
        join ajr.rating_change rc on rc.contest_id = ct.id
        cross join ajr.rating_settings s
        where ct.competition_id = competition_results.competition_id
    ),
    one_final as (
        select ct.weight
        from ajr.contest ct
        where ct.competition_id = competition_results.competition_id
        group by ct.weight
        having count(*) filter (where ct.round_name = 'Final') = 1
    ),
    by_athlete as (
        select athlete_id, weight,
               (array_agg(score_before order by seq))[1] as score_before,
               (array_agg(score_after order by seq desc))[1] as score_after,
               -- the last contest: the latest round (judobase counts down to the final, 0)
               (array_agg(round_name order by round nulls last, fight_no desc))[1] as last_round,
               (array_agg(won order by round nulls last, fight_no desc))[1] as last_won,
               count(*) as contests,
               count(*) filter (where won) as wins
        from fights
        group by athlete_id, weight
    )
    select b.athlete_id, a.family_name::text, a.given_name::text, a.gender::text, co.ioc::text,
           b.weight::text,
           case when f.weight is not null then ajr.result_label(b.last_round, b.last_won) end,
           round(b.score_before)::integer, round(b.score_after)::integer,
           b.contests::integer, b.wins::integer
    from by_athlete b
    join ajr.athlete a on a.id = b.athlete_id
    left join ajr.country co on co.id = a.country_id
    left join one_final f on f.weight = b.weight
    order by {WEIGHT_ORDER.format("b.weight")}, b.weight,
             array_position(array['gold', 'silver', 'bronze', '5th', '7th'],
                            case when f.weight is not null
                                 then ajr.result_label(b.last_round, b.last_won) end) nulls last,
             b.score_after desc
$$
"""

COMPETITION_CONTESTS = f"""
create function api.competition_contests(competition_id integer, only_weight text default null)
returns table (
    contest_id integer,
    weight text,
    round text,
    winner_id integer,
    white_id integer,
    white_family_name text,
    white_given_name text,
    white_country text,
    white_chance double precision,
    white_score_before integer,
    white_score_after integer,
    blue_id integer,
    blue_family_name text,
    blue_given_name text,
    blue_country text,
    blue_chance double precision,
    blue_score_before integer,
    blue_score_after integer,
    real_fight boolean
)
language sql stable security definer
set search_path = ''
as $$
    -- Decided contests, by weight, from the final back to the first round.
    -- real_fight: not a bye, not a 0:00 walkover.
    select ct.id, ct.weight::text, ct.round_name::text, ct.winner_id,
           ct.white_id, w.family_name::text, w.given_name::text, wc.ioc::text,
           wr.win_probability,
           round(wr.rating_before - s.rd_factor * wr.rd_before)::integer,
           round(wr.rating_after - s.rd_factor * wr.rd_after)::integer,
           ct.blue_id, b.family_name::text, b.given_name::text, bc.ioc::text,
           br.win_probability,
           round(br.rating_before - s.rd_factor * br.rd_before)::integer,
           round(br.rating_after - s.rd_factor * br.rd_after)::integer,
           not coalesce(ct.bye, false) and ct.duration is distinct from '00:00:00'
    from ajr.contest ct
    cross join ajr.rating_settings s
    join ajr.rating_change wr on wr.contest_id = ct.id and wr.athlete_id = ct.white_id
    join ajr.rating_change br on br.contest_id = ct.id and br.athlete_id = ct.blue_id
    join ajr.athlete w on w.id = ct.white_id
    left join ajr.country wc on wc.id = w.country_id
    join ajr.athlete b on b.id = ct.blue_id
    left join ajr.country bc on bc.id = b.country_id
    where ct.competition_id = competition_contests.competition_id
      and (competition_contests.only_weight is null
           or ct.weight = competition_contests.only_weight)
    order by {WEIGHT_ORDER.format("ct.weight")}, ct.weight, ct.round nulls last, ct.fight_no
$$
"""

FUNCTIONS = {
    "api.competition(integer)": COMPETITION,
    "api.competition_results(integer)": COMPETITION_RESULTS,
    "api.competition_contests(integer, text)": COMPETITION_CONTESTS,
}


def upgrade() -> None:
    """Upgrade schema."""
    for signature, sql in FUNCTIONS.items():
        op.execute(sql)
        op.execute(f"revoke execute on function {signature} from public")
        op.execute(f"grant execute on function {signature} to anon, authenticated")


def downgrade() -> None:
    """Downgrade schema."""
    for signature in FUNCTIONS:
        op.execute(f"drop function {signature}")
