"""The rating step against a real (test) database."""

from datetime import date, datetime

import pytest
from sqlalchemy import delete, func, text, update
from sqlmodel import Session, select

from ajr.core.db import engine
from ajr.core.job_run import job_run
from ajr.core.models import (
    Athlete,
    AthleteSummary,
    Competition,
    CompetitionStats,
    Contest,
    ContestWalkover,
    Country,
    JobRun,
    NationSummary,
    RatingChange,
    RatingSettings,
)
from ajr.rating import snapshot
from ajr.rating.__main__ import main
from ajr.rating.engine import RatingParams
from ajr.rating.job import LATEST, RatingCheckError, run_rating
from tests.test_api import add_data

pytestmark = pytest.mark.usefixtures("clean_db")


def contest(contest_id: int, competition_id: int, blue: int, white: int, winner: int | None,
            weight: str) -> Contest:  # fmt: skip
    return Contest(
        id=contest_id,
        competition_id=competition_id,
        blue_id=blue,
        white_id=white,
        winner_id=winner,
        weight=weight,
        round=0,
    )


def add_contests() -> None:
    """Athletes 1, 2, 3: two contests in March at -73, one in June."""
    with Session(engine) as session:
        session.add(Country(id=1, name="Japan", ioc="JPN"))
        session.add(Competition(id=10, name="Grand Slam", date_from=date(2026, 3, 1)))
        session.add(Competition(id=20, name="June", date_from=date(2026, 6, 1)))
        session.flush()
        session.add_all(Athlete(id=i, family_name=f"A{i}", country_id=1) for i in (1, 2, 3))
        session.flush()
        session.add_all(
            [
                contest(101, 10, blue=1, white=2, winner=1, weight="-73"),
                contest(102, 10, blue=1, white=3, winner=3, weight="-73"),
                contest(201, 20, blue=2, white=3, winner=2, weight="-73"),
                contest(202, 20, blue=1, white=2, winner=None, weight="-73"),  # not fought yet
            ]
        )
        session.commit()


def changes() -> dict[tuple[int, int], RatingChange]:
    with Session(engine) as session:
        return {(c.contest_id, c.athlete_id): c for c in session.exec(select(RatingChange))}


def test_two_rows_per_decided_contest():
    add_contests()

    run_rating()

    rows = changes()
    assert set(rows) == {(101, 1), (101, 2), (102, 1), (102, 3), (201, 2), (201, 3)}
    winner, loser = rows[(101, 1)], rows[(101, 2)]
    assert (winner.won, loser.won) == (True, False)
    assert (winner.opponent_id, loser.opponent_id) == (2, 1)
    assert winner.win_probability + loser.win_probability == pytest.approx(1)
    assert winner.rating_after > winner.rating_before
    assert loser.rating_after < loser.rating_before


def test_next_fought_on_links_each_athlete_history():
    add_contests()

    run_rating()

    rows = changes()
    # Athlete 1 fought twice on March 1st: the first row is "closed" the same day.
    assert rows[(101, 1)].next_fought_on == date(2026, 3, 1)
    assert rows[(102, 1)].next_fought_on == LATEST
    assert rows[(101, 2)].next_fought_on == date(2026, 6, 1)
    assert rows[(201, 2)].next_fought_on == LATEST
    # The second contest starts from the state after the first one.
    assert rows[(102, 1)].rating_before == pytest.approx(rows[(101, 1)].rating_after)


def test_a_contest_dated_outside_its_competition_counts_on_the_competition_day():
    add_contests()
    with Session(engine) as session:
        # judobase: the June contest started in February, before the March Grand Slam
        session.execute(
            update(Contest).where(Contest.id == 201).values(started_at=datetime(2026, 2, 3, 10))
        )
        # a contest that started the day before its competition stays on its own day
        session.execute(
            update(Contest).where(Contest.id == 101).values(started_at=datetime(2026, 2, 28, 18))
        )
        session.commit()

    run_rating()

    rows = changes()
    assert rows[(201, 2)].fought_on == date(2026, 6, 1)
    assert rows[(101, 1)].fought_on == date(2026, 2, 28)
    # every athlete's history in rating order runs forward in time, so one row holds at a time
    with Session(engine) as session:
        for athlete in (1, 2, 3):
            query = select(RatingChange).where(RatingChange.athlete_id == athlete)
            history = session.exec(query.order_by(RatingChange.seq)).all()
            days = [row.fought_on for row in history]
            assert days == sorted(days)


