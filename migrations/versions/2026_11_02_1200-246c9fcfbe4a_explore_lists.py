"""explore lists

The lists of the Explore pages: tournaments, contests, athletes and nations.
What would cost a scan of all contests per request is built by the rating job on
every run (ajr/rating/snapshot.py), next to today's rankings:

- ajr.competition_stats: per tournament, its real fights (no byes, no 0:00
  walkovers), how often the rating's favourite won and the upsets (a winner's
  chance of 35% or less).
- ajr.athlete_summary: per rated athlete, the weight, the latest contest and its
  tournament, the number of contests and today's place and score (null when not
  in a table).

The site reads them with:
- api.competitions(for_year, ranks): the tournaments of a year (all with null),
  latest first, with their stats.
- api.contests(for_year, only_weight, competition_id, upsets, sort, top, skip):
  a page of decided contests of a year (this one by default: all years at once
  are 200k contests, past the Data API's limit) and the number that match.
- api.athletes(q, country, gender, only_weight, sort, top, skip): a page of
  rated athletes and `total`; q matches the start of the family or given name,
  every word of it.
- api.nations(): nations with rated athletes, how many and how many in a table.

Revision ID: 246c9fcfbe4a
Revises: cdbd4287802e
Create Date: 2026-11-02 12:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "246c9fcfbe4a"
down_revision: Union[str, Sequence[str], None] = "cdbd4287802e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = [
    """
    create table ajr.competition_stats (
        competition_id integer primary key references ajr.competition (id),
        contests integer not null,
        accuracy double precision, -- share of fights the favourite won (null: no favourites)
        upsets integer not null
    )
    """,
    """
    create table ajr.athlete_summary (
        athlete_id integer primary key references ajr.athlete (id),
        weight text,
        last_contest date not null,
        last_competition_id integer references ajr.competition (id),
        contests integer not null,
        place integer, -- today, in the weight's table; null when not in it
        score integer
    )
    """,
    "create index ix_athlete_summary_weight on ajr.athlete_summary (weight)",
]

COMPETITIONS = """
create function api.competitions(for_year integer default null, ranks text[] default null)
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
    upsets integer
)
language sql stable security definer
set search_path = ''
as $$
    -- Individual tournaments with contests (no kata, no team events); ranks are
    -- rank_name values, e.g. array['Grand Slam', 'Grand Prix'].
    select cm.id, cm.name::text, cm.rank_name::text, cm.city::text, co.ioc::text, co.name::text,
           cm.date_from, cm.date_to, st.contests, st.accuracy, st.upsets
    from ajr.competition cm
    join ajr.competition_stats st on st.competition_id = cm.id
    left join ajr.country co on co.id = cm.country_id
    where not coalesce(cm.is_teams, false)
      and (competitions.for_year is null
           or cm.date_from between make_date(competitions.for_year, 1, 1)
                               and make_date(competitions.for_year, 12, 31))
      and (competitions.ranks is null or cm.rank_name = any(competitions.ranks))
    order by cm.date_from desc, cm.id
$$
"""

CONTESTS = """
create function api.contests(
    for_year integer default null,
    only_weight text default null,
    competition_id integer default null,
    upsets boolean default false,
    sort text default 'date-desc',
    top integer default 50,
    skip integer default 0
)
returns table (
    total bigint,
    contest_id integer,
    competition_id integer,
    competition text,
    day date,
    weight text,
    round text,
    winner_id integer,
    white_id integer,
    white_family_name text,
    white_given_name text,
    white_country text,
    white_chance double precision,
    white_change integer,
    blue_id integer,
    blue_family_name text,
    blue_given_name text,
    blue_country text,
    blue_chance double precision,
    blue_change integer
)
language sql stable security definer
set search_path = ''
as $$
    -- Decided real fights. sort: date-desc, date-asc or chance-asc (the least likely
    -- wins first). change: the rating's change in the contest. total: all that match.
    with matching as (
        select ct.id, ct.competition_id, cm.name, wr.fought_on, ct.weight, ct.round_name,
               ct.round, ct.fight_no, ct.winner_id,
               ct.white_id, wr.win_probability as white_chance,
               wr.rating_after - wr.rating_before as white_change,
               ct.blue_id, br.win_probability as blue_chance,
               br.rating_after - br.rating_before as blue_change,
               case when ct.winner_id = ct.white_id then wr.win_probability
                    else br.win_probability end as winner_chance
        from ajr.competition cm
        cross join (
            select coalesce(contests.for_year, extract(year from current_date)::integer) as value
        ) year
        join ajr.contest ct on ct.competition_id = cm.id
        join ajr.rating_change wr on wr.contest_id = ct.id and wr.athlete_id = ct.white_id
        join ajr.rating_change br on br.contest_id = ct.id and br.athlete_id = ct.blue_id
        where not coalesce(ct.bye, false) and ct.duration is distinct from '00:00:00'
          and cm.date_from between make_date(year.value, 1, 1) and make_date(year.value, 12, 31)
          and (contests.only_weight is null or ct.weight = contests.only_weight)
          and (contests.competition_id is null or ct.competition_id = contests.competition_id)
    ),
    picked as (
        select *, count(*) over () as total
        from matching
        where not contests.upsets or winner_chance <= 0.35
    )
    select p.total, p.id, p.competition_id, p.name::text, p.fought_on, p.weight::text,
           p.round_name::text, p.winner_id,
           p.white_id, w.family_name::text, w.given_name::text, wc.ioc::text,
           p.white_chance, round(p.white_change)::integer,
           p.blue_id, b.family_name::text, b.given_name::text, bc.ioc::text,
           p.blue_chance, round(p.blue_change)::integer
    from picked p
    join ajr.athlete w on w.id = p.white_id
    left join ajr.country wc on wc.id = w.country_id
    join ajr.athlete b on b.id = p.blue_id
    left join ajr.country bc on bc.id = b.country_id
    order by case when contests.sort = 'chance-asc' then p.winner_chance end,
             case when contests.sort = 'date-asc' then p.fought_on end,
             p.fought_on desc, p.competition_id, p.round nulls last, p.fight_no desc
    limit contests.top offset contests.skip
