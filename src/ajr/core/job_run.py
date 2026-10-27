"""Record every run of a job step in the job_run table."""

import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlmodel import Session

from ajr.core.db import engine
from ajr.core.models import JobRun


@contextmanager
def job_run(job_type: str) -> Iterator[None]:
    """Mark the run as running, then as success or failed (with the traceback).

    with job_run("sync"):
        ...
    """
    with Session(engine) as session:
        run = JobRun(type=job_type, status="running", started_at=datetime.now(UTC))
        session.add(run)
        session.commit()
        run_id = run.id

    try:
        yield
    except BaseException:
        # BaseException: a Ctrl+C or a stopped process is a failed run too.
        finish(run_id, "failed", traceback.format_exc())
        raise
    finish(run_id, "success")


def finish(run_id: int | None, status: str, error: str | None = None) -> None:
    with Session(engine) as session:
        run = session.get(JobRun, run_id)
        run.status = status
        run.finished_at = datetime.now(UTC)
        run.error = error
        session.commit()
