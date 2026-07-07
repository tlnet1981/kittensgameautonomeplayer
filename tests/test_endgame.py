"""Tests für player/brain/endgame.py (Spec 1.3/6.3): C(S)-Berechnung,
frontier_complete-Proxy, ΔlnC/Δt-Score und die 6.2→6.3-Umschaltung des
Meta-Controllers."""

import pytest

from player.brain import endgame, meta
from tests.helpers import make_snap


# ---------------------------------------------------------------- Fixtures

def _all_perks_researched():
    return [{"name": n, "label": n, "researched": True, "unlocked": True,
             "prices": [{"name": "paragon", "val": 1}]}
            for n in meta.METAPHYSICS_ORDER]


def frontier_snap():
    """Snapshot mit erfüllter Front: Metaphysics + Challenges + Religion +
    Relic Station (AM-Cap 5000) + Resource Retrieval ≥ 1."""
    snap = make_snap(
        resources={"catnip": {"value": 1000, "max": 50000, "rate": 5.0},
                   "antimatter": {"value": 100, "max": 5000, "rate": 0.1},
                   "timeCrystal": {"value": 30, "max": 0, "rate": 0.5},
                   "relic": {"value": 10, "max": 0, "rate": 0.2}},
        kittens=100,
        challenges=[{"name": "winterIsComing", "researched": True, "on": 1},
                    {"name": "anarchy", "researched": True, "on": 1}],
        religion={"worship": 5000.0, "transcendenceTier": 5,
                  "upgrades": [{"name": "solarRevolution", "label": "Solar Revolution",
                                "unlocked": True, "on": 1, "val": 1,
                                "noStackable": True, "prices": []}],
                  "ziggurat": []},
    )
    snap["prestige"] = {"paragon": 500, "burnedParagon": 100, "karma": 10,
                        "perks": _all_perks_researched()}
    snap["workshop"]["upgrades"] = [{"name": "relicStation", "label": "Relic Station",
                                     "researched": True, "unlocked": True,
                                     "prices": []}]
    snap["time"] = {"heat": 0, "heatMax": 100, "voidspace": [],
                    "chronoforge": [{"name": "ressourceRetrieval",
                                     "label": "Resource Retrieval", "val": 1,
                                     "unlocked": True,
                                     "prices": [{"name": "timeCrystal", "val": 1000}]}]}
    return snap


# ---------------------------------------------------------------- C(S)

def test_capability_index_all_dimensions_missing_is_epsilon():
    # Leerer Snapshot: keine Dimension beobachtbar → jeder Faktor ε →
    # geometrisches Mittel = ε (ehrlich, kein geratener Wert).
    snap = make_snap()
    rates = endgame.dimension_rates(snap)
    assert all(rates[d] is None for d in endgame.DIMENSIONS)
    assert endgame.capability_index(snap) == pytest.approx(endgame.EPS_DIM)


def test_capability_index_is_geometric_mean():
    # Zwei Dimensionen exakt auf Referenzrate (Faktor 1), fünf fehlen (ε):
    # C = (1 · 1 · ε^5)^(1/7) = ε^(5/7).
    rates = {d: None for d in endgame.DIMENSIONS}
    rates["paragon"] = endgame.REFERENCE_RATES["paragon"]
    rates["timeCrystal"] = endgame.REFERENCE_RATES["timeCrystal"]
    c = endgame.capability_index(make_snap(), rates=rates)
    assert c == pytest.approx(endgame.EPS_DIM ** (5.0 / 7.0))


def test_capability_index_reference_rates_only_scale():
    # b_i sind reine Normierung: proportionale Zustände behalten die
    # Rangfolge (Spec 1.3) — doppelte Raten ⇒ größerer Index.
    lo = {d: endgame.REFERENCE_RATES[d] for d in endgame.DIMENSIONS}
    hi = {d: 2 * endgame.REFERENCE_RATES[d] for d in endgame.DIMENSIONS}
    snap = make_snap()
    assert endgame.capability_index(snap, rates=hi) \
        > endgame.capability_index(snap, rates=lo)
    assert endgame.capability_index(snap, rates=lo) == pytest.approx(1.0)