def test_a_contest_without_a_time_counts_after_the_athletes_earlier_ones():
    add_contests()
    with Session(engine) as session:
        session.add(Competition(id=30, name="Two days", date_from=date(2026, 9, 18),
                                date_to=date(2026, 9, 19)))  # fmt: skip
        session.flush()
        # rated in this order: 1 v 2 on the 19th, then 1 v 3 with no time (the 18th)
        session.add(contest(301, 30, blue=1, white=2, winner=1, weight="-73"))
        session.add(contest(302, 30, blue=1, white=3, winner=1, weight="-73"))
        session.commit()
        session.execute(update(Contest).where(Contest.id == 301).values(round=1,
                        started_at=datetime(2026, 9, 19, 10)))  # fmt: skip
        session.commit()

    run_rating()

    rows = changes()
    assert rows[(301, 1)].fought_on == date(2026, 9, 19)
    assert rows[(302, 1)].fought_on == date(2026, 9, 19)  # not before 1's contest of the 19th
    assert rows[(301, 1)].next_fought_on == date(2026, 9, 19)


def test_only_real_fights_are_rated():
    add_contests()
    with Session(engine) as session:
        session.add(Competition(id=30, name="Paralympic Games", date_from=date(2026, 7, 1),
                                kind="para"))  # fmt: skip
        session.add(Competition(id=40, name="Grand Prix", date_from=date(2026, 8, 1)))
        session.flush()
        session.add_all(
            [
                contest(301, 30, blue=1, white=2, winner=1, weight="-73"),  # another kind
                contest(401, 40, blue=1, white=2, winner=1, weight="Open"),  # another category
                contest(402, 40, blue=1, white=3, winner=1, weight="-73"),  # a walkover
                contest(403, 40, blue=2, white=3, winner=2, weight="-73"),  # flagged a bye
                contest(404, 40, blue=2, white=1, winner=2, weight="-73"),  # 0:00, fought
            ]
        )
        session.flush()
        session.add(ContestWalkover(contest_id=402, reason="fusen"))
        session.execute(update(Contest).where(Contest.id == 403).values(bye=True))
        session.execute(update(Contest).where(Contest.id == 404).values(duration="00:00:00"))
        session.commit()

    run_rating()

    assert {c for c, _ in changes()} == {101, 102, 201, 403, 404}


def test_settings_are_saved():
    add_contests()

    run_rating()

    with Session(engine) as session:
        settings = session.get(RatingSettings, 1)
    assert settings.rd_growth == RatingParams().rd_growth
    assert settings.rd_factor == 3


def test_running_again_replaces_the_rows():
    add_contests()
    run_rating()
    first = changes()

    run_rating()

    assert changes() == first


def test_sync_can_delete_a_rated_contest():
    add_contests()
    run_rating()

    with Session(engine) as session:
        session.execute(delete(Contest).where(Contest.id == 101))
        session.commit()

    assert (101, 1) not in changes()


def test_command_line_run_is_logged():
    add_contests()

    main([])

    with Session(engine) as session:
        [run] = session.exec(select(JobRun)).all()
    assert (run.type, run.status) == ("rating", "success")
    assert len(changes()) == 6


# --- recomputing only what changed -------------------------------------------


def rate(full: bool = False) -> None:
    with job_run("rating_full" if full else "rating"):
        run_rating(full=full)


def mark_changed(competition_id: int) -> None:
    """What the sync does when a result of the competition appears, changes or vanishes."""
    with Session(engine) as session:
        session.execute(
            update(Competition)
            .where(Competition.id == competition_id)
            .values(results_changed_at=func.now())
        )
        session.commit()


def without_seq(rows: dict) -> dict:
    """Rows to compare: seq only orders them and may have gaps after deletions."""
    return {key: row.model_dump(exclude={"seq"}) for key, row in rows.items()}


def assert_same_as_full_run() -> None:
    since_change = without_seq(changes())
    rate(full=True)
    assert since_change == without_seq(changes())


