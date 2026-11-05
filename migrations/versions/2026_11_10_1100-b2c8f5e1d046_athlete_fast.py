"""athlete fast

The athlete's page and the contest's page read far less of the history:

- api.athlete read the athlete's whole history three times (ajr.score_at today, 90
  days and 6 months ago) and the weight's whole table four times (ajr.board_at today,
  90 days and 6 months ago, and on the day of the peak): about 1,600 pages for one
  row on a copy of production. Now:
  - ajr.score_at walks the athlete's index back from their latest day and stops at
    the first row whose next contest is after the day (a few pages; the same row);
  - the latest contest's weight and day come from ajr.athlete_summary;
  - today's place and the 90-day and 6-month changes of place come from
    ajr.leaderboard_snapshot, which has them (an athlete not in today's table has
    none, as before);
  - the weights fought in and the peak (score, day, weight) come from
    ajr.athlete_summary, which the rating job now fills; only the place on the day of
    the peak is still looked up (one table).
- api.contest_context(contest_id): what the contest's page shows of the two athletes'
  histories — each one's contests at the tournament and their earlier meetings —
  found from the contest itself (by the tournament's and the athletes' contests)
  instead of loading both whole histories (about 45 % of the database's time a day:
  one contest page loaded two histories).

The new athlete_summary columns are empty until the next update run publishes the
table (minutes after the release): until then the page shows no peak.

Revision ID: b2c8f5e1d046
Revises: a9d4e6f2b371
Create Date: 2026-11-10 11:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c8f5e1d046"
down_revision: Union[str, Sequence[str], None] = "a9d4e6f2b371"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SUMMARY_COLUMNS = """
alter table ajr.athlete_summary
    add column weights text[],  -- fought in, the latest first
    add column peak_score integer,  -- the best score at the end of a day of contests
    add column peak_on date,
    add column peak_weight text
"""

SCORE_AT = """
create or replace function ajr.score_at(p_athlete_id integer, p_day date)
returns table (rating double precision, rd double precision, score double precision, weight text)
language sql stable
set search_path = ''
as $$
    -- The athlete's rating, RD grown since and score on a day: from their last
    -- contest on or before it (the end of their index, not their whole history).
    select rc.rating_after,
           rd.value,
           rc.rating_after - s.rd_factor * rd.value,
           rc.weight::text
    from (
        -- from the athlete's latest day back: the first row whose next contest is
        -- after the day is the last contest of their last day on or before it
        select * from ajr.rating_change rc
        where rc.athlete_id = p_athlete_id and rc.fought_on <= p_day and rc.next_fought_on > p_day
        order by rc.fought_on desc
        limit 1
    ) rc
    cross join ajr.rating_settings s
    cross join lateral (
        select least(s.max_rd, sqrt(rc.rd_after ^ 2 + s.rd_growth ^ 2 * (p_day - rc.fought_on)))
            as value
    ) rd
$$
"""

ATHLETE = """
create or replace function api.athlete(athlete_id integer)
returns table (
    id integer,
    family_name text,
    given_name text,
    gender text,
    birth_year integer,
    country text,
    country_name text,
    weight text,
    rating integer,
    rd integer,
    score integer,
    place bigint,
    last_contest date,
    contests bigint,
    wrl_place integer,
    weights text[],
    peak_score integer,
    peak_on date,
    peak_place bigint,
    score_change_90d integer,
    score_change_6m integer,
    places_up_90d integer,
    places_up_6m integer
)
language sql stable security definer
set search_path = ''
as $$
    -- place is null when the athlete is hidden (a year without contests) or never rated.
    -- weights: the categories fought in, the latest first.
    -- The peak is the best score at the end of a day of contests; peak_place is the
    -- place in that day's table.
    select a.id,
           a.family_name::text,
           a.given_name::text,
           a.gender::text,
           a.dob_year,
           co.ioc::text,
           co.name::text,
           sm.weight,
           round(now.rating)::integer,
           round(now.rd)::integer,
           round(now.score)::integer,
           board.place::bigint,
           sm.last_contest,
           sm.contests::bigint,
           w.place,
           coalesce(sm.weights, '{}'),
           sm.peak_score,
           sm.peak_on,
           (select b.place
            from ajr.board_at(sm.peak_weight, sm.peak_on) b
            where b.athlete_id = a.id),
           round(now.score - s90.score)::integer,
           round(now.score - s6m.score)::integer,
           board.places_up_90d,
           board.places_up_6m
    from ajr.athlete a
    left join ajr.country co on co.id = a.country_id
    -- the latest contest's weight and day, and the counts, as the job left them
    left join ajr.athlete_summary sm on sm.athlete_id = a.id
    left join lateral ajr.score_at(a.id, current_date) now on true
    left join lateral ajr.score_at(a.id, current_date - 90) s90 on true
    left join lateral ajr.score_at(a.id, (current_date - interval '6 months')::date) s6m on true
    left join ajr.leaderboard_snapshot board
        on board.athlete_id = a.id and board.weight = sm.weight
    left join ajr.wrl_ranking w on w.athlete_id = a.id and w.weight = sm.weight
    where a.id = athlete.athlete_id