def test_dimension_rates_observed_only():
    # Nur beobachtete Raten zählen; Relic-Rate vorhanden, Rest fehlt.
    snap = make_snap(resources={"relic": {"value": 5, "max": 0, "rate": 0.2}})
    rates = endgame.dimension_rates(snap)
    assert rates["relic"] == pytest.approx(0.2)
    assert rates["antimatter"] is None
    assert rates["void"] is None
    # Paragon-Rate erst ab Kitten > 70 (Reset-Paragon-Formel Anhang D):
    snap2 = make_snap(kittens=100)
    assert endgame.dimension_rates(snap2)["paragon"] is not None
    assert endgame.dimension_rates(snap2)["paragon"] > 0


# ---------------------------------------------------------------- Front

def test_frontier_complete_conservative_false_without_data():
    assert endgame.frontier_complete(make_snap()) is False


def test_frontier_complete_requires_every_pillar():
    snap = frontier_snap()
    assert endgame.frontier_complete(snap) is True
    # Ein offener Perk kippt die Front:
    s2 = frontier_snap()
    s2["prestige"]["perks"][0]["researched"] = False
    assert endgame.frontier_complete(s2) is False
    # Eine offene Challenge kippt die Front:
    s3 = frontier_snap()
    s3["challenges"]["list"][0]["researched"] = False
    assert endgame.frontier_complete(s3) is False
    # AM-Cap unter 5000 (space.js:718-720) kippt die Front:
    s4 = frontier_snap()
    next(r for r in s4["resources"] if r["name"] == "antimatter")["maxValue"] = 500
    assert endgame.frontier_complete(s4) is False
    # Ohne Resource Retrieval keine operationale Shatter-Engine:
    s5 = frontier_snap()
    s5["time"]["chronoforge"] = []
    assert endgame.frontier_complete(s5) is False


# ---------------------------------------------------------------- Score (6.3)

def test_endgame_score_zero_without_projection_data():
    assert endgame.endgame_score(make_snap(), 600.0) == 0.0


def test_endgame_score_positive_when_paragon_rate_grows():
    snap = make_snap(kittens=100, max_kittens=200)
    snap["village"]["kittensPerSec"] = 0.05   # Ankünfte heben die Paragonrate
    assert endgame.endgame_score(snap, 600.0) > 0
    # Ohne Ankünfte fällt die Rate (gleicher Paragon über mehr Run-Zeit):
    snap2 = make_snap(kittens=100, max_kittens=200)
    assert endgame.endgame_score(snap2, 600.0) < 0


# ---------------------------------------------------------------- 6.2 → 6.3

def test_meta_switches_to_endgame_score_after_frontier():
    snap = frontier_snap()
    rt, variant, detail = meta.determine_run_plan(snap)
    assert detail["scoreMode"] == "6.3"
    # Nach F ist MATURE_ENDGAME_RUN der kanonische Träger der 6.3-Ziel-
    # funktion (Spec 8.2) und gewinnt Gleichstände deterministisch:
    assert rt == "MATURE_ENDGAME_RUN"
    assert variant is not None
    # Alle Zeilen tragen den ΔlnC/Δt-Score, keine Restzeit-Metrik:
    assert all(r["scoreMode"] == "6.3" and r["restzeit"] is None
               for r in detail["scores"])


def test_meta_stays_on_62_before_frontier():
    snap = make_snap(
        resources={"catnip": {"value": 100, "max": 5000, "rate": 2.0}}, kittens=10)
    snap["prestige"] = {"paragon": 0, "burnedParagon": 0, "karma": 0, "perks": []}
    _, _, detail = meta.determine_run_plan(snap)
    assert detail["scoreMode"] == "6.2"
    assert "MATURE_ENDGAME_RUN" not in {r["runType"] for r in detail["scores"]}


def test_mature_endgame_run_admissible_only_after_frontier():
    assert "MATURE_ENDGAME_RUN" not in meta._admissible_run_types(make_snap())
    assert "MATURE_ENDGAME_RUN" in meta._admissible_run_types(frontier_snap())
