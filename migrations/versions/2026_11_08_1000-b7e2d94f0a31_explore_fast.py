"""explore fast

The Explore lists timed out on a cold cache, most when the sort changed (each sort
is a new query): api.contests looked up both athletes' rating rows, names and
nations for every contest of the year (~150 thousand pages a call), api.athletes
looked up the name and nation of every rated athlete (~55 thousand).

- ajr.contest_list: every real fight (no byes, no 0:00 walkovers), both athletes
  with their names, nations, chances and rating changes, and the winner's chance;
  rebuilt by the rating job for the years a run changed (ajr/rating/snapshot.py).
- ajr.athlete_summary gets the athlete's names, gender, nation, year of birth and
  latest competition's name (it is rebuilt on every run anyway).
- api.contests and api.athletes read those tables only; same arguments, same rows.
  api.contests also orders the contests of one day, competition, round and fight
  number (one per weight) by weight: before, their order could change between two
  pages, which then repeated some and skipped others.

Revision ID: b7e2d94f0a31
Revises: a4c8e2f61d05
Create Date: 2026-11-08 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e2d94f0a31"
down_revision: Union[str, Sequence[str], None] = "a4c8e2f61d05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONTEST_LIST = """
create table ajr.contest_list (
    contest_id integer primary key,
    competition_id integer not null,
    competition text,
    year integer not null, -- of the competition's first day
    day date not null,
    weight text,
    round text,
    round_no integer, -- judobase counts down to the final, 0
    fight_no integer,
    winner_id integer not null,
    white_id integer not null,
    white_family_name text,
    white_given_name text,
    white_country text,
    white_chance double precision not null,
    white_change integer not null,
    blue_id integer not null,
    blue_family_name text,
    blue_given_name text,
    blue_country text,
    blue_chance double precision not null,
    blue_change integer not null,
    winner_chance double precision not null
)
"""

# As ajr/rating/snapshot.py builds it (kept here so the migration stays as it was).
FILL_CONTEST_LIST = """
insert into ajr.contest_list
select ct.id, ct.competition_id, cm.name, extract(year from cm.date_from)::integer,
       w.fought_on, ct.weight, ct.round_name, ct.round, ct.fight_no, ct.winner_id,
       ct.white_id, wa.family_name, wa.given_name, wc.ioc, w.win_probability,
       round(w.rating_after - w.rating_before)::integer,
       ct.blue_id, ba.family_name, ba.given_name, bc.ioc, b.win_probability,
       round(b.rating_after - b.rating_before)::integer,
       case when ct.winner_id = ct.white_id then w.win_probability else b.win_probability end
from ajr.competition cm
join ajr.contest ct on ct.competition_id = cm.id
join ajr.rating_change w on w.contest_id = ct.id and w.athlete_id = ct.white_id
join ajr.rating_change b on b.contest_id = ct.id and b.athlete_id = ct.blue_id
join ajr.athlete wa on wa.id = ct.white_id
left join ajr.country wc on wc.id = wa.country_id
join ajr.athlete ba on ba.id = ct.blue_id
left join ajr.country bc on bc.id = ba.country_id
where not coalesce(ct.bye, false) and ct.duration is distinct from '00:00:00'
"""

SUMMARY_COLUMNS = """
alter table ajr.athlete_summary
    add column family_name text,
    add column given_name text,
    add column gender text,
    add column country text,
    add column birth_year integer,
    add column last_competition text
"""

FILL_SUMMARY = """
update ajr.athlete_summary s
set family_name = a.family_name, given_name = a.given_name, gender = a.gender,
    birth_year = a.dob_year,
    country = (select co.ioc from ajr.country co where co.id = a.country_id),
    last_competition = (select cm.name from ajr.competition cm where cm.id = s.last_competition_id)
