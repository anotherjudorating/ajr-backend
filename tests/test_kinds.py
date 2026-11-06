"""ajr.sync.kinds: what kind of event a competition is (real judobase names and codes)."""

from types import SimpleNamespace

import pytest

from ajr.sync.kinds import kind


def event(name, code, is_teams=False, ages=("sen",), status=None, rank_name=None):
    return SimpleNamespace(
        name=name, competition_code=code, is_teams=is_teams, ages=list(ages), status=status,
        rank_name=rank_name,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("competition", "expected"),
    [
        (event("Paris Grand Slam 2024", "gs_fra2024"), "individual"),
        (event("Rome European Open 2027", "cont_open_ita2027"), "individual"),
        (event("20th Asian Games Aichi-Nagoya", "jua_games2026"), "individual"),
        (event("Asian Senior Championships 2022 (Individuals and Teams)", "x"), "individual"),
        (event("Asian-Pacific Championships  Seniors and Teams 2019", "x"), "individual"),
        (event("Paralympic Games Tokyo 2020", "pg_tokyo2020"), "para"),
        (event("IBSA Judo World Cup Tbilisi 2025", "wcup_ibsa_geo2025"), "para"),
        (
            event("Ecole Mont-Olivet Deaf Judo Masters Top 18 Lausanne 2026", "gs_deaf_sui2026"),
            "para",
        ),
        (event("Test Event - Olympic Games - Paris 2024", "oi_test2023", status="-1"), "camp"),
        (event("Belgrade EJU OTC Training Camp 2026", "eju_otc_srb2026", status="-1"), "camp"),
        (
            event("Porec EJU Cadet Training Camp 2024", "eju_cad_tc_cro2024", ages=["cad"]),
            "age_group",
        ),
        (
            event("Veterans African Championships 2026", "aju_vet2026", ages=["f1", "m1"]),
            "age_group",
        ),
        (event("World Judo Championships Juniors 2025", "wc_jun2025", ages=["jun"]), "age_group"),
        (event("Mixed Teams 2027", "eju_sen_teams2027", is_teams=True), "team"),
        (event("European Senior Championships Mixed Teams 2026", "eju_sen2026_mt"), "team"),
        (event("Arab Games Teams 2023", "arab_games2023"), "team"),
        (event("Laval Kata World Series 2027", "kata_can2027", ages=["cad", "jun", "sen"]), "kata"),
        (event("World Military Championships 2024", "mil_uzb2024"), "military"),
        (event("Something new 2027", "new_2027", ages=[""]), "individual"),  # [''] is unknown
    ],
)
def test_kind(competition, expected):
    assert kind(competition) == expected
