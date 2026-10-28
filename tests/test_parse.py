from datetime import date

from fake_judobase import competition, contest

from ajr.sync import parse


def test_text_is_trimmed_and_empty_becomes_none():
    assert parse.text("  Paris ") == "Paris"
    assert parse.text("   ") is None
    assert parse.text(None) is None


def test_gender_from_contest_code():
    assert parse.gender_from_contest_code("wc_sen2025_0002_f_0p78_0001") == "female"
    assert parse.gender_from_contest_code("gs_fra2024_0001_m_0073_0001") == "male"
    assert parse.gender_from_contest_code("broken") is None
    assert parse.gender_from_contest_code(None) is None


def test_has_results_count_becomes_a_flag():
    assert parse.competition(competition(1, date(2024, 1, 1), has_results=112)).has_results
    assert not parse.competition(competition(1, date(2024, 1, 1), has_results=0)).has_results


def test_contest_maps_fields():
    row = parse.contest(contest(10, 1, blue=100, white=200, winner=200))

    assert (row.id, row.competition_id) == (10, 1)
    assert (row.blue_id, row.white_id, row.winner_id) == (100, 200, 200)
    assert row.is_finished is True
    assert row.contest_code == "gs_fra2024_0001_m_0073_0001"
    assert row.bye is False


def test_contest_before_the_draw_has_no_fighters():
    row = parse.contest(contest(10, 1, blue=0, white=0, winner=0))

    assert (row.blue_id, row.white_id, row.winner_id) == (None, None, None)
    assert row.is_finished is False


def test_athletes_from_contest():
    item = contest(10, 1, blue=100, white=200, winner=200, code="wc_x_0001_f_0p78_0001")

    blue = parse.blue_athlete(item)
    white = parse.white_athlete(item)

    assert (blue.id, blue.family_name, blue.gender) == (100, "BLUE100", "female")
    assert (white.id, white.family_name, white.gender) == (200, "WHITE200", "female")
    assert parse.blue_athlete(contest(10, 1, blue=0, white=0, winner=0)) is None
