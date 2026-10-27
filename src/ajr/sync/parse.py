"""Convert judobase objects into our models.

judobase already returns typed values (ints, dates, None for unknown), so here we
only map its fields to our columns.
"""

import judobase

from ajr.core.models import Athlete, Competition, Contest, Country


def text(value: str | None) -> str | None:
    """Trimmed text; an empty text becomes None."""
    if value is None:
        return None
    return value.strip() or None


def country(item: judobase.CountryShort) -> Country:
    return Country(id=item.id_country, name=text(item.name), ioc=text(item.ioc))


def competition(item: judobase.Competition) -> Competition:
    return Competition(
        id=item.id_competition,
        name=text(item.name),
        date_from=item.date_from,
        date_to=item.date_to,
        rank_name=text(item.rank_name),
        competition_code=text(item.competition_code),
        city=text(item.city),
        timezone=text(item.timezone),
        is_teams=item.is_teams,
        # judobase gives the number of results; we only need to know if there are any.
        has_results=bool(item.has_results),
        country_id=item.id_country,
        updated_at=item.updated_at_ts,
    )


def contest(item: judobase.Contest) -> Contest:
    return Contest(
        id=item.id_fight,
        competition_id=item.id_competition,
        blue_id=item.id_person_blue,
        white_id=item.id_person_white,
        winner_id=item.id_winner,
        is_finished=item.is_finished,
        contest_code=text(item.contest_code_long),
        age=text(item.age),
        weight=text(item.weight),
        id_weight=item.id_weight,
        round=item.round,
        round_code=text(item.round_code),
        round_name=text(item.round_name),
        fight_no=item.fight_no,
        started_at=item.date_start_ts,
        duration=text(item.duration),
        golden_score=item.gs,
        bye=item.bye,
        ippon_w=item.ippon_w,
        waza_w=item.waza_w,
        yuko_w=item.yuko_w,
        penalty_w=item.penalty_w,
        hsk_w=item.hsk_w,
        ippon_b=item.ippon_b,
        waza_b=item.waza_b,
        yuko_b=item.yuko_b,
        penalty_b=item.penalty_b,
        hsk_b=item.hsk_b,
    )


def athlete(item: judobase.Judoka, athlete_id: int) -> Athlete:
    """The profile has no id of its own: it is the one we asked for."""
    return Athlete(
        id=athlete_id,
        family_name=text(item.family_name),
        given_name=text(item.given_name),
        gender=text(item.gender),
        dob_year=item.dob_year,
        country_id=item.id_country,
    )


def gender_from_contest_code(code: str | None) -> str | None:
    """'wc_sen2025_0002_f_0p78_0001' -> 'female'."""
    parts = (code or "").split("_")
    if len(parts) < 4:
        return None
    return {"m": "male", "f": "female"}.get(parts[3])


def blue_athlete(item: judobase.Contest) -> Athlete | None:
    """Athlete from the names inside a contest, used when the profile can't be fetched."""
    if item.id_person_blue is None:
        return None
    return Athlete(
        id=item.id_person_blue,
        family_name=text(item.family_name_blue),
        given_name=text(item.given_name_blue),
        gender=gender_from_contest_code(item.contest_code_long),
        country_id=item.id_country_blue,
    )


def white_athlete(item: judobase.Contest) -> Athlete | None:
    if item.id_person_white is None:
        return None
    return Athlete(
        id=item.id_person_white,
        family_name=text(item.family_name_white),
        given_name=text(item.given_name_white),
        gender=gender_from_contest_code(item.contest_code_long),
        country_id=item.id_country_white,
    )
