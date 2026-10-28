"""A fake judobase for sync tests.

Objects are built from raw values the way the real API sends them ("0" for unknown,
"YYYY/MM/DD" days, millisecond timestamps), so the judobase library parses them as
in production.
"""

from datetime import UTC, date, datetime

import judobase

# A moment judobase reports as `updated_at_ts` (seconds).
UPDATED = "1733305817"
UPDATED_LATER = "1733400000"


def country(country_id: int, name: str = "Japan", ioc: str = "JPN") -> judobase.CountryShort:
    return judobase.CountryShort(id_country=str(country_id), name=name, ioc=ioc)


def competition(
    competition_id: int,
    starts: date,
    ends: date | None = None,
    *,
    name: str = "Grand Slam",
    has_results: int = 100,
    updated: str = UPDATED,
    country_id: int = 1,
) -> judobase.Competition:
    return judobase.Competition(
        id_competition=str(competition_id),
        name=name,
        date_from=starts.strftime("%Y/%m/%d"),
        date_to=(ends or starts).strftime("%Y/%m/%d"),
        has_results=str(has_results),
        city="Paris",
        updated_at_ts=updated,
        id_live_theme=1,
        code_live_theme="theme",
        country_short="FRA",
        country="France",
        id_country=str(country_id),
        is_teams="0",
        rank_name="Grand Slam",
    )


def contest(
    contest_id: int,
    competition_id: int,
    blue: int,
    white: int,
    winner: int,
    *,
    code: str = "gs_fra2024_0001_m_0073_0001",
    blue_country: int = 1,
    white_country: int = 1,
) -> judobase.Contest:
    """Fighter and winner id 0 means "not known yet", as in judobase."""
    return judobase.Contest(
        id_competition=str(competition_id),
        id_fight=str(contest_id),
        id_person_blue=str(blue),
        id_person_white=str(white),
        id_winner=str(winner),
        is_finished="1" if winner else "0",
        round=1,
        duration="0:02:13",
        gs="0",
        bye="0",
        weight="-73",
        id_weight="3",
        type=1,
        round_code="r1",
        round_name="Round 1",
        mat=1,
        date_start_ts="1722499268000",
        updated_at="2024-08-03 01:13:11",
        first_hajime_at_ts="0",
        person_white=f"WHITE {white}",
        id_ijf_white="0",
        family_name_white=f"WHITE{white}",
        given_name_white="White",
        timestamp_version_white="0",
        id_country_white=str(white_country),
        person_blue=f"BLUE {blue}",
        id_ijf_blue="0",
        family_name_blue=f"BLUE{blue}",
        given_name_blue="Blue",
        timestamp_version_blue="0",
        id_country_blue=str(blue_country),
        competition_name="Grand Slam",
        external_id="x",
        city="Paris",
        age="Seniors",
        competition_date="2024-07-27",
        date_raw="2024-07-27",
        comp_year="2024",
        tagged=0,
        kodokan_tagged=0,
        published="1",
        sc_countdown_offset=0,
        fight_no=contest_id,
        contest_code_long=code,
    )


def profile(
    family_name: str, *, gender: str = "male", country_id: int = 1, dob_year: str = "2000"
) -> judobase.Judoka:
    return judobase.Judoka(
        family_name=family_name,
        given_name="Given",
        family_name_local=None,
        given_name_local=None,
        gender=gender,
        folder=None,
        picture_filename=None,
        side=None,
        coach=None,
        height=None,
        birth_date="1970-01-01",
        country="Japan",
        id_country=str(country_id),
        country_short="JPN",
        categories=[],
        dob_year=dob_year,
    )


def ranking_entry(
    athlete_id: int, weight_id: int, place: int, points: int
) -> judobase.RankingEntry:
    return judobase.RankingEntry(
        id_person=str(athlete_id),
        id_age="1" if weight_id <= 7 else "2",
        id_weight=str(weight_id),
        place=str(place),
        sum_points=str(points),
    )


class FakeJudobase:
    """Stands in for JudobaseClient and records which contests and profiles were asked for."""

    def __init__(self) -> None:
        self.countries_list: list[judobase.CountryShort] = [country(1)]
        self.competitions_list: list[judobase.Competition] = []
        self.contests_of: dict[int, list[judobase.Contest]] = {}
        self.profiles: dict[int, judobase.Judoka] = {}
        self.broken_competitions: set[int] = set()
        self.ranking: list[judobase.RankingEntry] = []
        self.ranking_broken = False
        self.contest_requests: list[int] = []
        self.profile_requests: list[int] = []

    async def __aenter__(self) -> FakeJudobase:
        return self

    async def __aexit__(self, *exc) -> None:
        pass

    async def countries(self) -> list[judobase.CountryShort]:
        return self.countries_list

    async def competitions(self) -> list[judobase.Competition]:
        return self.competitions_list

    async def contests(self, competition_id: int) -> list[judobase.Contest]:
        self.contest_requests.append(competition_id)
        if competition_id in self.broken_competitions:
            raise ConnectionError("500")
        return self.contests_of.get(competition_id, [])

    async def world_ranking(self) -> list[judobase.RankingEntry]:
        if self.ranking_broken:
            raise ConnectionError("500")
        return self.ranking

    async def judoka(self, judoka_id: int) -> judobase.Judoka:
        self.profile_requests.append(judoka_id)
        if judoka_id not in self.profiles:
            raise ConnectionError("404")
        return self.profiles[judoka_id]


def utc(timestamp: str) -> datetime:
    """The datetime of an `updated_at_ts` value."""
    return datetime.fromtimestamp(int(timestamp), UTC)