def test_new_competition_is_rated_from_its_day():
    add_contests()
    rate()
    with Session(engine) as session:
        session.add(Competition(id=30, name="Later", date_from=date(2026, 9, 1)))
        session.flush()
        session.add(contest(301, 30, blue=3, white=1, winner=3, weight="-73"))
        session.commit()
    mark_changed(30)

    rate()

    rows = changes()
    assert (301, 1) in rows and (301, 3) in rows
    assert rows[(102, 1)].next_fought_on == date(2026, 9, 1)  # linked to the new contest
    assert_same_as_full_run()


def test_corrected_result_in_the_past_is_rated_again():
    add_contests()
    rate()
    with Session(engine) as session:
        session.execute(update(Contest).where(Contest.id == 101).values(winner_id=2))
        session.commit()
    mark_changed(10)

    rate()

    assert changes()[(101, 2)].won is True
    assert_same_as_full_run()


def test_removed_contest_in_the_past():
    add_contests()
    rate()
    with Session(engine) as session:
        session.execute(delete(Contest).where(Contest.id == 102))
        session.commit()
    mark_changed(10)

    rate()

    assert (102, 1) not in changes()
    assert changes()[(101, 1)].next_fought_on == LATEST  # athlete 1 has no later contest now
    assert_same_as_full_run()


def test_nothing_changed_nothing_to_do(caplog):
    add_contests()
    rate()
    before = without_seq(changes())

    with caplog.at_level("INFO"):
        rate()

    assert "No results changed" in caplog.text
    assert without_seq(changes()) == before


def test_changed_parameters_rate_everything():
    add_contests()
    rate()
    # Athlete 2 rested three months before contest 201: RD growth matters there.
    old = changes()[(201, 2)].rd_before

    with job_run("rating"):
        run_rating(params=RatingParams(rd_growth=8))

    assert changes()[(201, 2)].rd_before > old
    with Session(engine) as session:
        assert session.get(RatingSettings, 1).rd_growth == 8


def test_empty_rating_table_rates_everything():
    """As right after a migration that empties rating_change."""
    add_contests()
    rate()
    with Session(engine) as session:
        session.execute(delete(RatingChange))
        session.commit()

    rate()

    assert len(changes()) == 6


# --- checks before commit ----------------------------------------------------


def test_an_inconsistent_history_fails_the_run_and_keeps_the_last_rating():
    add_contests()
    rate()
    with Session(engine) as session:
        # athlete 1's next contest before this one, as a bug in the dates would leave it
        session.execute(
            update(RatingChange)
            .where(RatingChange.contest_id == 101, RatingChange.athlete_id == 1)
            .values(next_fought_on=date(2026, 1, 1))
        )
        session.commit()
    before = without_seq(changes())

    with pytest.raises(RatingCheckError, match="1 athletes whose history is out of time order"):
        rate()

    assert without_seq(changes()) == before
    with Session(engine) as session:
        last = session.exec(select(JobRun).order_by(JobRun.id.desc())).first()
    assert last.status == "failed"
    assert "RatingCheckError" in last.error


# --- telling the site to refresh ---------------------------------------------


def rate_and_tell() -> bool:
    with job_run("rating"):
        return run_rating().changed


def test_a_run_says_whether_the_site_may_have_changed():
    add_contests()
    assert rate_and_tell() is True  # the first rating

    assert rate_and_tell() is False  # nothing new, the same day, no draw

    with Session(engine) as session:
        session.execute(update(Contest).where(Contest.id == 101).values(winner_id=2))
        session.commit()
    mark_changed(10)
    assert rate_and_tell() is True


def test_the_command_line_writes_the_answer_for_the_workflow(tmp_path, monkeypatch):
    add_contests()
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    main([])
    main([])

    assert output.read_text() == "changed=true\ncorrected=0\nchanged=false\ncorrected=0\n"


# --- the nightly full run --------------------------------------------------------


def test_a_full_run_on_a_right_history_corrects_nothing():
    add_contests()
    rate()

    with job_run("rating_full"):
        assert run_rating(full=True).corrected == 0


def test_a_full_run_reports_the_rows_it_corrected():
    add_contests()
    rate()
    with Session(engine) as session:
        # as a missed change would leave it: a contest whose rating is off
        session.execute(
            update(RatingChange)
            .where(RatingChange.contest_id == 101, RatingChange.athlete_id == 1)
            .values(rating_after=RatingChange.rating_after + 1)
        )
        session.commit()

    with job_run("rating_full"):
        assert run_rating(full=True).corrected == 1


