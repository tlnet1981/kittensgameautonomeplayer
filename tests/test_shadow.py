"""Tests der echten Schattenpreise (brain/shadow.py, Spec 10.2–10.4, 12.2)
und ihrer Integration in den taktischen Optimierer (tactics.py)."""

import math

import pytest

from player.brain import meta, safety, shadow, tactics
from player.brain.meta import Milestone
from tests.helpers import make_snap


def _generate(snap, target=None):
    sres = safety.check(snap)
    mview = meta.evaluate(snap)
    if target is not None:
        mview.active = Milestone("test", "Testziel", lambda s: False, target)
    cands, bn = tactics.generate(snap, mview, sres)
    return cands, bn


# ================================================================ λ (Menge)

def test_lambda_positive_for_bottleneck_zero_for_covered():
    """Engpassressource: λ ≈ 1/Rate; gedeckte Position: λ = 0;
    unbeteiligte Ressource taucht gar nicht auf."""
    snap = make_snap(resources={
        "wood": {"value": 5, "max": 200, "rate": 0.2},
        "science": {"value": 50, "max": 250, "rate": 0.1},
        "minerals": {"value": 0, "max": 250, "rate": 0},
    })
    lam = shadow.shadow_prices(snap, [{"name": "wood", "val": 25},
                                      {"name": "science", "val": 10}])
    # +1 Wood verkürzt die ETA um 1/0.2 = 5 s:
    assert lam["wood"] == pytest.approx(5.0, rel=0.01)
    assert lam["science"] == 0.0            # bereits gedeckt
    assert "minerals" not in lam            # nicht im Preisvektor, keine Kaskade


def test_lambda_clamped_for_zero_rate_and_zero_for_cap_block():
    snap = make_snap(resources={"wood": {"value": 0, "max": 200, "rate": 0}})
    # Rate 0 → endliches Clamp statt ∞:
    lam = shadow.shadow_prices(snap, [{"name": "wood", "val": 10}])
    assert lam["wood"] == shadow.LAMBDA_MAX
    # Cap blockiert das Ziel → λ = 0 (Storage ist der Fix, nicht mehr Einheiten):
    lam = shadow.shadow_prices(snap, [{"name": "wood", "val": 400}])
    assert lam["wood"] == 0.0


def test_lambda_cascade_dampens_via_craft_and_refine():
    """Craft-Kaskade: Inputs erben λ/Inputmenge; Refine (100 Catnip→1 Wood)
    ist die früheste Konversion."""
    crafts = [{"name": "manuscript", "label": "Manuscript", "unlocked": True,
               "prices": [{"name": "parchment", "val": 25},
                          {"name": "culture", "val": 400}]}]
    snap = make_snap(
        resources={"manuscript": {"value": 0, "max": 0, "rate": 0, "craftable": True},
                   "parchment": {"value": 0, "max": 0, "rate": 0},
                   "culture": {"value": 0, "max": 800, "rate": 0},
                   "wood": {"value": 0, "max": 200, "rate": 0},
                   "catnip": {"value": 0, "max": 5000, "rate": 0}},
        crafts=crafts,
    )
    lam = shadow.shadow_prices(snap, [{"name": "manuscript", "val": 5}])
    assert lam["manuscript"] == shadow.LAMBDA_MAX
    assert lam["parchment"] == pytest.approx(shadow.LAMBDA_MAX / 25)
    assert lam["culture"] == pytest.approx(shadow.LAMBDA_MAX / 400)

    lam = shadow.shadow_prices(snap, [{"name": "wood", "val": 10}])
    assert lam["catnip"] == pytest.approx(lam["wood"] / 100)


def test_empty_goal_prices_yield_empty_lambda():
    snap = make_snap()
    assert shadow.shadow_prices(snap, None) == {}
    assert shadow.shadow_prices(snap, []) == {}
    assert shadow.rate_shadow_prices(snap, None) == {}


# ================================================================ λ (Rate)

