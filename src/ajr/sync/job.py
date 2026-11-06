"""Copy judobase into our database.

Order of work:
1. Olympic cycles (from a local file), countries and competitions are saved every run,
   and the athletes' second ids (from a local file, see save_aliases).
2. Contests are fetched only for competitions that need it:
   - competitions happening now or in the next two weeks (draws and live results),
   - past competitions whose data changed in judobase since we last saved them,
   - every past competition with results when running with --full.
3. For each of those competitions, in one transaction: new athletes, the contests,
   and removal of contests judobase no longer lists. An empty answer for a
   competition we already have contests of is taken as a judobase glitch: nothing
   is removed and the competition is tried again next run.

Every write is an upsert keyed by the judobase id, so running the sync twice gives
the same result, and a crashed run simply continues where it stopped.
"""

import asyncio
import csv
import json
import logging
from collections.abc import Collection
from datetime import date, timedelta
from pathlib import Path

import judobase
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, SQLModel

from ajr.core.db import engine
from ajr.core.models import (
    Athlete,
    AthleteAlias,
    Competition,
    Contest,
    ContestWalkover,
    OlympicCycle,
    WrlRanking,
)
from ajr.sync import parse
from ajr.sync.client import JudobaseClient
from ajr.sync.walkovers import walkovers

logger = logging.getLogger(__name__)

OLYMPIC_GAMES_FILE = Path(__file__).parent / "data" / "olympic_games.json"
ALIASES_FILE = Path(__file__).parent / "data" / "athlete_aliases.csv"
DRAW_LOOKAHEAD = timedelta(days=14)
LIVE_GRACE = timedelta(days=2)  # results keep arriving for a couple of days
COMPETITIONS_PER_BATCH = 16
ROWS_PER_INSERT = 1000


async def run_sync(full: bool = False) -> list[Competition]:
    """The competitions whose results changed although judobase did not say so (their
    `updated` the same): only a full sync finds those, the 15-minute one misses them."""
    today = date.today()
    unannounced: list[Competition] = []
    async with JudobaseClient() as client:
        with Session(engine) as session:
            save_olympic_cycles(session)
            country_ids = save_countries(session, await client.countries())
            save_competitions(session, await client.competitions(), country_ids)
            aliases = save_aliases(session)
            session.commit()
            competitions = pick_competitions_to_sync(session, today, full)
            announced = {c.id for c in pick_competitions_to_sync(session, today, False)}
            known_athletes = set(session.scalars(select(Athlete.id)))

        logger.info("Syncing contests of %d competitions", len(competitions))
        for start in range(0, len(competitions), COMPETITIONS_PER_BATCH):
            batch = competitions[start : start + COMPETITIONS_PER_BATCH]
            results = await asyncio.gather(*(fetch_contests(client, c) for c in batch))
            for competition, contests in zip(batch, results, strict=True):
                if contests is None:
                    continue
                changed = await save_competition_contests(
                    client, competition, contests, known_athletes, country_ids, aliases
                )
                if changed and competition.id not in announced:
                    unannounced.append(competition)
            logger.info(
                "Done %d/%d",
                min(start + COMPETITIONS_PER_BATCH, len(competitions)),
                len(competitions),
            )

        await save_world_ranking(client, known_athletes, aliases)

    if unannounced:
        logger.warning(
            "Results changed without judobase saying so: %s",
            ", ".join(f"{c.id} {c.name}" for c in unannounced),
        )
    logger.info("Sync finished")
    return unannounced


# --- reference data ----------------------------------------------------------


def olympic_cycles() -> list[OlympicCycle]:
    """A cycle runs from the day after one Games to the last day of the next ones."""
    games = json.loads(OLYMPIC_GAMES_FILE.read_text())
    games.sort(key=lambda g: g["end"])
    cycles = []
    previous_end = None
    for number, game in enumerate(games, start=1):
        end = date.fromisoformat(game["end"])
        if previous_end is None:
            start = date.fromisoformat(game["start"])
        else:
            start = previous_end + timedelta(days=1)
        cycles.append(
            OlympicCycle(
                id=number,
                name=f"{game['city']} {game['year']}",
                date_from=start,
                date_to=end,
            )
        )
        previous_end = end
    return cycles


