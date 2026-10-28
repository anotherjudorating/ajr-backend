"""Recompute ajr.record: all-time bests for the records page.

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


def run_records(today: date | None = None) -> None:
    with Session(engine) as session:
        connection = session.connection()
        for statement in SETUP:
            connection.execute(text(statement))
        session.execute(delete(Record))
        for name, query in RECORDS.items():
            result = connection.execute(text(INSERT.format(query=query)), {"record": name})
            logger.info("%s: %d rows", name, result.rowcount)
        weekly = weekly_records(connection, PARAMS, RANKING, today or date.today())
        for name, rows in weekly.items():
            session.add_all(Record(record=name, **row) for row in rows)
            logger.info("%s: %d rows", name, len(rows))
        session.commit()
    logger.info("Records saved")