def test_rate_shadow_price_matches_analytic_derivative():
    """λ_rate ≈ fehlend/Rate² für den Engpass; gedeckte Position: 0."""
    snap = make_snap(resources={"wood": {"value": 5, "max": 200, "rate": 0.2},
                                "science": {"value": 50, "max": 250, "rate": 0.1}})
    goal = [{"name": "wood", "val": 25}, {"name": "science", "val": 10}]
    v = shadow.shadow_price_of_rate(snap, goal, "wood")
    assert abs(v - 20 / 0.2 ** 2) < 10      # ≈ 500 (numerisch leicht gedämpft)
    assert shadow.shadow_price_of_rate(snap, goal, "science") == 0.0
    # Rate 0 → Clamp:
    snap = make_snap(resources={"wood": {"value": 5, "max": 200, "rate": 0}})
    assert shadow.shadow_price_of_rate(snap, [{"name": "wood", "val": 25}],
                                       "wood") == shadow.LAMBDA_RATE_MAX


# ================================================================ Zeitwerte

def test_cost_benefit_net_value_and_payback():
    lam = {"wood": 2.0}
    assert shadow.cost_time([{"name": "wood", "val": 50}], lam) == 100.0
    assert shadow.benefit_time({"wood": 0.5}, lam, horizon=600) == 600.0
    assert shadow.benefit_time({"wood": 0.5}, lam, horizon=600,
                               unlock_bonus=30) == 630.0
    assert shadow.net_value(630.0, 100.0) == 530.0
    assert shadow.payback(120.0, 2.0) == 60.0
    assert shadow.payback(120.0, 0.0) == math.inf
    assert shadow.payback(0.0, 0.0) == 0.0   # nichts gekostet → sofort amortisiert


def test_run_horizon_is_clamped_and_grows_with_run_age():
    snap = make_snap()
    snap["calendar"].update({"year": 0, "season": 0, "day": 0})
    assert shadow.run_horizon(snap) == shadow.HORIZON_MIN
    snap["calendar"].update({"year": 20})
    assert shadow.run_horizon(snap) == shadow.HORIZON_MAX
    # Mittlerer Fall oberhalb der 30-min-Untergrenze (Jahr 2 ≈ 1600 s
    # Spielzeit → Horizont 3200 s):
    snap["calendar"].update({"year": 2, "season": 0, "day": 0})
    h = shadow.run_horizon(snap)
    assert shadow.HORIZON_MIN < h < shadow.HORIZON_MAX


# ================================================================ Jobs

def test_job_score_prefers_bottleneck_producing_job():
    snap = make_snap(jobs={"woodcutter": 0, "farmer": 0})
    lam_rate = {"wood": 100.0}
    assert shadow.job_score(snap, "woodcutter", lam_rate) > 0
    assert shadow.job_score(snap, "farmer", lam_rate) == 0.0
    assert shadow.job_score(snap, "woodcutter", {}) == 0.0   # keine λ-Daten


def test_free_kitten_goes_to_highest_job_score():
    """Ziel braucht Science → Scholar gewinnt gegen Woodcutter, obwohl
    beides freigeschaltet ist (JobScore statt festem Mapping)."""
    snap = make_snap(
        resources={"catnip": {"value": 5000, "max": 10000, "rate": 20},
                   "science": {"value": 0, "max": 250, "rate": 0.05},
                   "wood": {"value": 100, "max": 200, "rate": 0.3}},
        buildings={"field": {"val": 5, "prices": {"catnip": 100}}},
        techs={"calendar": {"researched": False, "prices": {"science": 30}}},
        jobs={"woodcutter": 1, "scholar": 0}, free_kittens=1,
        kittens=2, max_kittens=2, catnip_field_base=20,
    )
    cands, bn = _generate(snap, {"kind": "research", "name": "calendar"})
    job = next(c for c in cands if c.action.exec_spec.get("kind") == "assign_job")
    assert job.action.exec_spec["job"] == "scholar"
    # Seit der Soll-Allokation (12.2) kann die Wahl über das
    # Allokations-Defizit statt über den Einzel-JobScore laufen:
    assert (job.components.get("jobScore", 0) > 0
            or "allocDeficit" in job.components)


def test_job_fallback_without_lambda_data():
    """Ziel ohne Preisvektor (Gebäude fehlt im Snapshot) → λ leer →
    Balance-Fallback: dünnster Basisjob, kein Crash."""
    snap = make_snap(
        resources={"catnip": {"value": 5000, "max": 10000, "rate": 20}},
        jobs={"woodcutter": 1, "farmer": 0}, free_kittens=1,
        kittens=2, max_kittens=2, catnip_field_base=20,
    )
    cands, _ = _generate(snap, {"kind": "build", "name": "library"})
    job = next(c for c in cands if c.action.exec_spec.get("kind") == "assign_job")
    assert job.action.exec_spec["job"] == "farmer"     # min. Besetzung
    assert "jobScore" not in job.components