# --- a change of weight category ------------------------------------------------

# A share large enough to see in the test's few contests.
MOVES = RatingParams(move_handicap=0.25)


def test_a_move_up_starts_lower_and_a_move_back_starts_higher():
    from ajr.rating.engine import ContestRecord, run

    def fought(contest_id, day, weight, blue, white):
        return ContestRecord(contest_id, day, weight, blue, white, True, False, False)

    contests = [
        fought(1, date(2026, 1, 1), "-73", 1, 2),
        fought(2, date(2026, 2, 1), "-81", 1, 3),  # 1 moves up
        fought(3, date(2026, 3, 1), "Open", 1, 3),  # the open category is no move
        fought(4, date(2026, 4, 1), "-73", 1, 2),  # and back down
    ]
    plain = run(contests, RatingParams(move_handicap=0))
    moved = run(contests, MOVES)

    after_first = moved[0].blue_after.rating
    assert moved[1].blue_before.rating == pytest.approx(after_first * 0.75)
    assert moved[1].white_before == plain[1].white_before  # 3's first contest: no move
    after_open = moved[2].blue_after.rating
    assert moved[2].blue_before.rating == pytest.approx(moved[1].blue_after.rating)  # grown RD only
    assert moved[3].blue_before.rating == pytest.approx(after_open * 1.25)
    assert plain[1].blue_before.rating == pytest.approx(plain[0].blue_after.rating)


def test_a_move_between_runs_is_rated_as_in_a_full_run():
    add_contests()
    with job_run("rating"):
        run_rating(params=MOVES)
    with Session(engine) as session:
        session.add(Competition(id=30, name="Later", date_from=date(2026, 9, 1)))
        session.flush()
        session.add(contest(301, 30, blue=1, white=3, winner=1, weight="-81"))  # 1 and 3 move up
        session.commit()
    mark_changed(30)

    with job_run("rating"):
        run_rating(params=MOVES)

    since_change = without_seq(changes())
    before_move = changes()[(102, 1)].rating_after
    assert changes()[(301, 1)].rating_before < before_move  # the handicap applied
    with job_run("rating_full"):
        assert run_rating(full=True, params=MOVES).corrected == 0
    assert since_change == without_seq(changes())


# --- which weights' tables list an athlete -----------------------------------------


def add_tournaments(athlete_id: int, weights: list[str], first_id: int) -> None:
    """One competition a month from January 2026, one contest each against a new
    opponent, in the given weights in turn."""
    with Session(engine) as session:
        if session.get(Country, 1) is None:
            session.add(Country(id=1, name="Japan", ioc="JPN"))
        for i, weight in enumerate(weights):
            competition_id, opponent = first_id + i, 1000 + first_id + i
            session.add(Competition(id=competition_id, name=f"C{competition_id}",
                                    date_from=date(2026, 1 + i, 1)))  # fmt: skip
            session.merge(Athlete(id=athlete_id, family_name=f"A{athlete_id}", country_id=1))
            session.add(Athlete(id=opponent, family_name=f"O{opponent}", country_id=1))
            session.flush()
            session.add(contest(competition_id * 10, competition_id, blue=athlete_id,
                                white=opponent, winner=athlete_id, weight=weight))  # fmt: skip
        session.commit()


def tables_listing(athlete_id: int, day: date) -> set[str]:
    from sqlalchemy import text

    with Session(engine) as session:
        return {
            weight
            for weight in ("-73", "-81")
            if session.execute(
                text("select 1 from ajr.board_at(:w, :d) where athlete_id = :a"),
                {"w": weight, "d": day, "a": athlete_id},
            ).first()
        }


def test_an_athlete_fighting_in_two_weights_stands_in_both_tables():
    add_tournaments(1, ["-73", "-73", "-73", "-81", "-81", "-81"], first_id=100)
    rate()

    assert tables_listing(1, date(2026, 3, 15)) == {"-73"}
    assert tables_listing(1, date(2026, 5, 15)) == {"-73"}  # two tournaments in -81: a try-on
    assert tables_listing(1, date(2026, 6, 15)) == {"-73", "-81"}
    with Session(engine) as session:
        summary = session.execute(
            text_("select weight from ajr.athlete_summary where athlete_id = 1")
        ).scalar_one()
    assert summary == "-81"  # the latest contest's weight, which lists them


