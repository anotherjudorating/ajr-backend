"""What kind of event a judobase competition is, for what the rating counts.

judobase's rank_name is a points category, not a kind: an IBSA Grand Prix sits under
"Grand Prix", a training camp under "Continental Cup", a test event under "Olympic
Games". So the kind comes from its flags, age groups, status, code and name, the
first that matches (docs/audits/2026-11-06-tournaments.md, checked on the 1,986
competitions judobase lists). Only "individual" events are rated; a kind not
foreseen falls to "individual", the rating's guards on contests catch the rest.
"""

import re

import judobase

INDIVIDUAL = "individual"

CODE_TEAM = re.compile(r"(^|_)teams?(_|[0-9]|$)|(^|_)(cl|el|ecc)(_|[0-9]|$)")
NAME_TEAM = re.compile(
    r"mixed teams?|club championships|champions league|europa league|golden league|-\s*teams\s*$",
    re.IGNORECASE,
)
CODE_AGE = re.compile(r"(^|_)(jun|cad|vet|u23|u21|u18|eyof|youth)(_|[0-9])")
NAME_AGE = re.compile(r"\b(junior|cadet|veteran|u23|u21|u18|youth|eyof)s?\b", re.IGNORECASE)
CODE_KATA = re.compile(r"kata|(^|_)nw_")
NAME_KATA = re.compile(r"kata|ne-?waza", re.IGNORECASE)
CODE_PARA = re.compile(r"ibsa|^pg_|^para|deaf|adapted")
NAME_PARA = re.compile(r"\bibsa\b|paralympic|\bdeaf\b|adapted|blind", re.IGNORECASE)
CODE_CAMP = re.compile(
    r"(^|_)(otc|itc|tc|tcw\d?)(_|[0-9])|seminar|refsem|ref_|examination|congress|(^|_)test|kids|children"
)
NAME_CAMP = re.compile(
    r"training camp|\botc\b|\bitc\b|seminar|examination|congress|test event|kids|children",
    re.IGNORECASE,
)
CODE_MILITARY = re.compile(r"(^|_)mil(_|[0-9])")


def kind(item: judobase.Competition) -> str:
    """team, age_group, kata, para, camp, military or individual."""
    code = (item.competition_code or "").lower()
    name = item.name or ""
    ages = [age for age in (item.ages or []) if age]  # judobase sometimes gives ['']
    if item.is_teams or team_by_name(name):
        return "team"
    if ages and "sen" not in ages:
        return "age_group"
    if str(item.status or "") == "-1":  # cancelled, a test event, a camp
        return "camp"
    for event_kind, code_pattern, name_pattern in PATTERNS:
        if code_pattern.search(code) or name_pattern.search(name):
            return event_kind
    if item.rank_name == "Military World Championships":
        return "military"
    return INDIVIDUAL


def team_by_name(name: str) -> bool:
    """ "Arab Games Teams 2023", "... - TEAMS"; not "... Seniors and Teams 2019" or
    "(Individuals and Teams)", events of both."""
    text = name.lower()
    return "team" in text and "individual" not in text and "and team" not in text


# The first that matches; a team event first (its code may say juniors too).
PATTERNS = [
    ("team", CODE_TEAM, NAME_TEAM),
    ("kata", CODE_KATA, NAME_KATA),
    ("para", CODE_PARA, NAME_PARA),
    ("camp", CODE_CAMP, NAME_CAMP),
    ("age_group", CODE_AGE, NAME_AGE),
    ("military", CODE_MILITARY, re.compile(r"military", re.IGNORECASE)),
]