def save_olympic_cycles(session: Session) -> None:
    upsert(session, olympic_cycles())


def save_countries(session: Session, items: list[judobase.CountryShort]) -> set[int]:
    countries = [parse.country(item) for item in items]
    upsert(session, countries)
    return {country.id for country in countries}


def save_competitions(
    session: Session, items: list[judobase.Competition], country_ids: set[int]
) -> None:
    cycles = olympic_cycles()
    competitions = []
    for item in items:
        competition = parse.competition(item)
        competition.olympic_cycle_id = find_cycle(cycles, competition.date_from)
        if competition.country_id not in country_ids:
            competition.country_id = None
        competitions.append(competition)
    # These columns are ours: never overwritten by judobase data.
    upsert(session, competitions, keep_columns={"contests_synced_for", "results_changed_at"})


def save_aliases(session: Session) -> dict[int, int]:
    """Load the athletes' second ids (alias -> main id) from ALIASES_FILE, and write the
    main id in the contests that still have an alias, marking their competitions
    changed so the rating rates them again.

    judobase opens a new profile when an athlete changes nations, and sometimes enters
    one twice at a tournament; the file lists the ids checked to be one person. An
    alias or main id we don't have (yet) is left out until the athlete is synced.
    """
    with ALIASES_FILE.open(newline="") as file:
        listed = {int(row["alias_id"]): int(row["athlete_id"]) for row in csv.DictReader(file)}
    have = set(
        session.scalars(
            select(Athlete.id).where(Athlete.id.in_(set(listed) | set(listed.values())))
        )
    )
    aliases = {alias: main for alias, main in listed.items() if alias in have and main in have}

    saved = {a.alias_id: a.athlete_id for a in session.scalars(select(AthleteAlias))}
    if saved != aliases:
        session.execute(delete(AthleteAlias))
        upsert(session, [AthleteAlias(alias_id=a, athlete_id=m) for a, m in aliases.items()])
        logger.info("Athlete aliases: %d saved", len(aliases))

    changed: set[int] = set()
    for column in (Contest.white_id, Contest.blue_id, Contest.winner_id):
        alias = AthleteAlias.__table__.c
        result = session.execute(
            update(Contest)
            .where(column == alias.alias_id)
            .values({column.key: alias.athlete_id})
            .returning(Contest.competition_id)
        )
        changed.update(result.scalars())
    if changed:
        session.execute(
            update(Competition)
            .where(Competition.id.in_(changed))
            .values(results_changed_at=func.now())  # the rating picks it up
        )
        logger.info("Athlete aliases: contests of %d competitions moved to main ids", len(changed))
    return aliases


def find_cycle(cycles: list[OlympicCycle], day: date | None) -> int | None:
    if day is None:
        return None
    for cycle in cycles:
        if cycle.date_from <= day <= cycle.date_to:
            return cycle.id
    return None


# --- choosing what to sync ----------------------------------------------------


def pick_competitions_to_sync(session: Session, today: date, full: bool) -> list[Competition]:
    competitions = session.scalars(select(Competition)).all()
    picked = [c for c in competitions if needs_sync(c, today, full)]
    picked.sort(key=lambda c: c.date_from or date.min, reverse=True)
    return picked


def needs_sync(competition: Competition, today: date, full: bool) -> bool:
    if is_not_a_fight_event(competition) or competition.date_from is None:
        return False

    starts = competition.date_from
    ends = competition.date_to or starts

    happening_soon_or_now = starts - DRAW_LOOKAHEAD <= today <= ends + LIVE_GRACE
    if happening_soon_or_now:
        return True

    if starts > today or not competition.has_results:
        return False
    if full:
        return True
    return competition.contests_synced_for != competition.updated_at


# Kinds of event (ajr/sync/kinds.py) whose contests are not fetched: kata, ne-waza
# and camps have no fights, and team events none we rate yet (a team match's bouts:
# other stakes, selection; judobase lists some among the individual events, e.g.
# "European Senior Championships Mixed Teams 2026").
NOT_FETCHED = {"kata", "camp", "team"}


