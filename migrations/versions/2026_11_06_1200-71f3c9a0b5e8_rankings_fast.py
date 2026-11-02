"""rankings fast

The rankings' nations and pound-for-pound tables timed out on their first call
(api.teams for mixed: 3.3 s, past the Data API's limit for anon), and any past
day was slow: both build every weight's table with ajr.board_at, which read the
whole history of the weight.

- ajr.board_at: a weight's table on a day is the athletes whose latest contest by
  then is at most hide_after_days (a year) old; it now asks the new index on
  (weight, fought_on) for that year only, not for every row whose next contest
  came after the day (for 2012, nearly the whole history).
- Today's tables are built ahead, as the weights' are (ajr.leaderboard_snapshot):
  ajr.p4p_full / ajr.teams_full are api.p4p / api.teams as they were, run by the
  rating job into ajr.p4p_snapshot / ajr.teams_snapshot (ajr/rating/snapshot.py);
  api.p4p / api.teams serve today from there and compute any other day.

Revision ID: 71f3c9a0b5e8
Revises: d2a71c5e94b3
Create Date: 2026-11-06 12:00:00

"""

import importlib.util
from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "71f3c9a0b5e8"
down_revision: Union[str, Sequence[str], None] = "d2a71c5e94b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX = "create index ix_rating_change_weight_fought_on on ajr.rating_change (weight, fought_on)"

TABLES = [
    """
    create table ajr.p4p_snapshot (
        gender text not null,
        day date not null,
        place bigint not null,
        athlete_id integer not null references ajr.athlete (id),
        family_name text,
        given_name text,
        country text,
        weight text,
        weight_place bigint,
        rating integer,
        rd integer,
        score integer,
        gap integer,
        trend integer[],
        primary key (gender, athlete_id)
    )
    """,
    """
    create table ajr.teams_snapshot (
        kind text not null,
        day date not null,
        place bigint not null,
        country text not null,
        country_name text,
        rating integer,
        weights_led integer,
        weights_top8 integer,
        weights_filled integer,
        primary key (kind, country)
    )
    """,
]

P4P = """
create or replace function api.p4p(gender text, day date default current_date)
returns table (
    place bigint,
    athlete_id integer,
    family_name text,
    given_name text,
    country text,
    weight text,
    weight_place bigint,
    rating integer,
    rd integer,
    score integer,
    gap integer,
    trend integer[]
)
language sql stable security definer
set search_path = ''
as $$
    -- today's, built by the rating job
    select s.place, s.athlete_id, s.family_name, s.given_name, s.country, s.weight,
           s.weight_place, s.rating, s.rd, s.score, s.gap, s.trend
    from ajr.p4p_snapshot s
    where s.gender = p4p.gender and s.day = p4p.day
    union all
    -- any other day
    select * from ajr.p4p_full(p4p.gender, p4p.day)
    where not exists (
        select from ajr.p4p_snapshot s where s.gender = p4p.gender and s.day = p4p.day
    )
    order by 1, 3
$$
"""

TEAMS = """
create or replace function api.teams(kind text, day date default current_date)
returns table (
    place bigint,
    country text,
    country_name text,
    rating integer,
    weights_led integer,
    weights_top8 integer,
    weights_filled integer
)
language sql stable security definer
set search_path = ''
as $$
    -- today's, built by the rating job
    select s.place, s.country, s.country_name, s.rating, s.weights_led, s.weights_top8,
           s.weights_filled
    from ajr.teams_snapshot s
    where s.kind = teams.kind and s.day = teams.day
    union all
    -- any other day
    select * from ajr.teams_full(teams.kind, teams.day)
    where not exists (
        select from ajr.teams_snapshot s where s.kind = teams.kind and s.day = teams.day
    )
    order by 1, 3
$$
"""


def load_migration(name: str):
    """An earlier migration's module, to reuse its SQL."""
    path = next(Path(__file__).parent.glob(f"*{name}.py"))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def previous_board_at() -> str:
    return load_migration("ead6ff26f31b_api_for_the_site").BOARD_AT


def board_at() -> str:
    """ajr.board_at, asking the index for the year before the day only."""
    sql = (
        previous_board_at()
        .replace("create function ajr.board_at", "create or replace function ajr.board_at")
        .replace(
            "      and rc.fought_on <= p_day\n",
            "      and rc.fought_on <= p_day\n"
            "      -- the same as the hiding below, but in a form the index can answer\n"
            "      and rc.fought_on >= p_day - coalesce(\n"
            "          (select hide_after_days from ajr.rating_settings), 1000000)\n",
        )
    )
    assert "rc.fought_on >= p_day" in sql
    return sql


def previous(name: str) -> str:
    """api.p4p or api.teams as the "p4p and teams" migration created them."""
    return getattr(load_migration("4ae485321e30_p4p_and_teams"), name)


def full(name: str, parameter: str) -> str:
    """The previous api.p4p / api.teams as ajr.p4p_full / ajr.teams_full: the same
    query, now run by the rating job (as the owner) and for days off the snapshot."""
    function = name.lower()
    sql = (
        previous(name)
        .replace(
            f"create function api.{function}({parameter} text, day date default current_date)",
            f"create function ajr.{function}_full({parameter} text, day date)",
        )
        .replace("language sql stable security definer", "language sql stable")
        .replace(f"{function}.{parameter}", f"{function}_full.{parameter}")
        .replace(f"{function}.day", f"{function}_full.day")
    )
    assert f"ajr.{function}_full" in sql and f"{function}.day" not in sql.replace("_full.day", "")
    return sql


def grant(signature: str) -> None:
    op.execute(f"revoke execute on function {signature} from public")
    op.execute(f"grant execute on function {signature} to anon, authenticated")


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(INDEX)
    op.execute(board_at())
    for statement in TABLES:
        op.execute(statement)
    op.execute(full("P4P", "gender"))
    op.execute(full("TEAMS", "kind"))
    op.execute("revoke execute on function ajr.p4p_full(text, date) from public")
    op.execute("revoke execute on function ajr.teams_full(text, date) from public")
    op.execute(P4P)
    op.execute(TEAMS)


def downgrade() -> None:
    """Downgrade schema."""
    for name, signature in (("P4P", "api.p4p(text, date)"), ("TEAMS", "api.teams(text, date)")):
        op.execute(f"drop function {signature}")
        op.execute(previous(name))
        grant(signature)
    op.execute("drop function ajr.p4p_full(text, date)")
    op.execute("drop function ajr.teams_full(text, date)")
    op.execute("drop table ajr.p4p_snapshot")
    op.execute("drop table ajr.teams_snapshot")
    op.execute(previous_board_at().replace("create function", "create or replace function"))
    op.execute("drop index ajr.ix_rating_change_weight_fought_on")