$$
"""

CONTEST_CONTEXT = """
create function api.contest_context(contest_id integer)
returns table (
    side text,  -- white, blue: whose contest it is
    kind text,  -- road: at this tournament; meeting: the two athletes against each other
    contest_id integer,
    fought_on date,
    competition_id integer,
    competition text,
    round text,
    weight text,
    opponent_id integer,
    opponent_family_name text,
    opponent_given_name text,
    opponent_country text,
    won boolean,
    win_probability double precision,
    rating_before integer,
    rating_after integer,
    rd_after integer,
    rd_before integer,
    score_before integer,
    score_after integer,
    opponent_score integer,
    result text
)
language sql stable security definer
set search_path = ''
as $$
    -- Rows as api.athlete_history's (latest first): each athlete's contests at the
    -- tournament of this one (road), and the white athlete's contests against the blue
    -- one (meeting); this contest is among them.
    with c as (
        select ct.competition_id, ct.white_id, ct.blue_id
        from ajr.contest ct
        where ct.id = contest_context.contest_id
    ),
    picked as (
        select s.side, 'road' as kind, s.athlete_id, ct.id
        from c
        cross join lateral (values ('white', c.white_id), ('blue', c.blue_id)) s(side, athlete_id)
        join ajr.contest ct
            on ct.competition_id = c.competition_id and s.athlete_id in (ct.blue_id, ct.white_id)
        union all
        select 'white', 'meeting', c.white_id, ct.id
        from c
        join ajr.contest ct
            on (ct.blue_id = c.white_id and ct.white_id = c.blue_id)
            or (ct.white_id = c.white_id and ct.blue_id = c.blue_id)
    )
    select p.side,
           p.kind,
           rc.contest_id,
           rc.fought_on,
           cm.id,
           cm.name::text,
           ct.round_name::text,
           rc.weight::text,
           rc.opponent_id,
           o.family_name::text,
           o.given_name::text,
           co.ioc::text,
           rc.won,
           rc.win_probability,
           round(rc.rating_before)::integer,
           round(rc.rating_after)::integer,
           round(rc.rd_after)::integer,
           round(rc.rd_before)::integer,
           round(rc.rating_before - s.rd_factor * rc.rd_before)::integer,
           round(rc.rating_after - s.rd_factor * rc.rd_after)::integer,
           round(orc.rating_before - s.rd_factor * orc.rd_before)::integer,
           r.result
    from picked p
    join ajr.rating_change rc on rc.contest_id = p.id and rc.athlete_id = p.athlete_id
    cross join ajr.rating_settings s
    join ajr.contest ct on ct.id = rc.contest_id
    join ajr.competition cm on cm.id = ct.competition_id
    join ajr.athlete o on o.id = rc.opponent_id
    left join ajr.country co on co.id = o.country_id
    left join ajr.rating_change orc
        on orc.contest_id = rc.contest_id and orc.athlete_id = rc.opponent_id
    left join ajr.athlete_competition r
        on r.athlete_id = rc.athlete_id and r.competition_id = ct.competition_id
       and r.weight = ct.weight
    order by p.side desc, p.kind desc, rc.fought_on desc, ct.round nulls last,
             ct.fight_no desc, ct.id desc
$$
"""


def load_migration(name: str):
    """An earlier migration's module, to restore its SQL."""
    import importlib.util
    from pathlib import Path

    path = next(Path(__file__).parent.glob(f"*{name}.py"))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(SUMMARY_COLUMNS)
    op.execute(SCORE_AT)
    op.execute(ATHLETE)
    op.execute(CONTEST_CONTEXT)
    op.execute("revoke execute on function api.contest_context(integer) from public")
    op.execute("grant execute on function api.contest_context(integer) to anon, authenticated")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop function api.contest_context(integer)")
    page = load_migration("bc0c985bd1f9_athlete_page")
    for sql in (page.SCORE_AT, page.ATHLETE):
        op.execute(sql.replace("create function", "create or replace function"))
    op.execute(
        "alter table ajr.athlete_summary drop column weights, drop column peak_score, "
        "drop column peak_on, drop column peak_weight"
    )
