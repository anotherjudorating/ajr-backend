import pytest
from sqlmodel import Session, select

from ajr.core.db import engine
from ajr.core.job_run import job_run
from ajr.core.models import JobRun

pytestmark = pytest.mark.usefixtures("clean_db")


def runs() -> list[JobRun]:
    with Session(engine) as session:
        return list(session.exec(select(JobRun).order_by(JobRun.id)))


def test_successful_run():
    with job_run("sync"):
        [run] = runs()
        assert (run.type, run.status, run.finished_at) == ("sync", "running", None)

    [run] = runs()
    assert run.status == "success"
    assert run.finished_at >= run.started_at
    assert run.error is None


def test_failed_run_keeps_the_error_and_raises_it():
    with pytest.raises(RuntimeError, match="judobase is down"), job_run("sync"):
        raise RuntimeError("judobase is down")

    [run] = runs()
    assert run.status == "failed"
    assert run.finished_at is not None
    assert "RuntimeError: judobase is down" in run.error
