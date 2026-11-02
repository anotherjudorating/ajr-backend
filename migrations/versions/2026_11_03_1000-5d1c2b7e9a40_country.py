"""country

What the country page needs, and the debut of an athlete at a tournament.

Built ahead (a nation's rating on a past day costs about a second per call):
- ajr.nation_snapshot: today's nations rankings (men, women, mixed), built by the
  rating job from today's tables (ajr/rating/snapshot.py), as api.teams ranks them.
- ajr.nation_history: every week's mixed nations ranking, from the records job's
  weekly tables (ajr/records/weekly.py); weeks where every weight has a table.

The site reads them with:
- api.country(ioc): the nation, its rated athletes, today's place in the three
  nations rankings and its mixed rating, the mixed rating and place 90 days and 6
  months ago (the latest week before), its best score and the average of its 8 best.
- api.country_leaders(ioc): its best athlete in every weight today, with their place.
- api.country_history(ioc): its weekly mixed rating and place.
- api.country_tournaments(ioc, top): the latest tournaments its athletes fought
  at and their medals there (ajr.result_label: only in brackets with one final).

api.competition_results gets `debut`: the athlete's first rated contest was at this
tournament. Their score starts low (the rating's doubt about them is high), so a
debut's gain says little; the site leaves debuts out of the biggest gains.

Revision ID: 5d1c2b7e9a40
Revises: 00e6280e8753
Create Date: 2026-11-03 10:00:00

"""

import importlib.util
from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5d1c2b7e9a40"
down_revision: Union[str, Sequence[str], None] = "00e6280e8753"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = [
    """
    create table ajr.nation_snapshot (
        kind text not null, -- men, women, mixed
        country_id integer not null references ajr.country (id),
        place integer not null,
        rating integer not null,
        primary key (kind, country_id)
    )
    """,
    """
    create table ajr.nation_history (
        day date not null, -- a Sunday
        country_id integer not null references ajr.country (id),
        place integer not null,
        rating integer not null,
        primary key (day, country_id)
    )
    """,
    "create index ix_nation_history_country_id on ajr.nation_history (country_id, day)",
]

# Men, then women, lightest first.
WEIGHT_ORDER = (
    "array_position(array['-60', '-66', '-73', '-81', '-90', '-100', '+100',"
    " '-48', '-52', '-57', '-63', '-70', '-78', '+78'], {})"
)

COUNTRY = """
create function api.country(ioc text)
returns table (
    country text,
    name text,
    athletes integer,
    place integer,
    place_men integer,
    place_women integer,
    rating integer,
    place_90d integer,
    rating_90d integer,
    place_6m integer,
    rating_6m integer,
    top1 integer,
    top8 integer
)
language sql stable security definer
set search_path = ''
as $$
    -- athletes: rated ever. The past: the latest week on or before the day.
    select co.ioc::text, co.name::text,
           (select count(*)::integer
            from ajr.athlete_summary s
            join ajr.athlete a on a.id = s.athlete_id
            where a.country_id = co.id),
           mixed.place, men.place, women.place, mixed.rating,
           d90.place, d90.rating, m6.place, m6.rating,
           best.top1, best.top8
    from ajr.country co
    left join ajr.nation_snapshot mixed on mixed.kind = 'mixed' and mixed.country_id = co.id
    left join ajr.nation_snapshot men on men.kind = 'men' and men.country_id = co.id
    left join ajr.nation_snapshot women on women.kind = 'women' and women.country_id = co.id
    left join ajr.nation_history d90
        on d90.country_id = co.id
       and d90.day = (select max(h.day) from ajr.nation_history h where h.day <= current_date - 90)
    left join ajr.nation_history m6
        on m6.country_id = co.id
       and m6.day = (select max(h.day) from ajr.nation_history h
                     where h.day <= current_date - interval '6 months')
    cross join lateral (
        select max(top.score)::integer as top1, round(avg(top.score))::integer as top8
        from (
            select l.score
            from ajr.leaderboard_snapshot l
            join ajr.athlete a on a.id = l.athlete_id
            where a.country_id = co.id
            order by l.score desc
            limit 8
        ) top
    ) best
    where co.ioc = country.ioc
$$
"""

COUNTRY_LEADERS = f"""
create function api.country_leaders(ioc text)
returns table (
    weight text,
    athlete_id integer,
    family_name text,
    given_name text,
    place integer,
    score integer
)
language sql stable security definer
set search_path = ''
as $$
    select b.weight, b.athlete_id, b.family_name, b.given_name, b.place, b.score
    from (
        select distinct on (l.weight) l.weight::text, l.athlete_id, a.family_name::text,
               a.given_name::text, l.place::integer, l.score::integer
        from ajr.leaderboard_snapshot l
        join ajr.athlete a on a.id = l.athlete_id
        join ajr.country co on co.id = a.country_id
        where co.ioc = country_leaders.ioc
        order by l.weight, l.score desc
    ) b
    order by {WEIGHT_ORDER.format("b.weight")}
$$
"""