def test_a_try_on_of_another_weight_leaves_the_athlete_in_their_own():
    add_tournaments(2, ["-73", "-73", "-73", "-81"], first_id=200)
    rate()

    assert tables_listing(2, date(2026, 4, 15)) == {"-73"}
    with Session(engine) as session:
        summary = session.execute(
            text_("select weight from ajr.athlete_summary where athlete_id = 2")
        ).scalar_one()
    assert summary == "-73"


def test_tables_after_runs_since_changes_are_as_in_a_full_run():
    add_tournaments(3, ["-73", "-73", "-73", "-81", "-81"], first_id=300)
    rate()
    add_tournaments(3, ["-81"], first_id=306)  # the third tournament in -81, in July
    with Session(engine) as session:
        session.execute(
            update(Competition).where(Competition.id == 306).values(date_from=date(2026, 7, 1))
        )
        session.commit()
    mark_changed(306)
    rate()

    assert tables_listing(3, date(2026, 7, 15)) == {"-73", "-81"}
    listing_before = listing_rows()
    assert_same_as_full_run()
    assert listing_rows() == listing_before


def listing_rows() -> set[tuple]:
    from ajr.core.models import RatingListing

    with Session(engine) as session:
        return {
            (r.contest_id, r.athlete_id, r.weight, r.fought_on, r.next_fought_on)
            for r in session.exec(select(RatingListing))
        }


def text_(sql: str):
    from sqlalchemy import text

    return text(sql)


# --- the facts the athlete's page reads (docs/audits/2026-11-08-b1-plan.md) ---


def summaries() -> dict[int, dict]:
    with Session(engine) as session:
        return {s.athlete_id: s.model_dump() for s in session.exec(select(AthleteSummary))}


def test_history_rows_carry_their_facts():
    add_contests()
    with Session(engine) as session:
        session.execute(
            update(Contest).where(Contest.id == 101).values(round_name="Final", fight_no=7)
        )
        session.commit()

    rate()

    rows = changes()
    row = rows[(101, 1)]
    assert (row.competition_id, row.round, row.fight_no, row.round_name) == (10, 0, 7, "F")
    assert row.opponent_rating_before == rows[(101, 2)].rating_before
    assert row.opponent_rd_before == rows[(101, 2)].rd_before
    assert (row.opponent_family_name, row.opponent_country) == ("A2", "JPN")


def test_facts_follow_a_renamed_opponent():
    add_contests()
    rate()
    with Session(engine) as session:
        session.execute(update(Athlete).where(Athlete.id == 2).values(family_name="Renamed"))
        session.commit()

    rate()  # no result changed

    assert changes()[(101, 1)].opponent_family_name == "Renamed"


def test_rows_without_facts_fail_the_check(monkeypatch):
    add_contests()
    monkeypatch.setattr(snapshot, "HISTORY_FACTS", text_("select 1"))

    with pytest.raises(RatingCheckError, match="without their history facts"):
        rate()


def test_the_page_values_are_as_after_a_full_run():
    add_contests()
    rate()
    with Session(engine) as session:
        session.add(Competition(id=30, name="Later", date_from=date(2026, 9, 1)))
        session.flush()
        session.add(contest(301, 30, blue=3, white=1, winner=3, weight="-73"))
        session.commit()
    mark_changed(30)
    rate()
    since_change = summaries()

    rate(full=True)

    assert summaries() == since_change
    one = since_change[1]
    assert one["rating"] is not None and one["score_today"] is not None
    assert one["peak_on"] is not None


def test_nations_count_their_rated_athletes():
    add_contests()

    rate()

    with Session(engine) as session:
        nations = session.exec(select(NationSummary)).all()
    assert [(n.country, n.athletes) for n in nations] == [("JPN", 3)]


def peak_place_from_the_table(athlete_id: int) -> int | None:
    with Session(engine) as session:
        return session.execute(
            text_(
                "select b.place from ajr.athlete_summary s"
                " cross join lateral ajr.board_at(s.peak_weight, s.peak_on) b"
                " where s.athlete_id = :a and b.athlete_id = :a"
            ),
            {"a": athlete_id},
        ).scalar()


