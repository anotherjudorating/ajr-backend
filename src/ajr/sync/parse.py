"""Convert judobase objects into rows for our tables.

judobase returns most values as strings ("1", "0", "2025/06/13") and uses "0" or ""
when something is unknown, so all cleanup happens here.
"""

from datetime import UTC, date, datetime

from judobase.schemas import Competition, Contest, CountryShort, Judoka


def parse_int(value) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def parse_id(value) -> int | None:
    """judobase uses 0 for "no id" (e.g. no winner yet)."""
    number = parse_int(value)
    if number == 0:
        return None
    return number


def parse_bool(value) -> bool | None:
    if value is None or value == "":
        return None
    return str(value) not in ("0", "false", "False")


def parse_text(value, max_length: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_length]


def parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    # "2025/06/13" or "2025-06-13"
    return date.fromisoformat(str(value)[:10].replace("/", "-"))


def parse_datetime(value) -> datetime | None:
    """judobase sends 0 for an unknown time, which pydantic turns into 1970-01-01."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    if value.year <= 1970:
        return None
    return value


def country_row(country: CountryShort) -> dict:
    return {
        "id": int(country.id_country),
        "name": parse_text(country.name, 255),
        "ioc": parse_text(country.ioc, 10),
    }


def competition_row(competition: Competition) -> dict:
    return {
        "id": int(competition.id_competition),
        "name": parse_text(competition.name, 255),
        "date_from": parse_date(competition.date_from),
        "date_to": parse_date(competition.date_to),
        "rank_name": parse_text(competition.rank_name, 100),
        "competition_code": parse_text(competition.competition_code, 100),
        "city": parse_text(competition.city, 255),
        "timezone": parse_text(competition.timezone, 50),
        "is_teams": parse_bool(competition.is_teams),
        "has_results": parse_bool(competition.has_results),
        "country_id": parse_id(competition.id_country),
        "updated_at": parse_datetime(competition.updated_at_ts),
    }


def contest_row(contest: Contest) -> dict:
    return {
        "id": int(contest.id_fight),
        "competition_id": int(contest.id_competition),
        "blue_id": parse_id(contest.id_person_blue),
        "white_id": parse_id(contest.id_person_white),
        "winner_id": parse_id(contest.id_winner),
        "is_finished": bool(parse_bool(contest.is_finished)),
        "contest_code": parse_text(contest.contest_code_long, 100),
        "age": parse_text(contest.age, 50),
        "weight": parse_text(contest.weight, 50),
        "id_weight": parse_id(contest.id_weight),
        "round": parse_int(contest.round),
        "round_code": parse_text(contest.round_code, 50),
        "round_name": parse_text(contest.round_name, 100),
        "fight_no": parse_int(contest.fight_no),
        "started_at": parse_datetime(contest.date_start_ts),
        "duration": parse_text(contest.duration, 20),
        "golden_score": parse_bool(contest.gs),
        "bye": parse_bool(contest.bye),
        "ippon_w": parse_int(contest.ippon_w),
        "waza_w": parse_int(contest.waza_w),
        "yuko_w": parse_int(contest.yuko_w),
        "penalty_w": parse_int(contest.penalty_w),
        "hsk_w": parse_int(contest.hsk_w),
        "ippon_b": parse_int(contest.ippon_b),
        "waza_b": parse_int(contest.waza_b),
        "yuko_b": parse_int(contest.yuko_b),
        "penalty_b": parse_int(contest.penalty_b),
        "hsk_b": parse_int(contest.hsk_b),
    }


def judoka_row(judoka: Judoka, judoka_id: int) -> dict:
    return {
        "id": judoka_id,
        "family_name": parse_text(judoka.family_name, 255),
        "given_name": parse_text(judoka.given_name, 255),
        "gender": parse_text(judoka.gender, 10),
        "dob_year": parse_id(judoka.dob_year),
        "country_id": parse_id(judoka.id_country),
    }


def gender_from_contest_code(code: str | None) -> str | None:
    """'wc_sen2025_0002_f_0p78_0001' -> 'female'."""
    parts = (code or "").split("_")
    if len(parts) < 4:
        return None
    return {"m": "male", "f": "female"}.get(parts[3])


def blue_judoka_row(contest: Contest) -> dict | None:
    """Judoka row from the names inside a contest, used when the profile can't be fetched."""
    judoka_id = parse_id(contest.id_person_blue)
    if judoka_id is None:
        return None
    return {
        "id": judoka_id,
        "family_name": parse_text(contest.family_name_blue, 255),
        "given_name": parse_text(contest.given_name_blue, 255),
        "gender": gender_from_contest_code(contest.contest_code_long),
        "dob_year": None,
        "country_id": parse_id(contest.id_country_blue),
    }


def white_judoka_row(contest: Contest) -> dict | None:
    judoka_id = parse_id(contest.id_person_white)
    if judoka_id is None:
        return None
    return {
        "id": judoka_id,
        "family_name": parse_text(contest.family_name_white, 255),
        "given_name": parse_text(contest.given_name_white, 255),
        "gender": gender_from_contest_code(contest.contest_code_long),
        "dob_year": None,
        "country_id": parse_id(contest.id_country_white),
    }