def test_rebalance_gate_requires_job_score_gain():
    """Umschulung nur, wenn JobScore(Ziel) − JobScore(Spender) die
    Schwelle übersteigt — hier klar erfüllt (Science-Rate = 0)."""
    snap = make_snap(
        resources={"catnip": {"value": 3000, "max": 5000, "rate": 10},
                   "wood": {"value": 100, "max": 200, "rate": 0.4},
                   "science": {"value": 0, "max": 250, "rate": 0}},
        buildings={"field": {"val": 20, "prices": {"catnip": 100}},
                   "library": {"val": 1, "prices": {"wood": 40}}},
        techs={"calendar": {"researched": False, "prices": {"science": 30}}},
        jobs={"woodcutter": 2, "scholar": 0}, kittens=2, max_kittens=2,
        catnip_field_base=12,
    )
    cands, bn = _generate(snap, {"kind": "research", "name": "calendar"})
    shift = next(c for c in cands if c.action.id.startswith("shift:"))
    assert shift.action.exec_spec["to"] == "scholar"
    assert (shift.components.get("jobScore", 0) > tactics.REBALANCE_GAIN_MIN
            or "allocDeficit" in shift.components)


# ================================================================ Payback-Gate

def _payback_snap():
    """Ziel Hütte (400 Wood, Rate 0,5): λ_wood = 2 s/Einheit.
    - mine (Produktionsgebäude, Minerals ohne λ, kostet 50 Wood):
      Cost_time 100 s, Benefit 0 → Payback ∞ > Horizont → abgelehnt.
    - workshop (Unlock): kostet ebenfalls Wood, bleibt aber zulässig (10.4).
    - lumberMill (produziert den Engpass Wood): zwingende Dependency."""
    return make_snap(
        resources={"catnip": {"value": 40000, "max": 50000, "rate": 40},
                   "wood": {"value": 200, "max": 1000, "rate": 0.5},
                   "minerals": {"value": 100, "max": 500, "rate": 0}},
        buildings={"hut": {"val": 2, "prices": {"wood": 400}},
                   "mine": {"val": 0, "prices": {"wood": 50}},
                   "workshop": {"val": 0, "prices": {"wood": 50}},
                   "lumberMill": {"val": 0, "prices": {"minerals": 50}}},
        jobs={"woodcutter": 2}, kittens=2, max_kittens=2,
        catnip_field_base=40,
    )


def test_payback_gate_rejects_unprofitable_production_building():
    cands, bn = _generate(_payback_snap(), {"kind": "build", "name": "hut"})
    assert bn["resource"] == "wood"
    mine = next(c for c in cands if c.action.id == "build:mine")
    assert not mine.feasible
    assert "Payback" in mine.reject_reason
    assert mine.components.get("costTime", 0) > 0


def test_payback_gate_spares_unlocks_and_bottleneck_solvers():
    cands, _ = _generate(_payback_snap(), {"kind": "build", "name": "hut"})
    workshop = next(c for c in cands if c.action.id == "build:workshop")
    assert workshop.feasible                      # Unlock-first (10.4)
    assert workshop.components.get("unlock", 0) > 0
    mill = next(c for c in cands if c.action.id == "build:lumberMill")
    assert mill.feasible                          # löst den Engpass
    assert mill.components.get("netValue", 0) > 0
    assert mill.score > 0


def test_building_fallback_without_lambda_keeps_fixed_score():
    """Ohne λ-Daten (Ziel bezahlbar → alle λ = 0) behalten Ökonomie-
    Gebäude den festen Score — kein Payback-Gate, keine Sekundenwerte."""
    snap = _payback_snap()
    snap["resources"][1]["value"] = 900           # wood: Ziel sofort bezahlbar
    from player.state.derived import derive
    derive(snap)
    cands, _ = _generate(snap, {"kind": "build", "name": "hut"})
    mine = next(c for c in cands if c.action.id == "build:mine")
    assert mine.feasible
    assert mine.components.get("economy") == 0.6
    assert "netValue" not in mine.components
