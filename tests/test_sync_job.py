"""The whole sync against a fake judobase and a real (test) database."""

import asyncio
from datetime import date, timedelta

import pytest
from fake_judobase import UPDATED, UPDATED_LATER, FakeJudobase, competition, contest, profile, utc
from sqlmodel import Session, SQLModel, select

from ajr.core.db import engine
from ajr.core.models import Athlete, Competition, Contest, Country, JobRun, OlympicCycle
from ajr.sync import job
from ajr.sync.__main__ import main

pytestmark = pytest.mark.usefixtures("clean_db")

TODAY = date.today()
PAST = TODAY - timedelta(days=100)
SOON = TODAY + timedelta(days=5)


@pytest.fixture
def judobase(monkeypatch) -> FakeJudobase:
    fake = FakeJudobase()
    monkeypatch.setattr(job, "JudobaseClient", lambda: fake)
    return fake


def sync(full: bool = False) -> None:
    asyncio.run(job.run_sync(full=full))


def stored[T: SQLModel](model: type[T]) -> dict[int, T]:
    with Session(engine) as session:
        return {item.id: item for item in session.exec(select(model))}


def add_past_competition(judobase: FakeJudobase, competition_id: int = 1) -> None:
    """A finished competition with two contests between three athletes."""
    judobase.competitions_list.append(competition(competition_id, PAST))
    judobase.contests_of[competition_id] = [
        contest(competition_id * 10 + 1, competition_id, blue=100, white=200, winner=200),
        contest(competition_id * 10 + 2, competition_id, blue=200, white=300, winner=300),
    ]
    for athlete_id in (100, 200, 300):
        judobase.profiles[athlete_id] = profile(f"NAME{athlete_id}")


def test_first_sync_saves_everything(judobase):
    add_past_competition(judobase)

    sync()

    assert stored(Country)[1].ioc == "JPN"
    assert len(stored(OlympicCycle)) == 22
    saved = stored(Competition)[1]
    assert saved.date_from == PAST
    assert saved.olympic_cycle_id is not None
    assert saved.contests_synced_for == utc(UPDATED)
    assert set(stored(Contest)) == {11, 12}
    athletes = stored(Athlete)
    assert set(athletes) == {100, 200, 300}
    assert (athletes[100].family_name, athletes[100].dob_year) == ("NAME100", 2000)


def test_second_sync_skips_unchanged_competitions(judobase):
    add_past_competition(judobase)
    sync()
    judobase.contest_requests.clear()
    judobase.profile_requests.clear()

    sync()

    assert judobase.contest_requests == []
    assert judobase.profile_requests == []
    assert set(stored(Contest)) == {11, 12}


def test_changed_competition_is_fetched_again(judobase):
    add_past_competition(judobase)
    sync()
    # judobase redrew the bracket: contest 12 is gone, contest 13 is new.
    judobase.competitions_list[0] = competition(1, PAST, updated=UPDATED_LATER)
    judobase.contests_of[1] = [
        contest(11, 1, blue=100, white=200, winner=200),
        contest(13, 1, blue=100, white=300, winner=100),
    ]

    sync()

    assert set(stored(Contest)) == {11, 13}
    assert stored(Competition)[1].contests_synced_for == utc(UPDATED_LATER)


def test_full_sync_fetches_unchanged_competitions(judobase):
    add_past_competition(judobase)
    sync()
    judobase.contest_requests.clear()

    sync(full=True)

    assert judobase.contest_requests == [1]


def test_known_athletes_are_not_fetched_again(judobase):
    add_past_competition(judobase, 1)
    sync()
    judobase.profile_requests.clear()
    judobase.competitions_list.append(competition(2, PAST))
    judobase.contests_of[2] = [contest(21, 2, blue=100, white=400, winner=400)]
    judobase.profiles[400] = profile("NAME400")

    sync()

    assert judobase.profile_requests == [400]


def test_missing_profile_is_taken_from_the_contest(judobase):
    judobase.competitions_list.append(competition(1, PAST))
    judobase.contests_of[1] = [
        contest(11, 1, blue=100, white=200, winner=200, code="wc_x_0001_f_0p78_0001")
    ]
    judobase.profiles[100] = profile("NAME100", gender="female")

    sync()

    athlete = stored(Athlete)[200]
    assert (athlete.family_name, athlete.given_name) == ("WHITE200", "White")
    assert (athlete.gender, athlete.country_id, athlete.dob_year) == ("female", 1, None)


def test_winner_who_is_not_a_fighter_is_dropped(judobase):
    add_past_competition(judobase)
    judobase.contests_of[1][0] = contest(11, 1, blue=100, white=200, winner=999)

    sync()

    assert stored(Contest)[11].winner_id is None
    assert stored(Contest)[12].winner_id == 300


