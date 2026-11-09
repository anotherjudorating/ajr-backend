"""Database tables, all in the `ajr` schema (not exposed by the Supabase Data API).

Ids of countries, athletes, competitions and contests are judobase ids.
"""

from datetime import date, datetime

from sqlalchemy import ARRAY, DateTime, ForeignKeyConstraint, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
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


class AthleteAlias(SQLModel, table=True):
    """A second judobase id of an athlete (judobase opens a new profile when an athlete
    changes nations, and sometimes enters one twice at a tournament): the sync writes
    the main id in its contests instead, so the athlete has one rating history. Loaded
    from ajr/sync/data/athlete_aliases.csv by the sync."""

    __tablename__ = "athlete_alias"
    __table_args__ = {"schema": SCHEMA}

    alias_id: int = Field(foreign_key=fk("athlete"), primary_key=True)
    athlete_id: int = Field(foreign_key=fk("athlete"))  # the id fought under last


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
    ages: list[str] | None = Field(default=None, sa_type=ARRAY(Text))  # judobase's, e.g. ["sen"]
    status: str | None = None  # judobase's; "-1": cancelled, a test event, a camp
    # individual, team, age_group, kata, para, camp or military (ajr/sync/kinds.py)
    kind: str = Field(default="individual", sa_type=Text)
    country_id: int | None = Field(default=None, foreign_key=fk("country"))
    # judobase `updated_at_ts`, and its value when the contests were last synced.
    updated_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    contests_synced_for: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    # When the sync last saw a result of this competition appear, change or vanish;
    # the rating is recomputed from the first such competition (see ajr/rating/job.py).
    results_changed_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True), index=True
    )


class ContestWalkover(SQLModel, table=True):
    """A decided contest that was a walkover, not a fight (ajr/sync/walkovers.py):
    reason "fusen" (judobase's Fusen-Gachi tag) or "likely" (nothing was fought)."""

    __tablename__ = "contest_walkover"
    __table_args__ = {"schema": SCHEMA}

    contest_id: int = Field(foreign_key=fk("contest"), primary_key=True, ondelete="CASCADE")
    reason: str = Field(sa_type=Text)


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
    __table_args__ = (
        # api.last_update: the latest successful rating run.
        Index(
            "ix_job_run_last_rating",
            text("finished_at desc"),
            postgresql_where=text("type = 'rating' and status = 'success'"),
        ),
        {"schema": SCHEMA},
    )

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
        # The same, for a day in the past: the contests of the year before it, with
        # what ajr.board_at reads, so that it does not read the table.
        Index(
            "ix_rating_change_weight_fought_on_board",
            "weight",
            "fought_on",
            postgresql_include=[
                "next_fought_on",
                "athlete_id",
                "rating_after",
                "rd_after",
                "listed_here",
            ],  # fmt: skip
        ),
        # An athlete's history.
        Index("ix_rating_change_athlete_id_fought_on", "athlete_id", "fought_on"),
        {"schema": SCHEMA},
    )

    # The sync deletes contests judobase dropped; their rows go with them until the
    # next rating run recomputes everything.
    contest_id: int = Field(foreign_key=fk("contest"), primary_key=True, ondelete="CASCADE")
    athlete_id: int = Field(foreign_key=fk("athlete"), primary_key=True)
    seq: int  # the contest's place in rating order (both rows of a contest share it)
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
    # Whether the table of `weight` lists the athlete from this contest on (see
    # ajr/rating/ranking.py); the other tables listing them are in rating_listing.
    listed_here: bool = True
    # What the athlete's history shows beside the row, written by the rating job
    # (ajr/rating/snapshot.py, HISTORY_FACTS) so the page reads this table alone: the
    # contest's tournament, round (judobase counts down to the final, 0), number and
    # round name, the opponent's rating before it (their row of the contest), their
    # name and nation as they are now, and how the athlete ended the tournament.
    competition_id: int | None = None
    round: int | None = None
    fight_no: int | None = None
    round_name: str | None = None
    opponent_rating_before: float | None = None
    opponent_rd_before: float | None = None
    opponent_family_name: str | None = None
    opponent_given_name: str | None = None
    opponent_country: str | None = None  # IOC
    result: str | None = None  # ajr.athlete_competition's, for the contest's weight


