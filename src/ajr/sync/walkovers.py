"""Which decided contests of a competition were walkovers, not fights.

A contest that "lasted 0:00" is mostly a real fight whose time judobase lost (83% of
them have scores, and their losers fight on as often as after any fight), so 0:00
alone says nothing (docs/audits/2026-11-06-real-fights.md). A walkover is:

- tagged Fusen-Gachi by judobase (a kiken-gachi, an injury withdrawal, was fought), or
- nothing happened on a scoreboard that worked: no clock and no hajime, a score of a
  single ippon or none, in a competition whose timed fights have a hajime (90% or
  more of over 20), and the loser not seen again in the bracket.

Checked against the tag on competitions with a scoreboard: precision 98.6%, recall
95% from the contest fields alone; the scoreboard clock removes the false ones.
"""

import judobase

FUSEN = "fusen"  # Fusen-Gachi: the opponent did not appear
LIKELY = "likely"  # no tag, but nothing was fought (see the module's docstring)

TIMED_SHARE = 0.9
TIMED_MIN = 20


def tag(item: judobase.Contest) -> str | None:
    for event in item.events or []:
        for t in event.tags or []:
            name = (t.name or "").lower()
            if name.startswith("fusen"):
                return "fusen"
            if name.startswith("kiken"):
                return "kiken"
    return None


def clock(item: judobase.Contest) -> float:
    return max((event.time_sc or 0 for event in item.events or []), default=0)


def scores(item: judobase.Contest, side: str) -> tuple[int, int, int, int, int]:
    """(ippon, waza-ari, yuko, penalties, hansoku-make) of white ("w") or blue ("b")."""
    return tuple(
        getattr(item, f"{field}_{side}") or 0
        for field in ("ippon", "waza", "yuko", "penalty", "hsk")
    )


def ippon_only_or_blank(item: judobase.Contest) -> bool:
    winner = "w" if item.id_winner == item.id_person_white else "b"
    loser = "b" if winner == "w" else "w"
    won, lost = scores(item, winner), scores(item, loser)
    blank = not any(won) and not any(lost)
    ippon_only = won == (1, 0, 0, 0, 0) and not any(lost)
    return blank or ippon_only


def walkovers(items: list[judobase.Contest]) -> dict[int, str]:
    """contest id -> FUSEN or LIKELY, for the walkovers among one competition's contests."""
    decided = [i for i in items if i.id_winner is not None and not i.bye]
    timed = [i for i in decided if i.duration and i.duration != "00:00:00"]
    with_hajime = sum(i.first_hajime_at_ts is not None for i in timed)
    scoreboard = len(timed) > TIMED_MIN and with_hajime >= TIMED_SHARE * len(timed)

    # every athlete's (weight, round, fight number) in the bracket, for "seen again"
    appearances: dict[int, list[tuple]] = {}
    for i in items:
        for athlete in (i.id_person_white, i.id_person_blue):
            if athlete is not None:
                appearances.setdefault(athlete, []).append((i.id_weight, i.round, i.fight_no))

    def seen_again(item: judobase.Contest, loser: int | None) -> bool:
        # judobase counts rounds down to the final (0): a later contest has a smaller
        # round, or the same round and a bigger fight number
        here = (item.round or 0, item.fight_no or 0)
        return any(
            weight == item.id_weight
            and ((r or 0) < here[0] or ((r or 0) == here[0] and (n or 0) > here[1]))
            for weight, r, n in appearances.get(loser, [])
        )

    found: dict[int, str] = {}
    for i in decided:
        t = tag(i)
        if t == "fusen":
            found[i.id_fight] = FUSEN
            continue
        if t == "kiken" or not scoreboard:
            continue
        loser = i.id_person_blue if i.id_winner == i.id_person_white else i.id_person_white
        if (
            clock(i) == 0
            and i.first_hajime_at_ts is None
            and ippon_only_or_blank(i)
            and not seen_again(i, loser)
        ):
            found[i.id_fight] = LIKELY
    return found
