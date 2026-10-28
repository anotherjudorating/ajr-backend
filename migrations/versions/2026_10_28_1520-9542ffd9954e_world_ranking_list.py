"""world ranking list

The current IJF World Ranking List next to our places: wrl_ranking, and a wrl_place
column in api.leaderboard (filled for today's table only) and api.athlete.

Revision ID: 9542ffd9954e
Revises: 4f5a4bb0ff65
Create Date: 2026-10-28 15:20:24.298652

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '9542ffd9954e'
down_revision: Union[str, Sequence[str], None] = '4f5a4bb0ff65'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def leaderboard(with_wrl: bool) -> str:
    wrl_column = ",\n    wrl_place integer" if with_wrl else ""
    wrl_value = ",\n           w.place" if with_wrl else ""
    # The WRL is the current one: no place to show for a table of another day.
    wrl_join = (
        """
    left join ajr.wrl_ranking w
        on w.athlete_id = now.athlete_id
       and w.weight = leaderboard.weight
       and leaderboard.day = current_date"""
        if with_wrl
        else ""
    )
    return f"""
create function api.leaderboard(weight text, day date default current_date)
returns table (
    place bigint,
    athlete_id integer,
    family_name text,
    given_name text,
    country text,
    rating integer,
    rd integer,
    score integer,
    last_contest date,
    places_up_90d integer,
    score_change_90d integer,
    score_change_6m integer{wrl_column}
)
language sql stable security definer
set search_path = ''
as $$
    -- Changes are null when the athlete was not in the table back then (new or returning).
    select now.place,
           now.athlete_id,
           a.family_name::text,
           a.given_name::text,
           co.ioc::text,
           round(now.rating)::integer,
           round(now.rd)::integer,
           round(now.score)::integer,
           now.last_contest,
           (d90.place - now.place)::integer,
           round(now.score - d90.score)::integer,
           round(now.score - d6m.score)::integer{wrl_value}
    from ajr.board_at(leaderboard.weight, leaderboard.day) now
    join ajr.athlete a on a.id = now.athlete_id
    left join ajr.country co on co.id = a.country_id
    left join ajr.board_at(leaderboard.weight, leaderboard.day - 90) d90
        on d90.athlete_id = now.athlete_id
    left join ajr.board_at(leaderboard.weight, (leaderboard.day - interval '6 months')::date) d6m
        on d6m.athlete_id = now.athlete_id{wrl_join}
    order by now.place, a.family_name
$$
"""


def athlete(with_wrl: bool) -> str:
    wrl_column = ",\n    wrl_place integer" if with_wrl else ""
    wrl_value = ",\n           w.place" if with_wrl else ""
    wrl_join = (
        """
    left join ajr.wrl_ranking w on w.athlete_id = a.id and w.weight = latest.weight"""
        if with_wrl
        else ""
    )
    return f"""
create function api.athlete(athlete_id integer)
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
    contests bigint{wrl_column}
)
language sql stable security definer
set search_path = ''
as $$
    -- place is null when the athlete is hidden (a year without contests) or never rated.
    select a.id,
           a.family_name::text,
           a.given_name::text,
           a.gender::text,
           a.dob_year,
           co.ioc::text,
           co.name::text,
           latest.weight::text,
           round(latest.rating_after)::integer,
           round(rd.value)::integer,
           round(latest.rating_after - s.rd_factor * rd.value)::integer,
           board.place,
           latest.fought_on,
           (select count(*) from ajr.rating_change rc where rc.athlete_id = a.id){wrl_value}
    from ajr.athlete a
    cross join ajr.rating_settings s
    left join ajr.country co on co.id = a.country_id
    left join ajr.rating_change latest
        on latest.athlete_id = a.id and latest.next_fought_on = date '9999-12-31'
    left join lateral (
        select least(s.max_rd, sqrt(latest.rd_after ^ 2
                                    + s.rd_growth ^ 2 * (current_date - latest.fought_on)))
            as value
    ) rd on true
    left join lateral ajr.board_at(latest.weight, current_date) board
        on board.athlete_id = a.id{wrl_join}
    where a.id = athlete.athlete_id
$$
"""


def replace_api_functions(with_wrl: bool) -> None:
    """Their result columns change, so they are dropped and created again."""
    op.execute("drop function api.leaderboard(text, date)")
    op.execute("drop function api.athlete(integer)")
    op.execute(leaderboard(with_wrl))
    op.execute(athlete(with_wrl))
    for function in ("api.leaderboard(text, date)", "api.athlete(integer)"):
        op.execute(f"revoke execute on function {function} from public")
        op.execute(f"grant execute on function {function} to anon, authenticated")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "wrl_ranking",
        sa.Column("athlete_id", sa.Integer(), nullable=False),
        sa.Column("weight", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("place", sa.Integer(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["athlete_id"], ["ajr.athlete.id"]),
        sa.PrimaryKeyConstraint("athlete_id", "weight"),
        schema="ajr",
    )
    replace_api_functions(with_wrl=True)


def downgrade() -> None:
    """Downgrade schema."""
    replace_api_functions(with_wrl=False)
    op.drop_table("wrl_ranking", schema="ajr")
