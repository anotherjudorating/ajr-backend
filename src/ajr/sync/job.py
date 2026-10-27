"""Copy judobase into our database.

Order of work:
1. Olympic cycles (from a local file), countries and competitions are saved every run.
2. Contests are fetched only for competitions that need it:
   - competitions happening now or in the next two weeks (draws and live results),
   - past competitions whose data changed in judobase since we last saved them,
   - every past competition with results when running with --full.
3. For each of those competitions, in one transaction: new judokas, the contests,
   and removal of contests judobase no longer lists.

Every write is an upsert keyed by the judobase id, so running the sync twice gives
the same result, and a crashed run simply continues where it stopped.
"""

import asyncio
import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session

from ajr.core.db import engine
from ajr.core.models import Competition, Contest, Country, Judoka, OlympicCycle, SyncState
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
    async with JudobaseClient() as judobase:
        with Session(engine) as session:
            save_olympic_cycles(session)
            country_ids = save_countries(session, await judobase.countries())
            save_competitions(session, await judobase.competitions(), country_ids)
            session.commit()
            competitions = pick_competitions_to_sync(session, today, full)
            known_judokas = set(session.scalars(select(Judoka.id)))

        logger.info("Syncing contests of %d competitions", len(competitions))
        for start in range(0, len(competitions), COMPETITIONS_PER_BATCH):
            batch = competitions[start : start + COMPETITIONS_PER_BATCH]
            results = await asyncio.gather(*(fetch_contests(judobase, c) for c in batch))
            for competition, contests in zip(batch, results, strict=True):
                if contests is None:
                    continue
                await save_competition_contests(
                    judobase, competition, contests, known_judokas, country_ids
                )
            logger.info(
                "Done %d/%d",
                min(start + COMPETITIONS_PER_BATCH, len(competitions)),
                len(competitions),
            )

    with Session(engine) as session:
        upsert(session, SyncState, [{"id": 1, "last_success_at": datetime.now(UTC)}])
        session.commit()
    logger.info("Sync finished")


# --- reference data ----------------------------------------------------------


def olympic_cycle_rows() -> list[dict]:
    """A cycle runs from the day after one Games to the last day of the next ones."""
    games = json.loads(OLYMPIC_GAMES_FILE.read_text())
    games.sort(key=lambda g: g["end"])
    rows = []
    previous_end = None
    for number, game in enumerate(games, start=1):
        end = date.fromisoformat(game["end"])
        if previous_end is None:
            start = date.fromisoformat(game["start"])
        else:
            start = previous_end + timedelta(days=1)
        rows.append(
            {
                "id": number,
                "name": f"{game['city']} {game['year']}",
                "date_from": start,
                "date_to": end,
            }
        )
        previous_end = end
    return rows


def save_olympic_cycles(session: Session) -> None:
    upsert(session, OlympicCycle, olympic_cycle_rows())


def save_countries(session: Session, countries) -> set[int]:
    rows = [parse.country_row(c) for c in countries]
    upsert(session, Country, rows)
    return {row["id"] for row in rows}


def save_competitions(session: Session, competitions, country_ids: set[int]) -> None:
    cycles = olympic_cycle_rows()
    rows = []
    for competition in competitions:
        row = parse.competition_row(competition)
        row["olympic_cycle_id"] = find_cycle(cycles, row["date_from"])
        if row["country_id"] not in country_ids:
            row["country_id"] = None
        rows.append(row)
    # `contests_synced_for` is ours: never overwritten by judobase data.
    upsert(session, Competition, rows, keep_columns={"contests_synced_for"})


def find_cycle(cycles: list[dict], day: date | None) -> int | None:
    if day is None:
        return None
    for cycle in cycles:
        if cycle["date_from"] <= day <= cycle["date_to"]:
            return cycle["id"]
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


async def fetch_contests(judobase: JudobaseClient, competition: Competition):
    try:
        return await judobase.contests(competition.id)
    except Exception as error:
        # One broken competition must not stop the whole sync; it is retried next run.
        logger.error("Competition %s: could not fetch contests: %r", competition.id, error)
        return None


async def save_competition_contests(
    judobase: JudobaseClient,
    competition: Competition,
    contests,
    known_judokas: set[int],
    country_ids: set[int],
) -> None:
    new_judokas = await fetch_new_judokas(judobase, contests, known_judokas)
    for judoka in new_judokas:
        if judoka["country_id"] not in country_ids:
            judoka["country_id"] = None

    contest_rows = []
    for contest in contests:
        row = parse.contest_row(contest)
        if row["competition_id"] != competition.id:
            continue
        if row["winner_id"] is not None and row["winner_id"] not in (
            row["blue_id"],
            row["white_id"],
        ):
            logger.warning(
                "Contest %s: winner %s is not one of the fighters, ignoring the winner",
                row["id"],
                row["winner_id"],
            )
            row["winner_id"] = None
        contest_rows.append(row)

    with Session(engine) as session:
        upsert(session, Judoka, new_judokas, update_existing=False)
        upsert(session, Contest, contest_rows)
        remove_missing_contests(session, competition.id, [row["id"] for row in contest_rows])
        session.execute(
            update(Competition)
            .where(Competition.id == competition.id)
            .values(contests_synced_for=competition.updated_at)
        )
        session.commit()

    known_judokas.update(judoka["id"] for judoka in new_judokas)
    logger.info(
        "Competition %s: %d contests, %d new judokas",
        competition.id,
        len(contest_rows),
        len(new_judokas),
    )


async def fetch_new_judokas(
    judobase: JudobaseClient, contests, known_judokas: set[int]
) -> list[dict]:
    """Fetch profiles of judokas we have never seen. If a profile can't be fetched,
    use the name and country written in the contest instead."""
    from_contests = {}
    for contest in contests:
        for row in (parse.blue_judoka_row(contest), parse.white_judoka_row(contest)):
            if row is not None and row["id"] not in known_judokas:
                from_contests.setdefault(row["id"], row)

    async def fetch_one(judoka_id: int) -> dict:
        try:
            profile = await judobase.judoka(judoka_id)
            return parse.judoka_row(profile, judoka_id)
        except Exception as error:
            logger.warning("Judoka %s: using contest data (%r)", judoka_id, error)
            return from_contests[judoka_id]

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
    session: Session, model, rows: list[dict], keep_columns=(), update_existing=True
) -> None:
    """INSERT ... ON CONFLICT (primary key) DO UPDATE / DO NOTHING."""
    if not rows:
        return
    table = model.__table__
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
