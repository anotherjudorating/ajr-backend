"""python -m ajr.records [--if-changed]"""

import argparse
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlmodel import Session

from ajr.core.db import engine
from ajr.core.job_run import job_run
from ajr.core.models import Competition, JobRun
from ajr.records.job import run_records

logger = logging.getLogger(__name__)

# The records about time (the longest at #1, the weekly nations) move without new
# results: at least once a week anyway.
AT_LEAST_EVERY = timedelta(days=7)


def needs_records() -> bool:
    """Results changed since the last records, or those are a week old."""
    with Session(engine) as session:
        last = session.scalar(
            select(func.max(JobRun.started_at))
            .where(JobRun.type == "records")
            .where(JobRun.status == "success")
        )
        if last is None or datetime.now(UTC) - last > AT_LEAST_EVERY:
            return True
        changed = session.scalar(select(func.max(Competition.results_changed_at)))
        return changed is not None and changed >= last


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Recompute the records.")
    parser.add_argument(
        "--if-changed",
        action="store_true",
        help="only if results changed since the last records (or they are a week old)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.if_changed and not needs_records():
        logger.info("No results changed since the last records: nothing to do")
        return
    with job_run("records"):
        run_records()


if __name__ == "__main__":
    main()