$$
"""

ATHLETES = """
create function api.athletes(
    q text default null,
    country text default null,
    gender text default null,
    only_weight text default null,
    sort text default 'name-asc',
    top integer default 50,
    skip integer default 0
)
returns table (
    total bigint,
    id integer,
    family_name text,
    given_name text,
    gender text,
    country text,
    birth_year integer,
    weight text,
    place integer,
    score integer,
    contests integer,
    last_contest date,
    last_competition_id integer,
    last_competition text
)
language sql stable security definer
set search_path = ''
as $$
    -- q: every word starts the family or the given name (any case). country: IOC.
    -- gender: male / female. sort: name-asc, name-desc, age-asc, age-desc, rating-desc.
    with words as (
        select word from unnest(string_to_array(lower(trim(coalesce(athletes.q, ''))), ' ')) word
        where word <> ''
    ),
    picked as (
        select a.id, a.family_name, a.given_name, a.gender, co.ioc, a.dob_year, s.weight,
               s.place, s.score, s.contests, s.last_contest, s.last_competition_id,
               count(*) over () as total
        from ajr.athlete_summary s
        join ajr.athlete a on a.id = s.athlete_id
        left join ajr.country co on co.id = a.country_id
        where (athletes.country is null or co.ioc = athletes.country)
          and (athletes.gender is null or a.gender = athletes.gender)
          and (athletes.only_weight is null or s.weight = athletes.only_weight)
          and not exists (
              select from words
              where lower(coalesce(a.family_name, '')) not like words.word || '%'
                and lower(coalesce(a.given_name, '')) not like words.word || '%'
          )
    )
    select p.total, p.id, p.family_name::text, p.given_name::text, p.gender::text, p.ioc::text,
           p.dob_year, p.weight, p.place, p.score, p.contests, p.last_contest,
           p.last_competition_id, cm.name::text
    from picked p
    left join ajr.competition cm on cm.id = p.last_competition_id
    order by case when athletes.sort = 'rating-desc' then p.score end desc nulls last,
             case when athletes.sort = 'age-asc' then p.dob_year end desc nulls last,
             case when athletes.sort = 'age-desc' then p.dob_year end nulls last,
             case when athletes.sort = 'name-desc' then p.family_name end desc,
             p.family_name, p.given_name, p.id
    limit athletes.top offset athletes.skip
$$
"""

NATIONS = """
create function api.nations()
returns table (country text, name text, athletes integer, active integer)
language sql stable security definer
set search_path = ''
as $$
    -- active: in a weight's table today
    select co.ioc::text, co.name::text, count(*)::integer, count(s.place)::integer
    from ajr.athlete_summary s
    join ajr.athlete a on a.id = s.athlete_id
    join ajr.country co on co.id = a.country_id
    where co.ioc is not null
    group by co.ioc, co.name
    order by co.name
$$
"""

FUNCTIONS = {
    "api.competitions(integer, text[])": COMPETITIONS,
    "api.contests(integer, text, integer, boolean, text, integer, integer)": CONTESTS,
    "api.athletes(text, text, text, text, text, integer, integer)": ATHLETES,
    "api.nations()": NATIONS,
}


def upgrade() -> None:
    """Upgrade schema."""
    for statement in TABLES:
        op.execute(statement)
    for signature, sql in FUNCTIONS.items():
        op.execute(sql)
        op.execute(f"revoke execute on function {signature} from public")
        op.execute(f"grant execute on function {signature} to anon, authenticated")


def downgrade() -> None:
    """Downgrade schema."""
    for signature in FUNCTIONS:
        op.execute(f"drop function {signature}")
    op.execute("drop table ajr.athlete_summary")
    op.execute("drop table ajr.competition_stats")