class RatingListing(SQLModel, table=True):
    """Another weight whose table lists the athlete from a contest on, besides the
    contest's own category (an athlete fighting in two weights)."""

    __tablename__ = "rating_listing"
    __table_args__ = (
        Index(
            "ix_rating_listing_weight_fought_on",
            "weight",
            "fought_on",
            postgresql_include=["next_fought_on", "athlete_id", "rating_after", "rd_after"],
        ),
        ForeignKeyConstraint(
            ["contest_id", "athlete_id"],
            [f"{SCHEMA}.rating_change.contest_id", f"{SCHEMA}.rating_change.athlete_id"],
            ondelete="CASCADE",
        ),
        {"schema": SCHEMA},
    )

    contest_id: int = Field(primary_key=True)
    athlete_id: int = Field(primary_key=True)
    weight: str = Field(primary_key=True)
    # as the rating_change row's (copied, so that a table is read from the index)
    fought_on: date
    next_fought_on: date
    rating_after: float
    rd_after: float


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
    move_handicap: float  # on a change of weight category: share of the rating
    real_fights_only: bool  # only real fights rated (ajr/rating/engine.py)
    rd_factor: float  # leaderboard score = rating - rd_factor * RD
    hide_after_days: int | None  # not in the table after this many days without contests
    min_tournaments: int  # in a weight within listing_days, to stand in its table
    listing_days: int


class WrlRanking(SQLModel, table=True):
    """The current IJF World Ranking List of seniors, shown next to our places.

    Only athletes we have; replaced as a whole when judobase's list changes (weekly).
    An athlete can be ranked in two weight categories.
    """

    __tablename__ = "wrl_ranking"
    __table_args__ = {"schema": SCHEMA}

    athlete_id: int = Field(foreign_key=fk("athlete"), primary_key=True)
    weight: str = Field(primary_key=True)
    place: int


class Record(SQLModel, table=True):
    """All-time bests for the records page, recomputed as a whole by `python -m ajr.records`.

    One row per place of a record; which ids are set depends on the record (an
    athlete, a pair of athletes, a nation, a competition).
    """

    __table_args__ = (Index("ix_record_record_place", "record", "place"), {"schema": SCHEMA})

    id: int | None = Field(default=None, primary_key=True)
    record: str  # e.g. highest_rating (see ajr/records/job.py)
    place: int  # ties share a place
    athlete_id: int | None = Field(default=None, foreign_key=fk("athlete"))
    opponent_id: int | None = Field(default=None, foreign_key=fk("athlete"))
    country_id: int | None = Field(default=None, foreign_key=fk("country"))
    competition_id: int | None = Field(default=None, foreign_key=fk("competition"))
    weight: str | None = None
    value: float  # what the record is about: a score, weeks, a count, an age
    detail: dict | None = Field(default=None, sa_type=JSONB)  # e.g. gold/silver/bronze
    day: date | None = None  # when it happened
    # The names shown with the row, written by the records job (see NAMES there).
    family_name: str | None = Field(default=None, sa_type=Text)
    given_name: str | None = Field(default=None, sa_type=Text)
    gender: str | None = Field(default=None, sa_type=Text)
    opponent_family_name: str | None = Field(default=None, sa_type=Text)
    opponent_given_name: str | None = Field(default=None, sa_type=Text)
    country: str | None = Field(default=None, sa_type=Text)  # the nation's code
    country_name: str | None = Field(default=None, sa_type=Text)
    competition: str | None = Field(default=None, sa_type=Text)


class LeaderboardSnapshot(SQLModel, table=True):
    """Today's table of every weight, as api.leaderboard serves it, rebuilt by the
    rating job (see ajr/rating/snapshot.py)."""

    __tablename__ = "leaderboard_snapshot"
    __table_args__ = (
        # The top places of every weight (the home page).
        Index("ix_leaderboard_snapshot_place", "place"),
        # A nation's best athletes (the country page).
        # A nation's best athlete in each weight (api.country_leaders), from the index alone.
        Index(
            "ix_leaderboard_snapshot_country_leaders",
            "country",
            "weight",
            text("score desc"),
            "place",
            postgresql_include=["athlete_id", "family_name", "given_name"],
        ),
        {"schema": SCHEMA},
    )

    weight: str = Field(primary_key=True)
    day: date
    place: int
    athlete_id: int = Field(foreign_key=fk("athlete"), primary_key=True)
    family_name: str | None = None
    given_name: str | None = None
    country: str | None = None
    rating: int | None = None
    rd: int | None = None
    score: int | None = None
    last_contest: date | None = None
    places_up_90d: int | None = None
    score_change_90d: int | None = None
    score_change_6m: int | None = None
    wrl_place: int | None = None
    places_up_6m: int | None = None
    birth_year: int | None = None
    trend: list[int | None] | None = Field(default=None, sa_type=ARRAY(Integer))
    last_competition_id: int | None = None
    last_competition_name: str | None = None
    last_competition_rank: str | None = None
    last_competition_city: str | None = None
    entry: str | None = None


