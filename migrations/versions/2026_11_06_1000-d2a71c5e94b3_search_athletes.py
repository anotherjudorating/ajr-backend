"""search athletes

api.search_athletes(q, only_weight, top): the head-to-head's athlete boxes. Every
rated athlete can be found (every word of q starts their family or given name, as
api.search); the weight picked orders them: its table today first, by place, then
the athletes in another weight's table, by score, then the rest, the latest to
fight first. `place` and `score` are today's, null when not in a table.

Revision ID: d2a71c5e94b3
Revises: 6b4d2f8e1a97
Create Date: 2026-11-06 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2a71c5e94b3"
down_revision: Union[str, Sequence[str], None] = "6b4d2f8e1a97"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEARCH_ATHLETES = """
create function api.search_athletes(
    q text, only_weight text default null, top integer default 8
)
returns table (
    id integer,
    family_name text,
    given_name text,
    country text,
    gender text,
    weight text,
    place integer,
    score integer
)
language sql stable security definer
set search_path = ''
as $$
    with words as (
        select word
        from unnest(string_to_array(lower(trim(coalesce(search_athletes.q, ''))), ' ')) word
        where word <> ''
    )
    select a.id, a.family_name::text, a.given_name::text, co.ioc::text, a.gender::text,
           s.weight, s.place, s.score
    from ajr.athlete_summary s
    join ajr.athlete a on a.id = s.athlete_id
    left join ajr.country co on co.id = a.country_id
    where exists (select from words)
      and not exists (
          select from words
          where lower(coalesce(a.family_name, '')) not like words.word || '%'
            and lower(coalesce(a.given_name, '')) not like words.word || '%'
      )
    order by s.weight is not distinct from search_athletes.only_weight and s.place is not null desc,
             s.place is not null desc,
             case when s.weight is not distinct from search_athletes.only_weight then s.place end,
             s.score desc nulls last,
             s.last_contest desc
    limit search_athletes.top
$$
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(SEARCH_ATHLETES)
    op.execute("revoke execute on function api.search_athletes(text, text, integer) from public")
    op.execute(
        "grant execute on function api.search_athletes(text, text, integer) to anon, authenticated"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop function api.search_athletes(text, text, integer)")
