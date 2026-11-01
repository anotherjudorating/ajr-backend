"""contest

api.contest(contest_id): one contest for its page. The competition, the weight
and round, the time and golden score; both athletes with their scores (ippon,
waza-ari, yuko, shido), their place in the weight's table the day before and
their rating, RD and score before and after, with the chance the rating gave
each. The road to it and the earlier meetings come from api.athlete_history.

Revision ID: cdbd4287802e
Revises: 06a683118231
Create Date: 2026-11-02 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cdbd4287802e"
down_revision: Union[str, Sequence[str], None] = "06a683118231"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def side_columns(side: str) -> str:
    """The columns of one athlete of the contest (blue or white)."""
    return f"""
    {side}_id integer,
    {side}_family_name text,
    {side}_given_name text,
    {side}_country text,
    {side}_place_before bigint,
    {side}_ippon integer,
    {side}_waza integer,
    {side}_yuko integer,
    {side}_shido integer,
    {side}_win_probability double precision,
    {side}_rating_before integer,
    {side}_rating_after integer,
    {side}_rd_before integer,
    {side}_rd_after integer,
    {side}_score_before integer,
    {side}_score_after integer"""


def side_values(side: str, letter: str) -> str:
    """Their values: `letter` is judobase's suffix for the side's scores (b, w)."""
    return f"""
           ct.{side}_id,
           {side}_a.family_name::text,
           {side}_a.given_name::text,
           {side}_co.ioc::text,
           (select b.place
            from ajr.board_at({side}_rc.weight, {side}_rc.fought_on - 1) b
            where b.athlete_id = ct.{side}_id),
           ct.ippon_{letter},
           ct.waza_{letter},
           ct.yuko_{letter},
           ct.penalty_{letter},
           {side}_rc.win_probability,
           round({side}_rc.rating_before)::integer,
           round({side}_rc.rating_after)::integer,
           round({side}_rc.rd_before)::integer,
           round({side}_rc.rd_after)::integer,
           round({side}_rc.rating_before - s.rd_factor * {side}_rc.rd_before)::integer,
           round({side}_rc.rating_after - s.rd_factor * {side}_rc.rd_after)::integer"""


def side_joins(side: str) -> str:
    return f"""
    left join ajr.athlete {side}_a on {side}_a.id = ct.{side}_id
    left join ajr.country {side}_co on {side}_co.id = {side}_a.country_id
    left join ajr.rating_change {side}_rc
        on {side}_rc.contest_id = ct.id and {side}_rc.athlete_id = ct.{side}_id"""


CONTEST = f"""
create function api.contest(contest_id integer)
returns table (
    contest_id integer,
    competition_id integer,
    competition text,
    competition_rank text,
    city text,
    day date,
    weight text,
    round text,
    duration text,
    golden_score boolean,
    winner_id integer,{side_columns("white")},{side_columns("blue")}
)
language sql stable security definer
set search_path = ''
as $$
    -- Place: in the weight's table the day before the contest. No rating rows for
    -- a contest that was not fought (bye, not decided yet).
    select ct.id,
           cm.id,
           cm.name::text,
           cm.rank_name::text,
           cm.city::text,
           coalesce(white_rc.fought_on, ct.started_at::date, cm.date_from),
           ct.weight::text,
           ct.round_name::text,
           ct.duration::text,
           ct.golden_score,
           ct.winner_id,{side_values("white", "w")},{side_values("blue", "b")}
    from ajr.contest ct
    join ajr.competition cm on cm.id = ct.competition_id
    cross join ajr.rating_settings s{side_joins("white")}{side_joins("blue")}
    where ct.id = contest.contest_id
$$
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(CONTEST)
    op.execute("revoke execute on function api.contest(integer) from public")
    op.execute("grant execute on function api.contest(integer) to anon, authenticated")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop function api.contest(integer)")
