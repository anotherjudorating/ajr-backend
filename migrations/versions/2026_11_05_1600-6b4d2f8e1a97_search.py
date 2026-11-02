"""search

api.search(q): the header's search box, one call per pause in typing. Up to 5
athletes, 3 tournaments and 3 nations, in that order:

- athletes: rated ones; every word of q starts their family or given name (as
  api.athletes). Those in a table today first, by score, then by their latest
  contest.
- tournaments: individual ones with contests, and coming World Tour ones; every
  word starts a word of the name. The coming ones first, the soonest first, then
  the latest.
- nations: with rated athletes; every word starts a word of the name, or q is the
  IOC code. The most athletes first.

Revision ID: 6b4d2f8e1a97
Revises: 3a6d9e21b7c4
Create Date: 2026-11-05 16:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6b4d2f8e1a97"
down_revision: Union[str, Sequence[str], None] = "3a6d9e21b7c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEARCH = """
create function api.search(q text)
returns table (
    kind text, -- athlete, tournament, nation
    id integer, -- athlete or competition id; null for a nation
    name text, -- the tournament's or the nation's
    family_name text,
    given_name text,
    country text, -- IOC: the athlete's, the host's, the nation's
    gender text,
    weight text, -- the athlete's
    date_from date,
    date_to date
)
language sql stable security definer
set search_path = ''
as $$
    with words as (
        select word from unnest(string_to_array(lower(trim(coalesce(search.q, ''))), ' ')) word
        where word <> ''
    ),
    -- every word starts a word of the text
    athletes as (
        select 'athlete'::text, a.id, null::text, a.family_name::text, a.given_name::text,
               co.ioc::text, a.gender::text, s.weight, null::date, null::date
        from ajr.athlete_summary s
        join ajr.athlete a on a.id = s.athlete_id
        left join ajr.country co on co.id = a.country_id
        where exists (select from words)
          and not exists (
              select from words
              where lower(coalesce(a.family_name, '')) not like words.word || '%'
                and lower(coalesce(a.given_name, '')) not like words.word || '%'
          )
        order by s.score desc nulls last, s.last_contest desc
        limit 5
    ),
    tournaments as (
        select 'tournament'::text, cm.id, cm.name::text, null::text, null::text, co.ioc::text,
               null::text, null::text, cm.date_from, cm.date_to
        from ajr.competition cm
        left join ajr.country co on co.id = cm.country_id
        where exists (select from words)
          and not coalesce(cm.is_teams, false)
          and (exists (select from ajr.competition_stats st where st.competition_id = cm.id)
               or (cm.date_from >= current_date
                   and cm.rank_name in ('Olympic Games', 'World Championships', 'Masters',
                                        'Grand Slam', 'Grand Prix')))
          and not exists (
              select from words
              where not lower(' ' || coalesce(cm.name, '')) like '% ' || words.word || '%'
          )
        order by cm.date_from >= current_date desc,
                 case when cm.date_from >= current_date then cm.date_from end,
                 cm.date_from desc
        limit 3
    ),
    nations as (
        select 'nation'::text, null::integer, co.name::text, null::text, null::text, co.ioc::text,
               null::text, null::text, null::date, null::date
        from ajr.country co
        join (
            select a.country_id, count(*) as athletes
            from ajr.athlete_summary s
            join ajr.athlete a on a.id = s.athlete_id
            group by a.country_id
        ) rated on rated.country_id = co.id
        where exists (select from words)
          and co.ioc is not null
          and (lower(co.ioc) = lower(trim(search.q))
               or not exists (
                   select from words
                   where not lower(' ' || coalesce(co.name, '')) like '% ' || words.word || '%'
               ))
        order by rated.athletes desc
        limit 3
    )
    select * from athletes
    union all select * from tournaments
    union all select * from nations
$$
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(SEARCH)
    op.execute("revoke execute on function api.search(text) from public")
    op.execute("grant execute on function api.search(text) to anon, authenticated")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop function api.search(text)")
