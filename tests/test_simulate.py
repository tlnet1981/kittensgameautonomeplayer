"""Tests der EV-Projektion (simulate), Run-Plan-Wahl (Spec 8.3) und CS-Suche (19.1)."""

import math

import pytest

from player.brain import chrono, meta, safety, simulate, tactics
from tests.helpers import make_snap


def _with_prestige(snap, paragon=0, karma=0, perks=None):
    snap["prestige"] = {"paragon": paragon, "burnedParagon": 0, "karma": karma,
                        "perks": perks or []}
    return snap


# ================================================================ Projektion

def test_projection_clamps_at_cap():
    snap = make_snap(resources={"wood": {"value": 90, "max": 100, "rate": 1.0}})
    proj = simulate.project(snap, 600)
    assert proj.final["wood"] == pytest.approx(100)   # Cap-Klemme, nicht 690


def test_projection_respects_season_modifiers():
    # Feld-Basisrate 10/s, Frühling (Mod 1.5) → net 15/s; ab Sommer (Mod 1.0)
    # sinkt die Rate auf 10/s. Rest-Frühling = 90 Tage = 180 s.
    snap = make_snap(resources={"catnip": {"value": 0, "max": 0, "rate": 15.0}},
                     season="spring", catnip_field_base=10)
    proj = simulate.project(snap, 380)
    assert proj.final["catnip"] == pytest.approx(15 * 180 + 10 * 200)


def test_eta_of_finds_affordability_time():
    snap = make_snap(resources={"science": {"value": 0, "max": 0, "rate": 2.0}})
    proj = simulate.project(snap, 600)
    assert proj.eta_of([{"name": "science", "val": 100}]) == pytest.approx(50)
    assert math.isinf(proj.eta_of([{"name": "science", "val": 10_000}]))
    # nicht projizierte Ressourcen zählen konstant → nie bezahlbar:
    assert math.isinf(proj.eta_of([{"name": "titanium", "val": 5}]))


def test_invest_policy_tradeoff_short_vs_long():
    snap = make_snap(resources={"science": {"value": 0, "max": 0, "rate": 1.0}})
    a_short = simulate.project(snap, 600, policy={"invest": 0.15}).final["science"]
    c_short = simulate.project(snap, 600, policy={"invest": 0.60}).final["science"]
    assert a_short > c_short          # kurzer Horizont: Minimalpfad sammelt mehr
    a_long = simulate.project(snap, 14400, policy={"invest": 0.15}).final["science"]
    c_long = simulate.project(snap, 14400, policy={"invest": 0.60}).final["science"]
    assert c_long > a_long            # langer Horizont: Investition zahlt sich aus


def test_kitten_arrivals_raise_paragon_projection():
    snap = make_snap(kittens=100, max_kittens=120)
    snap["village"]["kittensPerSec"] = 0.05
    proj = simulate.project(snap, 600)
    assert proj.paragon_projection(0.0) == pytest.approx(30)
    assert proj.paragon_projection(600.0) > 30
    assert proj.paragon_eta(35) < 600
    # Ohne Ankunftsrate im Snapshot: konservativ konstant (kein Wachstum).
    snap2 = make_snap(kittens=100, max_kittens=120)
    proj2 = simulate.project(snap2, 600)
    assert proj2.paragon_projection(600.0) == pytest.approx(30)
    assert math.isinf(proj2.paragon_eta(35))


def test_summary_is_compact_and_serializable():
    snap = make_snap(resources={"gold": {"value": 5, "max": 50, "rate": 0.1}})
    s = simulate.project(snap, 600).summary()
    assert set(s) == {"horizonS", "invest", "final", "kittensEnd", "paragonEnd"}


# ================================================================ Run-Plan (8.3)

def test_run_plan_first_state_yields_first_run():
    snap = _with_prestige(make_snap(
        resources={"catnip": {"value": 100, "max": 5000, "rate": 2.0}}, kittens=10))
    rt, variant, detail = meta.determine_run_plan(snap)
    assert rt == "FIRST_RUN"
    # Ziel im Horizont unerreichbar → alle Varianten inf → Tie-Break a (C.2):
    assert variant == "a_minimal"
    assert meta.determine_run(snap) == "FIRST_RUN"


def test_run_plan_open_perk_yields_price_ratio_run():
    snap = _with_prestige(make_snap(
        resources={"science": {"value": 0, "max": 0, "rate": 1.0}},
        techs={"metaphysics": {"researched": False, "prices": {"science": 450}}},
        kittens=5), paragon=40, karma=1)
    rt, variant, detail = meta.determine_run_plan(snap)
    assert rt == "PRICE_RATIO_RUN"
    assert variant is not None