from ajr.athlete a
where a.id = s.athlete_id
"""

CONTESTS = """
create or replace function api.contests(
    for_year integer default null,
    only_weight text default null,
    competition_id integer default null,
    upsets boolean default false,
    q text default null,
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
    -- Decided real fights of a year (this one by default), from ajr.contest_list.
    -- q: every word starts a family or given name of one of the two athletes.
    -- sort: date-desc, date-asc or chance-asc (the least likely wins first).
    -- total: all that match.
    with words as (
        select word from unnest(string_to_array(lower(trim(coalesce(contests.q, ''))), ' ')) word
        where word <> ''
    ),
    picked as (
        select l.*, count(*) over () as total
        from ajr.contest_list l
        where l.year = coalesce(contests.for_year, extract(year from current_date)::integer)
          and (contests.only_weight is null or l.weight = contests.only_weight)
          and (contests.competition_id is null or l.competition_id = contests.competition_id)
          and (not contests.upsets or l.winner_chance <= 0.35)
          and (contests.q is null
               or not exists (
                   select from words
                   where lower(coalesce(l.white_family_name, '')) not like words.word || '%'
                     and lower(coalesce(l.white_given_name, '')) not like words.word || '%'
               )
               or not exists (
                   select from words
                   where lower(coalesce(l.blue_family_name, '')) not like words.word || '%'
                     and lower(coalesce(l.blue_given_name, '')) not like words.word || '%'
               ))
    )
    select p.total, p.contest_id, p.competition_id, p.competition, p.day, p.weight, p.round,
           p.winner_id, p.white_id, p.white_family_name, p.white_given_name, p.white_country,
           p.white_chance, p.white_change, p.blue_id, p.blue_family_name, p.blue_given_name,
           p.blue_country, p.blue_chance, p.blue_change
    from picked p
    order by case when contests.sort = 'chance-asc' then p.winner_chance end,
             case when contests.sort = 'date-asc' then p.day end,
             p.day desc, p.competition_id, p.round_no nulls last, p.fight_no desc,
             p.weight, p.contest_id -- one order, so the pages neither repeat nor skip
    limit contests.top offset contests.skip
$$
"""

ATHLETES = """
create or replace function api.athletes(
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
        select s.*, count(*) over () as total
        from ajr.athlete_summary s
        where (athletes.country is null or s.country = athletes.country)
          and (athletes.gender is null or s.gender = athletes.gender)
          and (athletes.only_weight is null or s.weight = athletes.only_weight)
          and not exists (
              select from words
              where lower(coalesce(s.family_name, '')) not like words.word || '%'
                and lower(coalesce(s.given_name, '')) not like words.word || '%'
          )
    )
    select p.total, p.athlete_id, p.family_name, p.given_name, p.gender, p.country,
           p.birth_year, p.weight, p.place, p.score, p.contests, p.last_contest,
           p.last_competition_id, p.last_competition
    from picked p
    order by case when athletes.sort = 'rating-desc' then p.score end desc nulls last,
             case when athletes.sort = 'age-asc' then p.birth_year end desc nulls last,
             case when athletes.sort = 'age-desc' then p.birth_year end nulls last,
             case when athletes.sort = 'name-desc' then p.family_name end desc,
             p.family_name, p.given_name, p.athlete_id
    limit athletes.top offset athletes.skip
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
    op.execute(CONTEST_LIST)
    op.execute("create index ix_contest_list_year on ajr.contest_list (year)")
    op.execute(FILL_CONTEST_LIST)
    op.execute(SUMMARY_COLUMNS)
    op.execute(FILL_SUMMARY)
    op.execute(CONTESTS)
    op.execute(ATHLETES)


def downgrade() -> None:
    """Downgrade schema."""
    previous = load_migration("246c9fcfbe4a_explore_lists")
    for sql in (previous.CONTESTS, previous.ATHLETES):
        op.execute(sql.replace("create function", "create or replace function"))
    op.execute(
        "alter table ajr.athlete_summary drop column family_name, drop column given_name, "
        "drop column gender, drop column country, drop column birth_year, "
        "drop column last_competition"
    )
    op.execute("drop table ajr.contest_list")
