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
from ajr.records.queries import RECORDS, SETUP
from ajr.records.weekly import weekly_records

logger = logging.getLogger(__name__)

INSERT = """
    insert into ajr.record (record, place, athlete_id, opponent_id, country_id,
                            competition_id, weight, value, detail, day)
    select :record, * from ({query}) best
"""


# The names the site shows with a record's rows, written once here instead of looked
# up on every request: a nation's record has the nation, an athlete's their nation.
NAMES = """
    update ajr.record r
    set family_name = a.family_name,
        given_name = a.given_name,
        gender = a.gender,
        opponent_family_name = o.family_name,
        opponent_given_name = o.given_name,
        country = co.ioc,
        country_name = co.name,
        competition = cm.name
    from ajr.record named
    left join ajr.athlete a on a.id = named.athlete_id
    left join ajr.athlete o on o.id = named.opponent_id
    left join ajr.country co on co.id = coalesce(named.country_id, a.country_id)
    left join ajr.competition cm on cm.id = named.competition_id
    where named.id = r.id
"""

HISTORY_COPY = "copy ajr.nation_history (day, country_id, place, rating) from stdin"


def run_records(today: date | None = None) -> None:
    with Session(engine) as session:
        connection = session.connection()
        for statement in SETUP:
            connection.execute(text(statement))
        session.execute(delete(Record))
        for name, query in RECORDS.items():
            result = connection.execute(text(INSERT.format(query=query)), {"record": name})
            logger.info("%s: %d rows", name, result.rowcount)
        history: list[dict] = []
        weekly = weekly_records(connection, PARAMS, RANKING, today or date.today(), history)
        for name, rows in weekly.items():
            session.add_all(Record(record=name, **row) for row in rows)
            logger.info("%s: %d rows", name, len(rows))
        session.flush()
        connection.execute(text(NAMES))
        connection.execute(text("delete from ajr.nation_history"))
        cursor = connection.connection.cursor()
        with cursor.copy(HISTORY_COPY) as copy:
            for row in history:
                copy.write_row([row["day"], row["country_id"], row["place"], row["rating"]])
        logger.info("nation_history: %d rows", len(history))
        session.commit()
    logger.info("Records saved")
