"""Copy judobase into our database.

Order of work:
1. Olympic cycles (from a local file), countries and competitions are saved every run.
2. Contests are fetched only for competitions that need it:
   - competitions happening now or in the next two weeks (draws and live results),
   - past competitions whose data changed in judobase since we last saved them,
   - every past competition with results when running with --full.
3. For each of those competitions, in one transaction: new athletes, the contests,
   and removal of contests judobase no longer lists.

Every write is an upsert keyed by the judobase id, so running the sync twice gives
the same result, and a crashed run simply continues where it stopped.
"""

import asyncio
import json
import logging
from collections.abc import Collection
from datetime import date, timedelta
from pathlib import Path

import judobase
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, SQLModel

from ajr.core.db import engine
from ajr.core.models import Athlete, Competition, Contest, OlympicCycle
from ajr.sync import parse
from ajr.sync.client import JudobaseClient

logger = logging.getLogger(__name__)

OLYMPIC_GAMES_FILE = Path(__file__).parent / "data" / "olympic_games.json"
DRAW_LOOKAHEAD = timedelta(days=14)
LIVE_GRACE = timedelta(days=2)  # results keep arriving for a couple of days
COMPETITIONS_PER_BATCH = 16
ROWS_PER_INSERT = 1000


async def run_sync(full: bool = False) -> None:
    today = date.today()
    async with JudobaseClient() as client:
        with Session(engine) as session:
            save_olympic_cycles(session)
            country_ids = save_countries(session, await client.countries())
            save_competitions(session, await client.competitions(), country_ids)
            session.commit()
            competitions = pick_competitions_to_sync(session, today, full)
            known_athletes = set(session.scalars(select(Athlete.id)))

        logger.info("Syncing contests of %d competitions", len(competitions))
        for start in range(0, len(competitions), COMPETITIONS_PER_BATCH):
            batch = competitions[start : start + COMPETITIONS_PER_BATCH]
            results = await asyncio.gather(*(fetch_contests(client, c) for c in batch))
            for competition, contests in zip(batch, results, strict=True):
                if contests is None:
                    continue
                await save_competition_contests(
                    client, competition, contests, known_athletes, country_ids
                )
            logger.info(
                "Done %d/%d",
                min(start + COMPETITIONS_PER_BATCH, len(competitions)),
                len(competitions),
            )

    logger.info("Sync finished")


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
    # `contests_synced_for` is ours: never overwritten by judobase data.
    upsert(session, competitions, keep_columns={"contests_synced_for"})


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


def is_not_a_fight_event(competition: Competition) -> bool:
    """Kata and ne-waza events have no fights we can rate."""
    text = f"{competition.rank_name or ''} {competition.name or ''}".lower()
    return "kata" in text or "ne-waza" in text


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
) -> None:
    new_athletes = await fetch_new_athletes(client, items, known_athletes)
    for athlete in new_athletes:
        if athlete.country_id not in country_ids:
            athlete.country_id = None

    contests = []
    for item in items:
        contest = parse.contest(item)
        if contest.competition_id != competition.id:
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
        upsert(session, new_athletes, update_existing=False)
        upsert(session, contests)
        remove_missing_contests(session, competition.id, [contest.id for contest in contests])
        session.execute(
            update(Competition)
            .where(Competition.id == competition.id)
            .values(contests_synced_for=competition.updated_at)
        )
        session.commit()

    known_athletes.update(athlete.id for athlete in new_athletes)
    logger.info(
        "Competition %s: %d contests, %d new athletes",
        competition.id,
        len(contests),
        len(new_athletes),
    )


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


def remove_missing_contests(session: Session, competition_id: int, contest_ids: list[int]) -> None:
    """Contests judobase no longer lists for this competition (e.g. a redrawn bracket)."""
    session.execute(
        delete(Contest)
        .where(Contest.competition_id == competition_id)
        .where(Contest.id.not_in(contest_ids))
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
