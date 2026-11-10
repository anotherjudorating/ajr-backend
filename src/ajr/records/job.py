"""Recompute ajr.record: all-time bests for the records page; and, from the same
weekly tables, ajr.nation_history (every week's mixed nations ranking).

Run after the nightly full rating (`python -m ajr.records`, about a minute). The
table is replaced as a whole in one transaction. Most records are SQL queries
(ajr/records/queries.py); the ones that need every week's tables are computed in
Python (ajr/records/weekly.py).
"""

import logging
from datetime import date

from sqlalchemy import delete, text
from sqlmodel import Session

from ajr.core.db import engine
from ajr.core.models import Record
from ajr.rating.job import PARAMS, RANKING
from ajr.records.queries import BY_GENDER, RECORDS, SETUP, scoped
from ajr.records.weekly import weekly_records

logger = logging.getLogger(__name__)

INSERT = """
    insert into ajr.record (record, place, athlete_id, opponent_id, country_id,
                            competition_id, weight, value, detail, day, gender)
    select :record, best.*, cast(:gender as text) from ({query}) best
"""


# The names the site shows with a record's rows, written once here instead of looked
# up on every request: a nation's record has the nation, an athlete's their nation.
NAMES = """
    update ajr.record r
    set family_name = a.family_name,
        given_name = a.given_name,
        gender = coalesce(a.gender, named.gender), -- a nation's or tournament's: its rows' own
        opponent_family_name = o.family_name,
        opponent_given_name = o.given_name,
        opponent_country = oc.ioc,
        country = co.ioc,
        country_name = co.name,
        competition = cm.name
    from ajr.record named
    left join ajr.athlete a on a.id = named.athlete_id
    left join ajr.athlete o on o.id = named.opponent_id
    left join ajr.country oc on oc.id = o.country_id
    left join ajr.country co on co.id = coalesce(named.country_id, a.country_id)
    left join ajr.competition cm on cm.id = named.competition_id
    where named.id = r.id
"""

# Every Sunday's top 10 of every weight, as the weekly tables have them.
WEEKLY_PLACE = """
    create temp table weekly_place (sunday date, weight text, athlete_id integer, place integer)
    on commit drop
"""
WEEKLY_PLACE_COPY = "copy weekly_place (sunday, weight, athlete_id, place) from stdin"

HISTORY_COPY = "copy ajr.nation_history (day, country_id, place, rating) from stdin"


def run_records(today: date | None = None) -> None:
    with Session(engine) as session:
        connection = session.connection()
        # the weekly tables first: the SQL records read their top 10s (weekly_place)
        history: list[dict] = []
        places: list[tuple] = []
        weekly = weekly_records(connection, PARAMS, RANKING, today or date.today(), history, places)
        connection.execute(text(WEEKLY_PLACE))
        cursor = connection.connection.cursor()
        with cursor.copy(WEEKLY_PLACE_COPY) as copy:
            for row in places:
                copy.write_row(row)
        for statement in SETUP:
            connection.execute(text(statement))
        session.execute(delete(Record))
        for name, query in RECORDS.items():
            # a nation's or tournament's record also for each gender (BY_GENDER)
            for gender in (None, "male", "female") if name in BY_GENDER else (None,):
                sql = INSERT.format(query=scoped(query, gender))
                result = connection.execute(text(sql), {"record": name, "gender": gender})
                logger.info("%s %s: %d rows", name, gender or "all", result.rowcount)
        for name, rows in weekly.items():
            session.add_all(Record(record=name, **row) for row in rows)
            logger.info("%s: %d rows", name, len(rows))
        session.flush()
        connection.execute(text(NAMES))
        connection.execute(text("delete from ajr.nation_history"))
        with cursor.copy(HISTORY_COPY) as copy:
            for row in history:
                copy.write_row([row["day"], row["country_id"], row["place"], row["rating"]])
        logger.info("nation_history: %d rows", len(history))
        session.commit()
    logger.info("Records saved")
