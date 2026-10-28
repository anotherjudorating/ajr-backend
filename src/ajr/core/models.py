"""Database tables, all in the `ajr` schema (not exposed by the Supabase Data API).

Ids of countries, athletes, competitions and contests are judobase ids.
"""

from datetime import date, datetime

from sqlalchemy import DateTime, Index
from sqlmodel import Field, SQLModel

SCHEMA = "ajr"
# Rows keyed by judobase ids: no sequence, the id always comes from the source.
EXTERNAL_ID = {"primary_key": True, "sa_column_kwargs": {"autoincrement": False}}


def fk(table: str) -> str:
    return f"{SCHEMA}.{table}.id"


class Country(SQLModel, table=True):
    __table_args__ = {"schema": SCHEMA}

    id: int = Field(**EXTERNAL_ID)
    name: str | None = None
    ioc: str | None = None


class Athlete(SQLModel, table=True):
    __table_args__ = {"schema": SCHEMA}

    id: int = Field(**EXTERNAL_ID)
    family_name: str | None = None
    given_name: str | None = None
    gender: str | None = None
    dob_year: int | None = None  # judobase only exposes the year of birth
    country_id: int | None = Field(default=None, foreign_key=fk("country"), index=True)


class OlympicCycle(SQLModel, table=True):
    __tablename__ = "olympic_cycle"
    __table_args__ = {"schema": SCHEMA}

    id: int = Field(**EXTERNAL_ID)
    name: str
    date_from: date
    date_to: date


class Competition(SQLModel, table=True):
    __table_args__ = {"schema": SCHEMA}

    id: int = Field(**EXTERNAL_ID)
    name: str | None = None
    date_from: date | None = Field(default=None, index=True)
    date_to: date | None = None
    rank_name: str | None = None
    competition_code: str | None = None
    city: str | None = None
    timezone: str | None = None
    is_teams: bool | None = None
    has_results: bool | None = None
    country_id: int | None = Field(default=None, foreign_key=fk("country"))
    olympic_cycle_id: int | None = Field(default=None, foreign_key=fk("olympic_cycle"), index=True)
    # judobase `updated_at_ts`, and its value when the contests were last synced.
    updated_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    contests_synced_for: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))


class Contest(SQLModel, table=True):
    """A fight, from the draw on. Fighters are unknown until the bracket reaches it,
    the winner until it is fought."""

    __table_args__ = {"schema": SCHEMA}

    id: int = Field(**EXTERNAL_ID)  # judobase id_fight
    competition_id: int = Field(foreign_key=fk("competition"), index=True)
    blue_id: int | None = Field(default=None, foreign_key=fk("athlete"), index=True)
    white_id: int | None = Field(default=None, foreign_key=fk("athlete"), index=True)
    winner_id: int | None = Field(default=None, foreign_key=fk("athlete"))
    is_finished: bool = False
    contest_code: str | None = None
    age: str | None = None
    weight: str | None = None
    id_weight: int | None = None  # judobase weight category id
    round: int | None = None
    round_code: str | None = None  # position in the bracket
    round_name: str | None = None
    fight_no: int | None = None
    started_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    duration: str | None = None
    golden_score: bool | None = None
    bye: bool | None = None  # walked through without an opponent: not a real fight
    # Scores: _w white, _b blue.
    ippon_w: int | None = None
    waza_w: int | None = None
    yuko_w: int | None = None
    penalty_w: int | None = None
    hsk_w: int | None = None
    ippon_b: int | None = None
    waza_b: int | None = None
    yuko_b: int | None = None
    penalty_b: int | None = None
    hsk_b: int | None = None


class JobRun(SQLModel, table=True):
    """One run of a job step: what ran, when, and how it ended.

    A run left `running` long after it started was killed (e.g. by a timeout).
    """

    __tablename__ = "job_run"
    __table_args__ = {"schema": SCHEMA}

    id: int | None = Field(default=None, primary_key=True)
    type: str  # sync, sync_full, rating
    status: str  # running, success, failed
    started_at: datetime = Field(sa_type=DateTime(timezone=True))
    finished_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    error: str | None = None  # traceback of a failed run


class RatingChange(SQLModel, table=True):
    """An athlete's rating before and after one contest: the whole rating history.

    The state on day D is the row with fought_on <= D < next_fought_on; RD then
    grows for the days since fought_on (see rating_settings).
    """

    __tablename__ = "rating_change"
    __table_args__ = (
        # The table of a weight category on a day.
        Index("ix_rating_change_weight_next_fought_on", "weight", "next_fought_on"),
        # An athlete's history.
        Index("ix_rating_change_athlete_id_fought_on", "athlete_id", "fought_on"),
        {"schema": SCHEMA},
    )

    # The sync deletes contests judobase dropped; their rows go with them until the
    # next rating run recomputes everything.
    contest_id: int = Field(foreign_key=fk("contest"), primary_key=True, ondelete="CASCADE")
    athlete_id: int = Field(foreign_key=fk("athlete"), primary_key=True)
    opponent_id: int = Field(foreign_key=fk("athlete"))
    fought_on: date
    # The day of the athlete's next contest; 9999-12-31 for the latest one.
    next_fought_on: date
    # The category the athlete is ranked in from this contest on (an open-weight
    # contest keeps the previous one; None until the athlete fights in a category).
    weight: str | None = None
    won: bool
    win_probability: float  # the athlete's chance before the contest
    rating_before: float
    rd_before: float  # already grown for the days without contests
    volatility_before: float
    rating_after: float
    rd_after: float
    volatility_after: float


class RatingSettings(SQLModel, table=True):
    """The parameters the rating was computed with (one row), for the site's SQL."""

    __tablename__ = "rating_settings"
    __table_args__ = {"schema": SCHEMA}

    id: int = Field(default=1, primary_key=True)
    initial_rating: float
    initial_rd: float
    max_rd: float
    rd_growth: float  # RD² grows by rd_growth² for every day without contests
    initial_volatility: float
    tau: float
    rd_factor: float  # leaderboard score = rating - rd_factor * RD
    hide_after_days: int | None  # not in the table after this many days without contests