def test_the_peak_place_follows_a_corrected_history():
    add_contests()
    rate()
    assert summaries()[3]["peak_place"] == peak_place_from_the_table(3)
    with Session(engine) as session:  # judobase corrected the March contest
        session.execute(update(Contest).where(Contest.id == 102).values(winner_id=1))
        session.commit()
    mark_changed(10)

    rate()

    assert summaries()[3]["peak_place"] == peak_place_from_the_table(3)
    assert summaries()[1]["peak_place"] == peak_place_from_the_table(1)


# --- the facts the tournament and country pages read (docs/audits/2026-11-08-b2-plan.md) ---


def test_the_contest_list_has_the_scores_and_the_walkovers():
    add_contests()
    with Session(engine) as session:
        session.add(contest(103, 10, blue=2, white=3, winner=2, weight="-73"))
        session.flush()
        session.add(ContestWalkover(contest_id=103, reason="fusen"))
        session.commit()

    rate()

    with Session(engine) as session:
        rows = {
            r["contest_id"]: r
            for r in session.execute(text_("select * from ajr.contest_list")).mappings()
        }
    assert {101, 103} <= set(rows), sorted(rows)
    rated, walkover = rows[101], rows[103]
    assert rated["real_fight"] and rated["white_score_before"] is not None
    assert rated["blue_score_after"] is not None
    assert not walkover["real_fight"]
    assert walkover["white_chance"] is None and walkover["white_score_before"] is None


def test_tournament_and_nation_facts():
    add_contests()

    rate()

    with Session(engine) as session:
        result = session.execute(
            text_(
                "select family_name, country from ajr.athlete_competition"
                " where athlete_id = 1 and competition_id = 10"
            )
        ).one()
        stats = session.exec(
            select(CompetitionStats).where(CompetitionStats.competition_id == 10)
        ).one()
        nations = session.execute(
            text_("select country, date_from from ajr.nation_competition where competition_id = 10")
        ).all()
        summary = session.exec(select(NationSummary)).one()
    assert tuple(result) == ("A1", "JPN")
    assert (stats.name, stats.date_from) == ("Grand Slam", date(2026, 3, 1))
    assert nations == [("JPN", date(2026, 3, 1))]
    assert summary.top1 is not None and summary.top8 is not None


def test_a_run_without_new_results_completes_a_list_a_migration_left_incomplete():
    add_contests()
    rate()
    with Session(engine) as session:  # as after a migration adding the scores
        session.execute(text_("update ajr.contest_list set white_score_before = null"))
        session.commit()

    rate()  # no result changed

    with Session(engine) as session:
        missing = session.execute(
            text_("select count(*) from ajr.contest_list where white_score_before is null")
        ).scalar()
    assert missing == 0


def test_stages_count_from_the_final():
    """One code per stage of a draw (ajr.fill_stages), whatever judobase calls it."""
    add_data()
    with Session(engine) as session:
        session.add(Competition(id=60, name="Draws", date_from=date(2026, 1, 1)))
        session.flush()
        rounds = [
            # a knockout draw named "Round N" from the start: the round number says
            ("-60", "Round 4", 3), ("-60", "Round 1", 6), ("-60", "Quarter-Final", 2),
            ("-60", "Semi Final", 1), ("-60", "Final", 0), ("-60", "Bronze", 0),
            ("-60", "Repechage", 1), ("-66", "best 16", 3), ("-66", "Round of 32", 4),
            ("-66", "\u00b8Round 3", 2),  # a stray character, the draw a knockout
            # a round robin: tours
            ("-73", "Round 1", 2), ("-73", "Round 2", 1), ("-73", "?", 0),
        ]  # fmt: skip
        for i, (weight, name, number) in enumerate(rounds):
            contest = Contest(id=600 + i, competition_id=60, blue_id=1, white_id=2, winner_id=1,
                              weight=weight, round=number, round_name=name)  # fmt: skip
            session.add(contest)
        session.commit()
        session.execute(text("select ajr.fill_stages(array[60])"))
        session.commit()
        stages = dict(session.execute(text(
            "select id, stage from ajr.contest where competition_id = 60"
        )).all())  # fmt: skip

    assert [stages[600 + i] for i in range(len(rounds))] == [
        "1/8", "1/64", "1/4", "1/2", "F", "BR", "REP", "1/8", "1/16", "R3", "R1", "R2", None,
    ]  # fmt: skip
