"""ajr.sync.walkovers: which decided contests were walkovers."""

from datetime import datetime
from types import SimpleNamespace

from ajr.sync.walkovers import FUSEN, LIKELY, walkovers

HAJIME = datetime(2026, 3, 1, 10, 0)


def fight(contest_id, white, blue, winner, *, duration="0:02:13", hajime=HAJIME, ippon=(0, 0),
          waza=(0, 0), round=3, fight_no=None, events=None, bye=False):  # fmt: skip
    return SimpleNamespace(
        id_fight=contest_id, id_person_white=white, id_person_blue=blue, id_winner=winner,
        duration=duration, first_hajime_at_ts=hajime, bye=bye, id_weight=3, round=round,
        fight_no=fight_no or contest_id, events=events,
        ippon_w=ippon[0], ippon_b=ippon[1], waza_w=waza[0], waza_b=waza[1],
        yuko_w=0, yuko_b=0, penalty_w=0, penalty_b=0, hsk_w=0, hsk_b=0,
    )  # fmt: skip


def scoreboard() -> list:
    """A competition with a working scoreboard: 25 timed fights with a hajime."""
    return [fight(1000 + i, 500 + i, 600 + i, 500 + i, waza=(1, 0)) for i in range(25)]


def tagged(name):
    return [SimpleNamespace(time_sc=0, tags=[SimpleNamespace(name=name)])]


def test_a_fusen_gachi_tag_is_a_walkover():
    items = scoreboard() + [fight(1, 10, 20, 10, duration="00:00:00", ippon=(1, 0),
                                  events=tagged("Fusen-Gachi"))]  # fmt: skip
    assert walkovers(items) == {1: FUSEN}


def test_a_kiken_gachi_was_fought():
    items = scoreboard() + [fight(1, 10, 20, 10, duration="00:00:00", hajime=None,
                                  ippon=(1, 0), events=tagged("Kiken-gachi"))]  # fmt: skip
    assert walkovers(items) == {}


def test_nothing_fought_on_a_scoreboard_and_the_loser_gone_is_a_walkover():
    items = scoreboard() + [fight(1, 10, 20, 10, duration="00:00:00", hajime=None, ippon=(1, 0))]
    assert walkovers(items) == {1: LIKELY}


def test_a_zero_time_fight_with_scores_or_a_hajime_is_a_fight():
    items = scoreboard() + [
        fight(1, 10, 20, 10, duration="00:00:00", hajime=None, waza=(1, 0)),  # scores
        fight(2, 11, 21, 11, duration="00:00:00", ippon=(1, 0)),  # a hajime
        fight(
            3,
            12,
            22,
            12,
            duration="00:00:00",
            hajime=None,
            ippon=(1, 0),
            events=[SimpleNamespace(time_sc=42, tags=None)],
        ),  # the clock ran  # fmt: skip
    ]
    assert walkovers(items) == {}


def test_a_loser_who_fights_on_did_not_miss_the_contest():
    items = scoreboard() + [
        fight(1, 10, 20, 10, duration="00:00:00", hajime=None, ippon=(1, 0), round=3),
        fight(2, 20, 30, 20, round=2),  # 20 fights a later round (repechage)
    ]
    assert walkovers(items) == {}


def test_without_a_scoreboard_only_the_tag_counts():
    items = [fight(1000 + i, 500 + i, 600 + i, 500 + i, hajime=None) for i in range(25)]
    items.append(fight(1, 10, 20, 10, duration="00:00:00", hajime=None, ippon=(1, 0)))
    assert walkovers(items) == {}
