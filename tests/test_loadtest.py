"""The load test's report and arithmetic (the calls themselves run in CI)."""

from ajr.loadtest.report import marked, report
from ajr.loadtest.run import percentile


def test_percentile():
    assert percentile(list(range(1, 101)), 0.95) == 96
    assert percentile([], 0.95) == 0


def test_marked_only_clearly_more_pages():
    assert marked(1000, 2000)
    assert not marked(1000, 1400)  # less than 1.5 times
    assert not marked(100, 400)  # 4 times, but only 300 pages more
    assert not marked(None, 5000)  # a new call


def run(pages: int, failures: list[str] | None = None) -> dict:
    case = {"case": "teams(kind='mixed')", "function": "teams", "pages": pages,
            "first": {"status": 200, "ms": 10.0}, "warm": {"status": 200, "ms": 2.0}}  # fmt: skip
    load = {"clients": 5, "calls": 1, "p50": 1, "p95": 2, "p99": 3, "failures": []}
    return {"cases": [case], "loads": [load], "failures": failures or []}


def test_report_marks_a_call_reading_more_and_lists_failures():
    text = report(run(1000), run(6000, ["teams(kind='mixed'): 500 timeout"]))

    assert "`teams` ⚠️" in text
    assert "1000 → 6000" in text
    assert "**1 failed calls**" in text
    assert "All 1 calls answered" in report(run(1000), run(1000))