COUNTRY_HISTORY = """
create function api.country_history(ioc text)
returns table (day date, place integer, rating integer)
language sql stable security definer
set search_path = ''
as $$
    select h.day, h.place, h.rating
    from ajr.nation_history h
    join ajr.country co on co.id = h.country_id
    where co.ioc = country_history.ioc
    order by h.day
$$
"""

COUNTRY_TOURNAMENTS = """
create function api.country_tournaments(ioc text, top integer default 10)
returns table (
    id integer,
    name text,
    rank_name text,
    date_from date,
    athletes integer,
    gold integer,
    silver integer,
    bronze integer
)
language sql stable security definer
set search_path = ''
as $$
    -- The nation's athletes' contests, the latest tournaments among them, how each
    -- athlete ended there (as api.competition_results) and the medals.
    with fights as (
        select ct.competition_id, ct.weight, ct.round, ct.fight_no, ct.round_name,
               rc.athlete_id, rc.won, rc.fought_on
        from ajr.country co
        join ajr.athlete a on a.country_id = co.id
        join ajr.rating_change rc on rc.athlete_id = a.id
        join ajr.contest ct on ct.id = rc.contest_id
        where co.ioc = country_tournaments.ioc
    ),
    recent as (
        select f.competition_id
        from fights f
        join ajr.competition cm on cm.id = f.competition_id
        where not coalesce(cm.is_teams, false)
        group by f.competition_id
        order by max(f.fought_on) desc
        limit country_tournaments.top
    ),
    one_final as (
        select ct.competition_id, ct.weight
        from ajr.contest ct
        join recent r on r.competition_id = ct.competition_id
        group by ct.competition_id, ct.weight
        having count(*) filter (where ct.round_name = 'Final') = 1
    ),
    ended as (
        select f.competition_id, f.athlete_id,
               case when bool_or(o.weight is not null)
                    then ajr.result_label(
                        (array_agg(f.round_name order by f.round nulls last, f.fight_no desc))[1],
                        (array_agg(f.won order by f.round nulls last, f.fight_no desc))[1])
               end as result
        from fights f
        join recent r on r.competition_id = f.competition_id
        left join one_final o on o.competition_id = f.competition_id and o.weight = f.weight
        group by f.competition_id, f.athlete_id, f.weight
    )
    select cm.id, cm.name::text, cm.rank_name::text, cm.date_from,
           count(distinct e.athlete_id)::integer,
           count(*) filter (where e.result = 'gold')::integer,
           count(*) filter (where e.result = 'silver')::integer,
           count(*) filter (where e.result = 'bronze')::integer
    from ended e
    join ajr.competition cm on cm.id = e.competition_id
    group by cm.id
    order by cm.date_from desc, cm.id
$$
"""


def load_migration(name: str):
    """An earlier migration's module, to reuse its SQL."""
    path = next(Path(__file__).parent.glob(f"*{name}.py"))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def previous_competition_results() -> str:
    return load_migration("00e6280e8753_tournament").COMPETITION_RESULTS


def competition_results() -> str:
    """api.competition_results with `debut`: no rated contest of the athlete before
    their first one here."""
    sql = (
        previous_competition_results()
        .replace("    wins integer\n)", "    wins integer,\n    debut boolean\n)")
        .replace(
            "               count(*) as contests,",
            "               min(seq) as first_seq,\n               count(*) as contests,",
        )
        .replace(
            "           b.contests::integer, b.wins::integer\n",
            "           b.contests::integer, b.wins::integer,\n"
            "           not exists (select from ajr.rating_change p\n"
            "                       where p.athlete_id = b.athlete_id and p.seq < b.first_seq)\n",
        )
    )
    assert sql.count("debut") == 1 and "first_seq" in sql and "p.seq" in sql
    return sql


FUNCTIONS = {
    "api.country(text)": COUNTRY,
    "api.country_leaders(text)": COUNTRY_LEADERS,
    "api.country_history(text)": COUNTRY_HISTORY,
    "api.country_tournaments(text, integer)": COUNTRY_TOURNAMENTS,
}
RESULTS = "api.competition_results(integer)"


def grant(signature: str) -> None:
    op.execute(f"revoke execute on function {signature} from public")
    op.execute(f"grant execute on function {signature} to anon, authenticated")


def upgrade() -> None:
    """Upgrade schema."""
    for statement in TABLES:
        op.execute(statement)
    for signature, sql in FUNCTIONS.items():
        op.execute(sql)
        grant(signature)
    op.execute(f"drop function {RESULTS}")  # its columns change
    op.execute(competition_results())
    grant(RESULTS)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"drop function {RESULTS}")
    op.execute(previous_competition_results())
    grant(RESULTS)
    for signature in FUNCTIONS:
        op.execute(f"drop function {signature}")
    op.execute("drop table ajr.nation_history")
    op.execute("drop table ajr.nation_snapshot")
