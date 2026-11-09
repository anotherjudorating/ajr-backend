"""Which competitions get their contests fetched."""

from datetime import UTC, date, datetime, timedelta

import pytest

from ajr.core.models import Competition
from ajr.sync.job import needs_sync

TODAY = date(2026, 10, 28)
UPDATED = datetime(2026, 1, 1, tzinfo=UTC)


def make(
    starts_in_days: int,
    *,
    days: int = 2,
    has_results: bool = True,
    synced: bool = True,
    name: str = "Grand Slam",
    kind: str = "individual",
) -> Competition:
    starts = TODAY + timedelta(days=starts_in_days)
    return Competition(
        id=1,
        name=name,
        kind=kind,
        date_from=starts,
        date_to=starts + timedelta(days=days - 1),
        has_results=has_results,
        updated_at=UPDATED,
        contests_synced_for=UPDATED if synced else None,
    )


@pytest.mark.parametrize(
    ("starts_in_days", "expected"),
    [
        (30, False),  # too far ahead, no draw yet
        (15, False),
        (14, True),  # draws come out about two weeks before
        (0, True),  # happening now
        (-3, True),  # 2-day event ended yesterday: results still arrive
        (-4, False),  # ended two days ago, already synced
    ],
)
def test_window_around_the_competition(starts_in_days, expected):
    assert needs_sync(make(starts_in_days), TODAY, full=False) is expected


def test_upcoming_competition_is_synced_even_if_unchanged():
    assert needs_sync(make(5, has_results=False), TODAY, full=False)


def test_past_competition_only_when_changed():
    assert not needs_sync(make(-100), TODAY, full=False)
    assert needs_sync(make(-100, synced=False), TODAY, full=False)


def test_full_sync_takes_every_past_competition_with_results():
    assert needs_sync(make(-100), TODAY, full=True)
    assert not needs_sync(make(-100, has_results=False, synced=False), TODAY, full=True)


@pytest.mark.parametrize("kind", ["kata", "camp", "team"])
def test_events_without_fights_we_rate_are_skipped(kind):
    assert not needs_sync(make(0, kind=kind), TODAY, full=True)


@pytest.mark.parametrize("kind", ["individual", "para", "age_group", "military"])
def test_other_events_are_fetched(kind):
    assert needs_sync(make(0, kind=kind), TODAY, full=True)


def test_competition_without_date_is_skipped():
    competition = make(0)
    competition.date_from = None
    assert not needs_sync(competition, TODAY, full=True)
