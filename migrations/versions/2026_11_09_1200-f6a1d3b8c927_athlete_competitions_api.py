"""athlete competitions api

The tournament's results and the athlete's history read ajr.athlete_competition,
which the rating job keeps (previous migration), instead of computing how each
athlete did from the whole history on every request:

- api.competition_results: about 20 thousand pages for a Grand Slam on a copy of
  production, now about 1 thousand (83 ms -> 26 ms);
- api.athlete_history: each contest's result from the table (it looked for the
  athlete's last contest of the competition for every row); 7 thousand pages for a
  long career, now 4 thousand.

Same arguments and rows (checked on a copy of production: 120 tournaments' results,
300 athletes' histories). A contest the rating does not count no longer decides an
athlete's result in their history, as it never did in the tournament's results.

Revision ID: f6a1d3b8c927
Revises: e4b9c2d7a815
Create Date: 2026-11-09 12:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a1d3b8c927"
down_revision: Union[str, Sequence[str], None] = "e4b9c2d7a815"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WEIGHT_ORDER = (
    "coalesce(array_position(array['-60', '-66', '-73', '-81', '-90', '-100', '+100', "
    "'-48', '-52', '-57', '-63', '-70', '-78', '+78'], r.weight), 100)"
)

COMPETITION_RESULTS = f"""
create or replace function api.competition_results(competition_id integer)
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
    wins integer,
    contests_before integer
)
language sql stable security definer
set search_path = ''
as $$
    -- result: gold, silver, bronze, 5th, 7th, the round lost in, or null (still in,
    -- pools, or a bracket where every contest is a "Final").
    select r.athlete_id, a.family_name::text, a.given_name::text, a.gender::text, co.ioc::text,
           r.weight, r.result, r.score_before, r.score_after, r.contests, r.wins,
           r.contests_before
    from ajr.athlete_competition r
    join ajr.athlete a on a.id = r.athlete_id
    left join ajr.country co on co.id = a.country_id
    where r.competition_id = competition_results.competition_id
    order by {WEIGHT_ORDER}, r.weight,
             array_position(array['gold', 'silver', 'bronze', '5th', '7th'], r.result) nulls last,
             r.score_after desc
$$
"""

ATHLETE_HISTORY = """
create or replace function api.athlete_history(athlete_id integer, only_weight text default null)
returns table (
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
    -- Latest first; within a day the later round (judobase counts down to the final) first.
    -- weight is the category the contest counts for (an open-weight contest keeps
    -- the athlete's), and only_weight picks the contests of one category.
    -- result: how the athlete ended the competition (ajr.athlete_competition).
    select rc.contest_id,
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
    from ajr.rating_change rc
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
    where rc.athlete_id = athlete_history.athlete_id
      and (athlete_history.only_weight is null or rc.weight = athlete_history.only_weight)
    order by rc.fought_on desc, ct.round nulls last, ct.fight_no desc, ct.id desc
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
    op.execute(COMPETITION_RESULTS)
    op.execute(ATHLETE_HISTORY)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        load_migration("8b3e61f0c2d7_contests_before")
        .competition_results()
        .replace("create function", "create or replace function")
    )
    op.execute(
        load_migration("bc0c985bd1f9_athlete_page").ATHLETE_HISTORY.replace(
            "create function", "create or replace function"
        )
    )