def test_empty_answer_does_not_wipe_a_competition(judobase):
    add_past_competition(judobase)
    sync()
    # A judobase glitch: the competition changed and comes back without contests.
    judobase.competitions_list[0] = competition(1, PAST, updated=UPDATED_LATER)
    judobase.contests_of[1] = []
    judobase.contest_requests.clear()

    sync()

    assert set(stored(Contest)) == {11, 12}
    assert stored(Competition)[1].contests_synced_for == utc(UPDATED)  # tried again next run
    sync()
    assert judobase.contest_requests == [1, 1]


def test_contest_of_another_competition_is_skipped(judobase):
    add_past_competition(judobase)
    judobase.contests_of[1].append(contest(99, 2, blue=100, white=200, winner=100))

    sync()

    assert set(stored(Contest)) == {11, 12}


def test_unknown_country_becomes_none(judobase):
    judobase.competitions_list.append(competition(1, PAST, country_id=999))
    judobase.contests_of[1] = [contest(11, 1, blue=100, white=200, winner=200, white_country=999)]
    judobase.profiles[100] = profile("NAME100", country_id=999)

    sync()

    assert stored(Competition)[1].country_id is None
    assert stored(Athlete)[100].country_id is None
    assert stored(Athlete)[200].country_id is None


def test_broken_competition_does_not_stop_the_sync_and_is_retried(judobase):
    add_past_competition(judobase, 1)
    add_past_competition(judobase, 2)
    judobase.broken_competitions.add(1)

    sync()

    assert set(stored(Contest)) == {21, 22}
    assert stored(Competition)[1].contests_synced_for is None

    judobase.broken_competitions.clear()
    judobase.contest_requests.clear()
    sync()

    assert judobase.contest_requests == [1]
    assert set(stored(Contest)) == {11, 12, 21, 22}


def test_draw_is_saved_before_the_fighters_are_known(judobase):
    judobase.competitions_list.append(competition(1, SOON, has_results=0))
    judobase.contests_of[1] = [
        contest(11, 1, blue=100, white=200, winner=0),
        contest(12, 1, blue=0, white=0, winner=0),  # winners of earlier rounds meet here
    ]
    judobase.profiles.update({100: profile("NAME100"), 200: profile("NAME200")})

    sync()

    saved = stored(Contest)
    assert (saved[11].blue_id, saved[11].winner_id, saved[11].is_finished) == (100, None, False)
    assert (saved[12].blue_id, saved[12].white_id) == (None, None)

    # The next run fetches the upcoming competition again even though it did not change.
    judobase.contest_requests.clear()
    sync()
    assert judobase.contest_requests == [1]


def test_competitions_without_fights_are_not_fetched(judobase):
    judobase.competitions_list += [
        competition(1, PAST, name="World Kata Championships"),
        competition(2, PAST, has_results=0),
        competition(3, TODAY + timedelta(days=30)),
    ]

    sync(full=True)

    assert judobase.contest_requests == []
    assert set(stored(Competition)) == {1, 2, 3}


@pytest.mark.parametrize(("argv", "run_type"), [([], "sync"), (["--full"], "sync_full")])
def test_command_line_run_is_logged(judobase, argv, run_type):
    add_past_competition(judobase)

    main(argv)

    [run] = stored(JobRun).values()
    assert (run.type, run.status) == (run_type, "success")
    assert set(stored(Contest)) == {11, 12}


def results_changed_at(competition_id: int = 1):
    return stored(Competition)[competition_id].results_changed_at


def test_new_results_mark_the_competition(judobase):
    add_past_competition(judobase)

    sync()

    assert results_changed_at() is not None


def test_unchanged_results_leave_the_mark(judobase):
    add_past_competition(judobase)
    sync()
    first_mark = results_changed_at()
    # The competition changed in judobase (e.g. a name), its results did not.
    judobase.competitions_list[0] = competition(1, PAST, updated=UPDATED_LATER)

    sync()

    assert results_changed_at() == first_mark


@pytest.mark.parametrize(
    "new_contests",
    [
        [contest(11, 1, blue=100, white=200, winner=100), contest(12, 1, 200, 300, 300)],
        [contest(11, 1, blue=100, white=200, winner=200)],  # a decided contest vanished
    ],
    ids=["winner changed", "contest removed"],
)
def test_changed_results_move_the_mark(judobase, new_contests):
    add_past_competition(judobase)
    sync()
    first_mark = results_changed_at()
    judobase.competitions_list[0] = competition(1, PAST, updated=UPDATED_LATER)
    judobase.contests_of[1] = new_contests

    sync()

    assert results_changed_at() > first_mark


def test_draw_without_results_does_not_mark(judobase):
    judobase.competitions_list.append(competition(1, SOON, has_results=0))
    judobase.contests_of[1] = [contest(11, 1, blue=100, white=200, winner=0)]
    judobase.profiles.update({100: profile("NAME100"), 200: profile("NAME200")})

    sync()

    assert results_changed_at() is None