def is_not_a_fight_event(competition: Competition) -> bool:
    return competition.kind in NOT_FETCHED


# --- contests -----------------------------------------------------------------


async def fetch_contests(
    client: JudobaseClient, competition: Competition
) -> list[judobase.Contest] | None:
    try:
        return await client.contests(competition.id)
    except Exception as error:
        # One broken competition must not stop the whole sync; it is retried next run.
        logger.error("Competition %s: could not fetch contests: %r", competition.id, error)
        return None


async def save_competition_contests(
    client: JudobaseClient,
    competition: Competition,
    items: list[judobase.Contest],
    known_athletes: set[int],
    country_ids: set[int],
    aliases: dict[int, int] | None = None,
) -> bool:
    """Whether the results changed (what the rating reads of them).

    An athlete's second id (`aliases`) is saved as their main id."""
    aliases = aliases or {}
    if not items:
        with Session(engine) as session:
            saved = session.scalar(
                select(func.count()).where(Contest.competition_id == competition.id)
            )
        if saved:
            logger.warning(
                "Competition %s: judobase returned no contests, keeping our %d",
                competition.id,
                saved,
            )
            return False

    new_athletes = await fetch_new_athletes(client, items, known_athletes)
    for athlete in new_athletes:
        if athlete.country_id not in country_ids:
            athlete.country_id = None

    contests = []
    for item in items:
        contest = parse.contest(item)
        if contest.competition_id != competition.id:
            continue
        contest.blue_id = aliases.get(contest.blue_id, contest.blue_id)
        contest.white_id = aliases.get(contest.white_id, contest.white_id)
        contest.winner_id = aliases.get(contest.winner_id, contest.winner_id)
        if contest.blue_id is not None and contest.blue_id == contest.white_id:
            logger.warning(
                "Contest %s: both sides are athlete %s, left out", contest.id, contest.blue_id
            )
            continue
        if contest.winner_id is not None and contest.winner_id not in (
            contest.blue_id,
            contest.white_id,
        ):
            logger.warning(
                "Contest %s: winner %s is not one of the fighters, ignoring the winner",
                contest.id,
                contest.winner_id,
            )
            contest.winner_id = None
        contests.append(contest)

    with Session(engine) as session:
        results_before = saved_results(session, competition.id)
        upsert(session, new_athletes, update_existing=False)
        upsert(session, contests)
        remove_missing_contests(session, competition.id, [contest.id for contest in contests])
        save_walkovers(session, competition.id, walkovers(items), {c.id for c in contests})
        values = {"contests_synced_for": competition.updated_at}
        changed = saved_results(session, competition.id) != results_before
        if changed:
            values["results_changed_at"] = func.now()  # the rating picks it up
        session.execute(update(Competition).where(Competition.id == competition.id).values(values))
        session.commit()

    known_athletes.update(athlete.id for athlete in new_athletes)
    logger.info(
        "Competition %s: %d contests, %d new athletes",
        competition.id,
        len(contests),
        len(new_athletes),
    )
    return changed


async def fetch_new_athletes(
    client: JudobaseClient, items: list[judobase.Contest], known_athletes: set[int]
) -> list[Athlete]:
    """Fetch profiles of athletes we have never seen. If a profile can't be fetched,
    use the name and country written in the contest instead."""
    from_contests = {}
    for item in items:
        for athlete in (parse.blue_athlete(item), parse.white_athlete(item)):
            if athlete is not None and athlete.id not in known_athletes:
                from_contests.setdefault(athlete.id, athlete)

    async def fetch_one(athlete_id: int) -> Athlete:
        try:
            profile = await client.judoka(athlete_id)
            return parse.athlete(profile, athlete_id)
        except Exception as error:
            logger.warning("Athlete %s: using contest data (%r)", athlete_id, error)
            return from_contests[athlete_id]

    return list(await asyncio.gather(*(fetch_one(i) for i in from_contests)))


# What the rating reads of a contest (ajr/rating/engine.py): a change in any of
# them, not only in the winner, must have the competition rated again.
RATED_FIELDS = (
    Contest.winner_id, Contest.blue_id, Contest.white_id, Contest.started_at, Contest.weight,
    Contest.round, Contest.fight_no, Contest.bye, Contest.duration,
)  # fmt: skip


