"""Which competitions get their contests fetched, and the Olympic cycles."""

from datetime import UTC, date, datetime, timedelta

import pytest

from ajr.core.models import Competition
from ajr.sync.job import find_cycle, needs_sync, olympic_cycles

TODAY = date(2026, 10, 28)
UPDATED = datetime(2026, 1, 1, tzinfo=UTC)


def make(
    starts_in_days: int,
    *,
    days: int = 2,
    has_results: bool = True,
    synced: bool = True,
    name: str = "Grand Slam",
) -> Competition:
    starts = TODAY + timedelta(days=starts_in_days)
    return Competition(
        id=1,
        name=name,
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


@pytest.mark.parametrize("name", ["World Kata Championships", "Ne-Waza Open"])
def test_events_without_fights_are_skipped(name):
    assert not needs_sync(make(0, name=name), TODAY, full=True)


def test_competition_without_date_is_skipped():
    competition = make(0)
    competition.date_from = None
    assert not needs_sync(competition, TODAY, full=True)


def test_olympic_cycles_follow_each_other():
    cycles = olympic_cycles()

    for previous, current in zip(cycles, cycles[1:], strict=False):
        assert current.date_from == previous.date_to + timedelta(days=1)
    assert find_cycle(cycles, date(2024, 8, 11)) == find_cycle(cycles, date(2021, 8, 9))
    assert find_cycle(cycles, date(2024, 8, 12)) != find_cycle(cycles, date(2024, 8, 11))
    assert find_cycle(cycles, None) is None
    assert find_cycle(cycles, date(1900, 1, 1)) is None  # before the first Games