class MatchupViews(SQLModel, table=True):
    """How many times the site showed a head-to-head pair (a < b): orders the popular
    matchups once there are enough (see the "popular matchups" migration)."""

    __tablename__ = "matchup_views"
    __table_args__ = {"schema": SCHEMA}

    a: int = Field(foreign_key=fk("athlete"), primary_key=True)
    b: int = Field(foreign_key=fk("athlete"), primary_key=True)
    views: int = 0


class CompetitionStats(SQLModel, table=True):
    """Per tournament, for the Explore lists; rebuilt by the rating job."""

    __tablename__ = "competition_stats"
    __table_args__ = {"schema": SCHEMA}

    competition_id: int = Field(foreign_key=fk("competition"), primary_key=True)
    contests: int  # real fights: no byes, no 0:00 walkovers
    accuracy: float | None = None  # share of them the favourite won
    upsets: int  # won with a chance of 35% or less
    # the tournament as the run saw it, so the tournaments list reads this table alone
    name: str | None = None
    rank_name: str | None = None
    city: str | None = None
    country: str | None = None  # IOC
    country_name: str | None = None
    date_from: date | None = None
    date_to: date | None = None


class AthleteSummary(SQLModel, table=True):
    """Per rated athlete, for the Explore lists; rebuilt by the rating job."""

    __tablename__ = "athlete_summary"
    # A nation's athletes (the country page).
    __table_args__ = (
        Index("ix_athlete_summary_country", "country"),
        # api.sitemap reads the athletes from the index alone.
        Index(
            "ix_athlete_summary_sitemap",
            "athlete_id",
            postgresql_include=["last_contest", "contests"],
        ),
        {"schema": SCHEMA},
    )

    athlete_id: int = Field(foreign_key=fk("athlete"), primary_key=True)
    weight: str | None = None
    last_contest: date
    last_competition_id: int | None = Field(default=None, foreign_key=fk("competition"))
    contests: int
    place: int | None = None  # today, in the weight's table
    score: int | None = None
    # the athlete's, kept here so the Explore list reads one table
    family_name: str | None = None
    given_name: str | None = None
    gender: str | None = None
    country: str | None = None  # IOC
    birth_year: int | None = None
    last_competition: str | None = None
    # for the athlete's page (api.athlete)
    weights: list[str] | None = Field(default=None, sa_type=ARRAY(Text))  # the latest first
    peak_score: int | None = None  # the best score at the end of a day of contests
    peak_on: date | None = None
    peak_weight: str | None = None
    # what api.athlete shows, on the day of the run (ajr/rating/snapshot.py)
    rating: int | None = None  # RD grown for the days without contests
    rd: int | None = None
    score_today: int | None = None  # `score` is the table's, None when hidden
    score_change_90d: int | None = None
    score_change_6m: int | None = None
    places_up_90d: int | None = None  # in today's table (None outside it)
    places_up_6m: int | None = None
    peak_place: int | None = None  # in the table of peak_weight on peak_on
    wrl_place: int | None = None


class NationSummary(SQLModel, table=True):
    """Every nation with a rated athlete, for the Explore list and the country page's
    switcher (api.nations); rebuilt by the rating job."""

    __tablename__ = "nation_summary"
    __table_args__ = {"schema": SCHEMA}

    country_id: int = Field(foreign_key=fk("country"), primary_key=True)
    country: str  # IOC
    name: str | None = None
    athletes: int
    active: int  # in a weight's table today
    # the country page's numbers (api.country): places in today's nations tables
    # (mixed, men, women) and the mixed rating, 90 days and 6 months ago, and the best
    # score and the average of the best 8 today
    place: int | None = None
    place_men: int | None = None
    place_women: int | None = None
    rating: int | None = None
    place_90d: int | None = None
    rating_90d: int | None = None
    place_6m: int | None = None
    rating_6m: int | None = None
    top1: int | None = None
    top8: int | None = None