def save_walkovers(
    session: Session, competition_id: int, found: dict[int, str], kept: set[int]
) -> None:
    """Replace the competition's walkovers (of the contests saved)."""
    session.execute(
        delete(ContestWalkover).where(
            ContestWalkover.contest_id.in_(
                select(Contest.id).where(Contest.competition_id == competition_id)
            )
        )
    )
    upsert(
        session,
        [ContestWalkover(contest_id=i, reason=r) for i, r in found.items() if i in kept],
    )


def saved_results(session: Session, competition_id: int) -> dict[int, tuple]:
    """Decided contests of the competition: contest id -> what the rating reads of it
    (whether it was a walkover too)."""
    rows = session.execute(
        select(Contest.id, *RATED_FIELDS, ContestWalkover.reason)
        .outerjoin(ContestWalkover, ContestWalkover.contest_id == Contest.id)
        .where(Contest.competition_id == competition_id)
        .where(Contest.winner_id.is_not(None))
    )
    return {row[0]: tuple(row[1:]) for row in rows}


def remove_missing_contests(session: Session, competition_id: int, contest_ids: list[int]) -> None:
    """Contests judobase no longer lists for this competition (e.g. a redrawn bracket)."""
    session.execute(
        delete(Contest)
        .where(Contest.competition_id == competition_id)
        .where(Contest.id.not_in(contest_ids))
    )


# --- world ranking list -------------------------------------------------------


async def save_world_ranking(
    client: JudobaseClient, known_athletes: set[int], aliases: dict[int, int] | None = None
) -> None:
    """Replace our copy of the WRL when judobase's list changed.

    Athletes we don't have are left out (we couldn't show them anyway). An error or
    an empty answer keeps our copy: the list only changes weekly.
    """
    try:
        items = await client.world_ranking()
    except Exception as error:
        logger.error("World ranking: could not fetch it: %r", error)
        return
    entries = []
    for entry in map(parse.wrl_entry, items):
        entry.athlete_id = (aliases or {}).get(entry.athlete_id, entry.athlete_id)
        if entry.athlete_id in known_athletes:
            entries.append(entry)
    # an athlete listed under both ids keeps the better place
    best = {}
    for entry in sorted(entries, key=lambda e: e.place):
        best.setdefault((entry.athlete_id, entry.weight), entry)
    entries = list(best.values())
    if not entries:
        logger.warning("World ranking: judobase returned no entries, keeping ours")
        return

    with Session(engine) as session:
        saved = {
            (e.athlete_id, e.weight): (e.place, e.points)
            for e in session.scalars(select(WrlRanking))
        }
        new = {(e.athlete_id, e.weight): (e.place, e.points) for e in entries}
        if saved == new:
            return
        session.execute(delete(WrlRanking))
        upsert(session, entries)
        session.commit()
    logger.info(
        "World ranking: %d entries saved, %d of athletes we don't have left out",
        len(entries),
        len(items) - len(entries),
    )


# --- writing ------------------------------------------------------------------


def upsert(
    session: Session,
    items: list[SQLModel],
    keep_columns: Collection[str] = (),
    update_existing: bool = True,
) -> None:
    """INSERT ... ON CONFLICT (primary key) DO UPDATE / DO NOTHING.

    All items are of one model; `keep_columns` are never overwritten on update.
    """
    if not items:
        return
    table = type(items[0]).__table__
    rows = [item.model_dump() for item in items]
    primary_key = [column.name for column in table.primary_key]
    statement = insert(table)
    if update_existing:
        columns_to_update = {
            name: statement.excluded[name]
            for name in rows[0]
            if name not in primary_key and name not in keep_columns
        }
        statement = statement.on_conflict_do_update(
            index_elements=primary_key, set_=columns_to_update
        )
    else:
        statement = statement.on_conflict_do_nothing(index_elements=primary_key)

    for start in range(0, len(rows), ROWS_PER_INSERT):
        session.execute(statement, rows[start : start + ROWS_PER_INSERT])
