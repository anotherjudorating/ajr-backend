"""tournament country facts

The tournament and country pages read their facts from tables the rating job keeps
(docs/audits/2026-11-08-b2-plan.md), as B-1 did for the athlete's page:

- ajr.contest_list: both sides' scores before and after, and real_fight; the
  walkovers of the rated categories join it (real_fight false, no chance, change or
  score), so the bracket (api.competition_contests) reads this table alone. The
  publish builds it in (competition, weight, round, number) order (SWAP_ORDER).
  api.contests lists real fights only (here, as the walkovers arrive with the next
  publish).
- ajr.athlete_competition: the athlete's names, gender and nation (api.competition_results),
  built in (competition, weight, athlete) order; a plain index on the competition.
- ajr.competition_stats: what the tournaments list shows of a tournament (api.competitions).
- ajr.nation_summary: the country page's numbers (places and ratings in the nations'
  tables today, 90 days and 6 months ago, best scores).
- ajr.nation_competition: the nation's IOC code and the tournament's first day, indexed
  (api.country_tournaments without the generic-plan trap), built in that order.
- ajr.leaderboard_snapshot: an index for the best athlete of a nation in each weight.
- ajr.medal_chance: names and nation (api.competition_chances).

The columns are empty until the next rating run and the publish after it; the
functions switch to them in the next migration, which also drops the indexes they
supersede.

Revision ID: c9f4e6a1b352
Revises: b8e3d5f0a241
Create Date: 2026-11-15 10:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9f4e6a1b352"
down_revision: Union[str, Sequence[str], None] = "b8e3d5f0a241"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NULLABLE = ["white_chance", "white_change", "blue_chance", "blue_change", "winner_chance"]
COLUMNS = {
    "contest_list": [
        ("white_score_before", "integer"),
        ("white_score_after", "integer"),
        ("blue_score_before", "integer"),
        ("blue_score_after", "integer"),
    ],
    "athlete_competition": [
        ("family_name", "text"),
        ("given_name", "text"),
        ("gender", "text"),
        ("country", "text"),
    ],
    "competition_stats": [
        ("name", "text"),
        ("rank_name", "text"),
        ("city", "text"),
        ("country", "text"),
        ("country_name", "text"),
        ("date_from", "date"),
        ("date_to", "date"),
    ],
    "nation_summary": [
        ("place", "integer"),
        ("place_men", "integer"),
        ("place_women", "integer"),
        ("rating", "integer"),
        ("place_90d", "integer"),
        ("rating_90d", "integer"),
        ("place_6m", "integer"),
        ("rating_6m", "integer"),
        ("top1", "integer"),
        ("top8", "integer"),
    ],
    "nation_competition": [("country", "text"), ("date_from", "date")],
    "medal_chance": [("family_name", "text"), ("given_name", "text"), ("country", "text")],
}

CONTESTS = """
create or replace function api.contests(for_year integer DEFAULT NULL::integer, only_weight text DEFAULT NULL::text, competition_id integer DEFAULT NULL::integer, upsets boolean DEFAULT false, q text DEFAULT NULL::text, sort text DEFAULT 'date-desc'::text, top integer DEFAULT 50, skip integer DEFAULT 0)
 RETURNS TABLE(total bigint, contest_id integer, competition_id integer, competition text, day date, weight text, round text, winner_id integer, white_id integer, white_family_name text, white_given_name text, white_country text, white_chance double precision, white_change integer, blue_id integer, blue_family_name text, blue_given_name text, blue_country text, blue_chance double precision, blue_change integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
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
        -- walkovers are in the list for the tournament page, not here
        where l.year = coalesce(contests.for_year, extract(year from current_date)::integer)
          and l.real_fight
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
$function$
"""

OLD_CONTESTS = """
create or replace function api.contests(for_year integer DEFAULT NULL::integer, only_weight text DEFAULT NULL::text, competition_id integer DEFAULT NULL::integer, upsets boolean DEFAULT false, q text DEFAULT NULL::text, sort text DEFAULT 'date-desc'::text, top integer DEFAULT 50, skip integer DEFAULT 0)
 RETURNS TABLE(total bigint, contest_id integer, competition_id integer, competition text, day date, weight text, round text, winner_id integer, white_id integer, white_family_name text, white_given_name text, white_country text, white_chance double precision, white_change integer, blue_id integer, blue_family_name text, blue_given_name text, blue_country text, blue_chance double precision, blue_change integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
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
$function$
"""


def upgrade() -> None:
    """Upgrade schema."""
    for table, columns in COLUMNS.items():
        op.execute(
            f"alter table ajr.{table} "
            + ", ".join(f"add column {name} {kind}" for name, kind in columns)
        )
    op.execute(
        "alter table ajr.contest_list "
        + ", ".join(f"alter column {name} drop not null" for name in NULLABLE)
        + ", add column real_fight boolean not null default true"  # every row is rated today
    )
    op.execute("alter table ajr.contest_list alter column real_fight drop default")
    op.execute(
        "create index ix_athlete_competition_competition on ajr.athlete_competition (competition_id)"
    )
    op.execute(
        "create index ix_leaderboard_snapshot_country_leaders on ajr.leaderboard_snapshot "
        "(country, weight, score desc, place) include (athlete_id, family_name, given_name)"
    )
    op.execute(
        "create index ix_nation_competition_country_date on ajr.nation_competition "
        "(country, date_from desc, competition_id)"
    )
    op.execute(CONTESTS)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(OLD_CONTESTS)
    op.execute("drop index ajr.ix_nation_competition_country_date")
    op.execute("drop index ajr.ix_leaderboard_snapshot_country_leaders")
    op.execute("drop index ajr.ix_athlete_competition_competition")
    op.execute("delete from ajr.contest_list where not real_fight")
    op.execute(
        "alter table ajr.contest_list drop column real_fight, "
        + ", ".join(f"alter column {name} set not null" for name in NULLABLE)
    )
    for table, columns in reversed(COLUMNS.items()):
        op.execute(
            f"alter table ajr.{table} " + ", ".join(f"drop column {name}" for name, _ in columns)
        )