def test_run_plan_minimal_variant_wins_short_horizon():
    # Jahr 1 → Horizont 1640 s; Science-Ziel 450 ist am schnellsten mit
    # wenig Investition erreichbar (invest kürzt den Bestandszufluss).
    snap = _with_prestige(make_snap(
        resources={"science": {"value": 0, "max": 0, "rate": 1.0}},
        techs={"metaphysics": {"researched": False, "prices": {"science": 450}}},
        kittens=5), paragon=40, karma=1)
    rt, variant, _ = meta.determine_run_plan(snap)
    assert (rt, variant) == ("PRICE_RATIO_RUN", "a_minimal")


def test_run_plan_invest_variant_wins_long_horizon():
    # Jahr 9 → Horizont 4 h; Ziel so groß, dass nur der investitionsstarke
    # Pfad es im Horizont erreicht (Ratenwachstum schlägt Bestandsabzug).
    snap = _with_prestige(make_snap(
        resources={"science": {"value": 0, "max": 0, "rate": 1.0}},
        techs={"metaphysics": {"researched": False, "prices": {"science": 88_300}}},
        kittens=5), paragon=40, karma=1)
    snap["calendar"]["year"] = 9
    rt, variant, _ = meta.determine_run_plan(snap)
    assert (rt, variant) == ("PRICE_RATIO_RUN", "c_investitionsstark")


def test_run_plan_fallback_without_data():
    # Leerer Snapshot (Alt-Test-Situation): feste Ableitung, keine Variante.
    rt, variant, detail = meta.determine_run_plan(_with_prestige(make_snap()))
    assert rt == "FIRST_RUN"
    assert variant is None
    assert "fallback" in detail


def test_run_type_constants_cover_spec_8_2():
    assert len(meta.RUN_TYPES) == 13
    assert meta.ACTIVE_RUN_TYPES <= meta.RUN_TYPES


# ================================================================ CS-Suche (19.1)

def test_chronosphere_search_yields_target_in_window():
    snap = make_snap(
        resources={"catnip": {"value": 40000, "max": 50000, "rate": 5.0},
                   "unobtainium": {"value": 1000, "max": 5000, "rate": 50.0}},
        buildings={"chronosphere": {"val": 1, "prices": {"unobtainium": 100}}},
        jobs={"farmer": 5}, kittens=5)
    n_target, detail = chrono.optimal_chronosphere_count(snap)
    assert n_target is not None
    assert 0 <= n_target <= 4            # Fenster n−2 … n+3 um n=1
    assert detail["nTarget"] == n_target
    assert n_target > 1                  # billiges UO + hoher Carryover → ausbauen
    assert detail["csValueNext"] > 0
    # RebuildDelay aus beobachteten Raten (#43): UO-Rate 50/s liefert die ETA.
    assert detail["rebuildMode"] == "eta"


def test_chronosphere_search_fallback_without_data():
    n_target, detail = chrono.optimal_chronosphere_count(make_snap())
    assert n_target is None
    assert "Fallback" in detail["reason"]


def _generate(snap):
    return tactics.generate(snap, meta.evaluate(snap), safety.check(snap))


def test_chronosphere_candidate_gated_by_target():
    # UO-Rate ≈ 0 → weitere Chronospheres unbezahlbar → n_target = Bestand →
    # der Kauf-Kandidat wird unterdrückt (statt opportunistisch zu kaufen).
    snap = make_snap(
        resources={"catnip": {"value": 40000, "max": 50000, "rate": 50.0},
                   "unobtainium": {"value": 200, "max": 1000, "rate": 0.01}},
        buildings={"chronosphere": {"val": 1, "prices": {"unobtainium": 100}}},
        jobs={"farmer": 5}, kittens=5)
    cands, _ = _generate(snap)
    cs = next(c for c in cands if c.action.id == "build:chronosphere")
    assert not cs.feasible
    assert "Zielzahl" in cs.reject_reason


def test_chronosphere_candidate_with_cs_value_below_target():
    snap = make_snap(
        resources={"catnip": {"value": 40000, "max": 50000, "rate": 5.0},
                   "unobtainium": {"value": 1000, "max": 5000, "rate": 50.0}},
        buildings={"chronosphere": {"val": 1, "prices": {"unobtainium": 100}}},
        jobs={"farmer": 5}, kittens=5)
    cands, _ = _generate(snap)
    cs = next(c for c in cands if c.action.id == "build:chronosphere")
    assert cs.feasible
    assert cs.components["csValue"] > 0          # Sekundenwert, transparent
    assert cs.score == pytest.approx(1.2)        # csValue ist NICHT additiv
