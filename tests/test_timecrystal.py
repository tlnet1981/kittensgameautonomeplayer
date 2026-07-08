"""Tests der Shatter-Engine (Spec 17.1–17.5), des AM-Cap-Makroplans
(16.3/17.4), der positiven CS-Schleife (19.2/19.3) und von Tempus Fugit
(Anhang B SET_TEMPUS_FUGIT)."""

import math

import pytest

from player.brain import actions, chrono, meta, simulate, tactics, timecrystal
from tests.helpers import make_snap


def _time_section(rr=0, heat=0.0, heat_max=100.0, furnace_val=None,
                  voidspace=None, **extra):
    """Time-Sektion im Format von driver/snapshot.js."""
    cf = []
    if rr is not None:
        cf.append({"name": "ressourceRetrieval", "label": "Resource Retrieval",
                   "val": rr, "unlocked": True,
                   "prices": [{"name": "timeCrystal", "val": 1000}]})
    if furnace_val is not None:
        cf.append({"name": "blastFurnace", "label": "Chrono Furnace",
                   "val": furnace_val, "unlocked": True,
                   "prices": [{"name": "timeCrystal", "val": 25},
                              {"name": "relic", "val": 5}]})
    out = {"heat": heat, "heatMax": heat_max, "flux": 0,
           "chronoforge": cf, "voidspace": voidspace or []}
    out.update(extra)
    return out


# ================================================================ 17.1 TC-Bilanz

def test_tc_balance_positive_sources():
    snap = make_snap(resources={
        "timeCrystal": {"value": 30, "max": 0, "rate": 0.5},
        "alicorn": {"value": 60, "max": 0, "rate": 0.01}})
    bal = timecrystal.tc_balance(snap)
    assert bal["stock"] == 30
    assert bal["ratePerSec"] == pytest.approx(0.5)
    # 60 Alicorns = 2 Batches à 25 → 2 TC (tcRefineRatio 0, religion.js:3040):
    assert bal["alicornTcPotential"] == pytest.approx(2.0)
    assert bal["netPositive"]


def test_tc_balance_leviathans_and_negative():
    snap = make_snap(
        resources={"timeCrystal": {"value": 30, "max": 0, "rate": 0.0}},
        races=[{"name": "leviathans", "title": "Leviathans",
                "buys": [{"name": "unobtainium", "val": 5000}],
                "sells": [{"name": "timeCrystal", "value": 0.25, "chance": 98}]}])
    bal = timecrystal.tc_balance(snap)
    assert bal["leviathanTcPerTrade"] == pytest.approx(0.245)
    assert bal["netPositive"]
    # Ohne Zuflussquelle (nur Bestand): Bilanz nicht positiv.
    snap2 = make_snap(resources={"timeCrystal": {"value": 500, "max": 0, "rate": 0.0}})
    assert not timecrystal.tc_balance(snap2)["netPositive"]


# ================================================================ 17.2 RR-Wert

def test_rr_value_formula():
    # Marginal je Shatter-Jahr: 5/s ÷ 5 Ticks/s × 4000 Ticks × 0.01 = 40
    # Einheiten × λ 2.0 = 80 s. ExpectedShatters = 2000 − 1000 − 5 = 995.
    # TC-Preis zum OPPORTUNITÄTSWERT (#43): Shatter-Jahresertrag bei RR 1
    # = 80 s/TC (> λ_TC 0.5 — das Mini-λ unterschätzte die 1000 durch den
    # RR-Kauf verschossenen Shatter). RRValue = 80·995 − 1000·80 = −400 s.
    snap = make_snap(resources={
        "unobtainium": {"value": 0, "max": 0, "rate": 5.0},
        "timeCrystal": {"value": 2000, "max": 0, "rate": 0}})
    snap["time"] = _time_section(rr=1)
    lam = {"unobtainium": 2.0, "timeCrystal": 0.5}
    rrv = timecrystal.rr_value(snap, lam)
    assert rrv["marginalPerShatterS"] == pytest.approx(80.0)
    assert rrv["expectedShatters"] == pytest.approx(995.0)
    assert rrv["tcValueMode"] == "shatterYield"
    assert rrv["tcValueS"] == pytest.approx(80.0)
    assert rrv["rrValueS"] == pytest.approx(-400.0)


def test_rr_value_negative_without_production_and_none_without_entry():
    snap = make_snap(resources={"timeCrystal": {"value": 2000, "max": 0, "rate": 0}})
    snap["time"] = _time_section(rr=0)
    rrv = timecrystal.rr_value(snap, {"timeCrystal": 0.5})
    assert rrv["rrValueS"] < 0          # kein Ertrag, aber TC-Preis
    snap["time"] = {"heat": 0, "heatMax": 100, "flux": 0,
                    "chronoforge": [], "voidspace": []}
    assert timecrystal.rr_value(snap, {"timeCrystal": 0.5}) is None


# ================================================================ 17.3 Furnace-Wert

def test_furnace_value_positive_when_heat_blocks():
    # heat 90/100, 10 Heat je Shatter → headroom 1; TC 30 → desired 25 →
    # blocked 24. Abbaurate 0.01·5 = 0.05/s → +Furnace 0.15/s:
    # AvoidedIdle = 24·10·(1/0.05 − 1/0.15) = 3200 s.
    # Zusatzbatch = min(24, 100/10) = 10 Shatter × 80 s Ertrag = 800 s.
    # Kosten = 25·0.5 = 12.5 s (kein λ_relic). Summe 3987.5 s.
    snap = make_snap(resources={
        "unobtainium": {"value": 0, "max": 0, "rate": 5.0},
        "timeCrystal": {"value": 30, "max": 0, "rate": 0}})
    snap["time"] = _time_section(rr=1, heat=90, heat_max=100, furnace_val=0)
    lam = {"unobtainium": 2.0, "timeCrystal": 0.5}
    fnv = timecrystal.furnace_value(snap, lam, horizon=600)
    assert fnv["blockedShatters"] == pytest.approx(24.0)
    assert fnv["avoidedIdleS"] == pytest.approx(3200.0)
    assert fnv["additionalBatchS"] == pytest.approx(800.0)
    assert fnv["furnaceValueS"] == pytest.approx(3987.5)


def test_furnace_value_negative_without_heat_pressure():
    snap = make_snap(resources={
        "unobtainium": {"value": 0, "max": 0, "rate": 5.0},
        "timeCrystal": {"value": 10, "max": 0, "rate": 0}})
    snap["time"] = _time_section(rr=1, heat=0, heat_max=1000, furnace_val=0)
    fnv = timecrystal.furnace_value(snap, {"unobtainium": 2.0, "timeCrystal": 0.5}, 600)
    assert fnv["blockedShatters"] == 0
    assert fnv["furnaceValueS"] < 0     # nur Kosten, Heat begrenzt nichts
    # Ohne blastFurnace-Eintrag: None (Schicht nicht erreicht).
    snap["time"] = _time_section(rr=1)
    assert timecrystal.furnace_value(snap, {}, 600) is None


# ================================================================ 17.5 Regeln A–D

def test_shatter_rule_a_maximizes_batch_under_heat():
    snap = make_snap(resources={
        "unobtainium": {"value": 0, "max": 0, "rate": 5.0},
        "timeCrystal": {"value": 20, "max": 0, "rate": 0}})
    snap["time"] = _time_section(rr=1, heat=0, heat_max=100)
    lam = {"unobtainium": 2.0, "timeCrystal": 0.5}
    batch, rule, detail = timecrystal.shatter_decision(snap, lam)
    assert rule == "A"
    # Ertrag linear (kein Cap) → Batch = Heat-Headroom 100/10 = 10
    # (TC-Spielraum wäre 15):
    assert batch == 10
    assert detail["valueS"] > 0

    snap["time"] = _time_section(rr=1, heat=80, heat_max=100)
    batch, rule, _ = timecrystal.shatter_decision(snap, lam)
    assert (rule, batch) == ("A", 2)    # Heat-Constraint drückt den Batch


def test_shatter_rule_a_batch_stops_at_resource_cap():
    # Cap 60 klemmt den kumulativen Ertrag (time.js:693-705): Jahr 1 = 40,
    # Jahr 2 = 60 (Sättigung) → optimaler Batch 2, nicht 10.
    snap = make_snap(resources={
        "unobtainium": {"value": 0, "max": 60, "rate": 5.0},
        "timeCrystal": {"value": 20, "max": 0, "rate": 0}})
    snap["time"] = _time_section(rr=1, heat=0, heat_max=100)
    batch, rule, _ = timecrystal.shatter_decision(
        snap, {"unobtainium": 2.0, "timeCrystal": 0.5})
    assert (rule, batch) == ("A", 2)


def test_shatter_rule_b_cycle_positioning():
    # Cycle cath (Index 4) → redmoon (Index 5): 5 Jahre; redmoon boostet
    # moonOutpost-Unobtainium ×1.2 (calendar.js:141-148).
    snap = make_snap(resources={
        "unobtainium": {"value": 0, "max": 0, "rate": 2.0},
        "timeCrystal": {"value": 20, "max": 0, "rate": 0}})
    snap["time"] = _time_section(rr=0, heat=0, heat_max=100)
    snap["calendar"]["cycle"] = 4
    snap["calendar"]["cycleYear"] = 0
    snap["space"] = {"programs": [], "planets": [{
        "name": "moon", "label": "Moon", "buildings": [
            {"name": "moonOutpost", "label": "Lunar Outpost", "val": 3,
             "unlocked": True, "prices": []}]}]}
    lam = {"unobtainium": 3.0, "timeCrystal": 0.1}
    batch, rule, detail = timecrystal.shatter_decision(snap, lam, horizon=600)
    assert rule == "B"
    assert batch == 5                     # genau bis zum Cycle-Start
    assert detail["targetCycle"] == "redmoon"
    assert detail["valueS"] > 0


def test_shatter_rule_c_1000_years_challenge():
    snap = make_snap(
        resources={"timeCrystal": {"value": 20, "max": 0, "rate": 0}},
        challenges=[{"name": "1000Years", "active": True, "unlocked": True}])
    snap["time"] = _time_section(rr=0, heat=0, heat_max=100)
    batch, rule, detail = timecrystal.shatter_decision(snap, {})
    assert rule == "C"
    assert batch == 10                    # max. Batch unter Heat-Constraint
    assert detail["challenge"] == "1000Years"


def test_shatter_rule_d_paragon_boundary():
    snap = make_snap(resources={"timeCrystal": {"value": 20, "max": 0, "rate": 0}})
    snap["time"] = _time_section(rr=0, heat=0, heat_max=100)
    snap["calendar"]["year"] = 995        # 5 Jahre bis floor(year/1000)+1
    batch, rule, detail = timecrystal.shatter_decision(snap, {"timeCrystal": 0.5})
    assert (rule, batch) == ("D", 5)
    assert detail["paragonGain"] == 1
    # Grenze außerhalb des Batch-Fensters → keine Regel greift:
    snap["calendar"]["year"] = 100
    assert timecrystal.shatter_decision(snap, {"timeCrystal": 0.5}) is None


def test_shatter_rule_d_reacts_to_state():
    """Pflichttest #43: Regel D bewertet Paragon und TC aus dem Zustand —
    paragon_value_s = Δratio/(1+ratio) × Σλ·rate × H = 0.01 × (2.0·5.0)
    × 600 = 60 s statt der Konstante 900."""
    snap = make_snap(resources={
        "science": {"value": 0, "max": 0, "rate": 5.0},
        "timeCrystal": {"value": 20, "max": 0, "rate": 0}})
    snap["time"] = _time_section(rr=0, heat=0, heat_max=100)
    snap["calendar"]["year"] = 995
    # TC-Kosten 5 Jahre × λ_TC 20 = 100 s > 60 s Paragon-Wert → KEIN
    # Shatter (mit PARAGON_VALUE_REF_S 900 hätte die Regel gefeuert):
    assert timecrystal.shatter_decision(
        snap, {"science": 2.0, "timeCrystal": 20.0}, horizon=600) is None
    # Billigere TC (λ_TC 2.0 → Kosten 10 s < 60 s): Regel D feuert.
    batch, rule, detail = timecrystal.shatter_decision(
        snap, {"science": 2.0, "timeCrystal": 2.0}, horizon=600)
    assert (rule, batch) == ("D", 5)
    assert detail["paragonValueS"] == pytest.approx(60.0)
    assert detail["valueS"] == pytest.approx(50.0)
    assert detail["tcValueMode"] == "lambda"


def test_shatter_decision_fallbacks_without_data():
    snap = make_snap(resources={"timeCrystal": {"value": 100, "max": 0, "rate": 0}})
    assert timecrystal.shatter_decision(snap, {"timeCrystal": 0.5}) is None
    snap["time"] = _time_section(rr=1, heat_max=0)      # keine Heat-Daten
    assert timecrystal.shatter_decision(snap, {"timeCrystal": 0.5}) is None
    snap["time"] = _time_section(rr=1, heat_max=100)
    snap["resources"][0]["value"] = 5.0                 # nur Reserve → kein Batch
    assert timecrystal.shatter_decision(snap, {"timeCrystal": 0.5}) is None


# ================================================================ Taktik-Integration

def test_rr_candidate_rejected_on_negative_rr_value():
    snap = make_snap(resources={"timeCrystal": {"value": 2000, "max": 0, "rate": 0}})
    snap["time"] = _time_section(rr=0, heat=0, heat_max=100)
    cands = []
    tactics._time_candidates(snap, cands, lam={"timeCrystal": 0.5},
                             horizon=600, run_type="PARAGON_RUN")
    rr = next(c for c in cands if c.action.id == "chronoforge:ressourceRetrieval")
    assert not rr.feasible
    assert "RRValue" in rr.reject_reason
    assert rr.components["rrValue"] < 0
    # Ohne Ertrag feuert auch keine Shatter-Regel:
    assert not any(c.action.id == "time:shatter" for c in cands)
    assert "rrValue" in tactics.SHADOW_INFO_KEYS
    assert "furnaceValue" in tactics.SHADOW_INFO_KEYS
    assert "shatterValue" in tactics.SHADOW_INFO_KEYS


def test_rr_candidate_positive_and_shatter_engine_batch():
    # TC 5000: RRValue = 80·(5000−1000−5) − 1000·80 = +239 600 s — seit
    # #43 kostet der RR-Kauf den TC-Opportunitätswert (80 s/TC), positiv
    # wird er erst, wenn die künftigen Shatter die 1000 TC überkompensieren.
    snap = make_snap(resources={
        "unobtainium": {"value": 0, "max": 0, "rate": 5.0},
        "timeCrystal": {"value": 5000, "max": 0, "rate": 0}})
    snap["time"] = _time_section(rr=1, heat=0, heat_max=100)
    cands = []
    lam = {"unobtainium": 2.0, "timeCrystal": 0.5}
    tactics._time_candidates(snap, cands, lam=lam, horizon=600,
                             run_type="PARAGON_RUN")
    rr = next(c for c in cands if c.action.id == "chronoforge:ressourceRetrieval")
    assert rr.feasible and rr.components["rrValue"] > 0
    sh = next(c for c in cands if c.action.id == "time:shatter")
    assert sh.action.batch == 10          # Regel A, Heat-Headroom 100/10
    assert sh.components["shatterValue"] > 0
    # rrValue/shatterValue sind Anzeige-Sekundenwerte, nicht additiv:
    assert rr.score == pytest.approx(1.3)
    assert sh.score == pytest.approx(1.1)


def test_furnace_candidate_gated_by_furnace_value():
    snap = make_snap(resources={
        "unobtainium": {"value": 0, "max": 0, "rate": 5.0},
        "timeCrystal": {"value": 200, "max": 0, "rate": 0},
        "relic": {"value": 50, "max": 0, "rate": 0}})
    lam = {"unobtainium": 2.0, "timeCrystal": 0.5}
    # Heat blockiert → Furnace-Kandidat mit positivem furnaceValue:
    snap["time"] = _time_section(rr=1, heat=95, heat_max=100, furnace_val=0)
    cands = []
    tactics._time_candidates(snap, cands, lam=lam, horizon=600)
    fn = next(c for c in cands if c.action.id == "chronoforge:blastFurnace")
    assert fn.feasible and fn.components["furnaceValue"] > 0
    # Kein Heat-Druck → abgelehnt (17.3):
    snap["time"] = _time_section(rr=1, heat=0, heat_max=10000, furnace_val=0)
    cands = []
    tactics._time_candidates(snap, cands, lam=lam, horizon=600)
    fn = next(c for c in cands if c.action.id == "chronoforge:blastFurnace")
    assert not fn.feasible
    assert "FurnaceValue" in fn.reject_reason


def test_conservative_fallback_without_lambda_unchanged():
    # Bestandsverhalten (Fallback-Pfad): ohne λ-Daten gilt die alte Regel
    # (RR ≥ 1, 5-TC-Reserve, Batch ≤ 5, Heat-Spielraum) — wie test_m6.
    snap = make_snap(resources={"timeCrystal": {"value": 30, "max": 0, "rate": 0}})
    snap["time"] = _time_section(rr=2, heat=0, heat_max=100)
    cands = []
    tactics._time_candidates(snap, cands, lam=None, horizon=None)
    sh = next(c for c in cands if c.action.id == "time:shatter")
    assert 1 <= sh.action.batch <= 5


# ================================================================ Void (19.3)

def test_voidspace_candidates_only_in_seed_run():
    snap = make_snap(resources={"void": {"value": 100, "max": 0, "rate": 0}})
    snap["time"] = _time_section(rr=None, voidspace=[
        {"name": "voidRift", "label": "Void Rift", "val": 0, "unlocked": True,
         "prices": [{"name": "void", "val": 75}]}])
    cands = []
    tactics._time_candidates(snap, cands, run_type="SEED_RUN")
    vr = next(c for c in cands if c.action.id == "voidspace:voidRift")
    assert vr.components["voidValue"] > 0
    # Kein Beiläufig-Einbau in Paragon-Runs (19.3):
    cands = []
    tactics._time_candidates(snap, cands, run_type="PARAGON_RUN")
    assert not any(c.action.id == "voidspace:voidRift" for c in cands)


def test_cryochambers_candidate_in_any_run():
    snap = make_snap(resources={
        "void": {"value": 200, "max": 0, "rate": 0},
        "timeCrystal": {"value": 10, "max": 0, "rate": 0},
        "karma": {"value": 5, "max": 0, "rate": 0}})
    snap["time"] = _time_section(rr=None, voidspace=[
        {"name": "cryochambers", "label": "Cryochamber", "val": 0,
         "unlocked": True, "prices": [{"name": "void", "val": 100},
                                      {"name": "timeCrystal", "val": 2},
                                      {"name": "karma", "val": 1}]}])
    cands = []
    tactics._time_candidates(snap, cands, run_type="PARAGON_RUN")
    assert any(c.action.id == "voidspace:cryochambers" for c in cands)


# ================================================================ 19.2 Vektordominanz

def _cs_snap(uo_value: float, cs: int = 2):
    return make_snap(
        resources={"unobtainium": {"value": uo_value, "max": 2 * uo_value + 1,
                                   "rate": 1.0}},
        buildings={"chronosphere": {"val": cs, "prices": {"unobtainium": 100}}})


def test_positive_cs_check_dominates():
    # 2 CS → saveRatio 3 %: Carryover 10000·0.03 = 300 Unobtainium;
    # Wiederaufbau Einheiten 1+2 = 100·(1+1.25)/1.25² = 144 → Dominanz.
    dom, detail = chrono.positive_cs_check(_cs_snap(10000))
    assert dom
    assert detail["coversRebuild"]
    assert detail["carry"]["unobtainium"] == pytest.approx(300.0)
    assert detail["rebuild"]["unobtainium"] == pytest.approx(144.0)


def test_positive_cs_check_negative_cases():
    dom, _ = chrono.positive_cs_check(_cs_snap(1000))   # 30 < 144
    assert not dom
    dom, detail = chrono.positive_cs_check(make_snap())  # keine Chronosphere
    assert not dom and "Chronosphere" in detail["reason"]


def test_carryover_vector_follows_reset_rules():
    snap = _cs_snap(10000)
    snap["resources"].append({"name": "timeCrystal", "title": "TC", "value": 50,
                              "maxValue": 0, "craftable": False,
                              "unlocked": True, "perSec": 0})
    snap["resources"].append({"name": "plate", "title": "Plate", "value": 400,
                              "maxValue": 0, "craftable": True,
                              "unlocked": True, "perSec": 0})
    carry = chrono.carryover_vector(snap)
    # TC ohne Anachronomancy: verloren (game.js:5050-5053).
    assert carry["timeCrystal"] == 0.0
    # Craftbar ohne fluxCondensator: verloren (game.js:5044-5047).
    assert carry["plate"] == 0.0
    snap["prestige"]["perks"] = [{"name": "anachronomancy", "researched": True}]
    snap["workshop"]["upgrades"] = [{"name": "fluxCondensator", "label": "FC",
                                     "researched": True, "unlocked": True,
                                     "prices": []}]
    carry = chrono.carryover_vector(snap)
    assert carry["timeCrystal"] == 50.0
    # sqrt(400)·0.03·100 = 60 (game.js:5062-5064):
    assert carry["plate"] == pytest.approx(60.0)


def test_chronosphere_rebuild_delay_from_observed_rates():
    """Pflichttest #43: RebuildDelay aus beobachteten Raten (ETA) statt
    der Konstante 60 s/CS; ohne Rate greift ehrlich der Fallback."""
    def _rebuild_snap(rate):
        return make_snap(
            resources={"unobtainium": {"value": 1000, "max": 5000,
                                       "rate": rate}},
            buildings={"chronosphere": {"val": 1,
                                        "prices": {"unobtainium": 100}}})
    # Rate 0: keine ETA möglich → Fallback-Modus, RebuildDelay = 60·k
    # (UOCost 0, solange der Bestand die Einheiten deckt; Carryover 0
    # ohne positive Rate):
    _, detail = chrono.optimal_chronosphere_count(_rebuild_snap(0.0))
    assert detail["rebuildMode"] == "fallback"
    assert detail["csValues"][2] == pytest.approx(-120.0)
    # Rate 50/s: RebuildETA(k) = 80·Σ_{j<k}1.25^j / 50 (Basis 100/1.25).
    # k=1: 0.3 − 0 − 1.6 = −1.3; k=2: 0.6 − 2.0 − 3.6 = −5.0 — Sekunden
    # statt Minuten, der Zustand entscheidet:
    _, detail = chrono.optimal_chronosphere_count(_rebuild_snap(50.0))
    assert detail["rebuildMode"] == "eta"
    assert detail["csValues"][1] == pytest.approx(-1.3)
    assert detail["csValues"][2] == pytest.approx(-5.0)


def test_seed_run_admissible_conservative():
    ok, _ = chrono.seed_run_admissible(make_snap())
    assert not ok
    snap = make_snap(resources={"void": {"value": 10, "max": 0, "rate": 0}},
                     buildings={"chronosphere": {"val": 1,
                                                 "prices": {"unobtainium": 100}}})
    ok, detail = chrono.seed_run_admissible(snap)
    assert ok and detail["chronospheres"] == 1


# ================================================================ Run-Typen (8.2)

def test_leviathan_run_admissible():
    snap = make_snap(races=[{"name": "leviathans", "title": "Leviathans",
                             "buys": [{"name": "unobtainium", "val": 5000}],
                             "sells": [{"name": "timeCrystal", "value": 0.25,
                                        "chance": 98}]}])
    assert "LEVIATHAN_RUN" in meta._admissible_run_types(snap)
    # Ohne TC-Position im Angebot: nicht zulässig.
    snap2 = make_snap(races=[{"name": "leviathans", "title": "Leviathans",
                              "buys": [], "sells": [{"name": "relic",
                                                     "value": 1, "chance": 100}]}])
    assert "LEVIATHAN_RUN" not in meta._admissible_run_types(snap2)


def test_shatter_run_admissible_needs_rr_and_positive_balance():
    snap = make_snap(resources={"timeCrystal": {"value": 30, "max": 0, "rate": 0.5}})
    snap["time"] = _time_section(rr=1)
    assert "SHATTER_RUN" in meta._admissible_run_types(snap)
    snap["time"] = _time_section(rr=0)              # keine RR-Infrastruktur
    assert "SHATTER_RUN" not in meta._admissible_run_types(snap)
    snap["time"] = _time_section(rr=1)
    snap["resources"][0]["perSec"] = 0.0            # Bilanz nicht positiv
    assert "SHATTER_RUN" not in meta._admissible_run_types(snap)


def test_relic_station_run_admissible_and_done():
    snap = make_snap(resources={"antimatter": {"value": 100, "max": 500, "rate": 0}})
    assert "RELIC_STATION_RUN" in meta._admissible_run_types(snap)
    # Ziel erreicht (Upgrade + AM-Cap 5000): nicht mehr zulässig.
    snap = make_snap(resources={"antimatter": {"value": 100, "max": 5000, "rate": 0}})
    snap["workshop"]["upgrades"] = [{"name": "relicStation", "label": "Relic Station",
                                     "researched": True, "unlocked": True,
                                     "prices": []}]
    assert "RELIC_STATION_RUN" not in meta._admissible_run_types(snap)


def test_positive_cs_and_seed_run_admissible():
    snap = _cs_snap(10000)
    snap["resources"].append({"name": "void", "title": "Void", "value": 10,
                              "maxValue": 0, "craftable": False,
                              "unlocked": True, "perSec": 0})
    adm = meta._admissible_run_types(snap)
    assert "POSITIVE_CS_RUN" in adm
    assert "SEED_RUN" in adm
    assert meta.ACTIVE_RUN_TYPES <= meta.RUN_TYPES


def test_shatter_run_restzeit_zero_when_stocked():
    snap = make_snap(resources={"timeCrystal": {"value": 30, "max": 0, "rate": 0.5},
                                "catnip": {"value": 100, "max": 5000, "rate": 1.0}})
    snap["time"] = _time_section(rr=1)
    proj = simulate.project(snap, 600)
    assert meta._plan_restzeit(snap, "SHATTER_RUN", proj, 600) == 0.0
    snap["resources"][0]["value"] = 10.0     # unter dem Ziel → Rate zählt
    rz = meta._plan_restzeit(snap, "SHATTER_RUN", proj, 600)
    # Seit #38 ist das TC-Ziel zustandsabhängig (Reserve + Heat-gedeckelter
    # Batch, hier heatMax 100/10 → 5+10 = 15) statt der Konstante Reserve+15:
    assert rz == pytest.approx((meta._shatter_tc_target(snap) - 10.0) / 0.5)
    snap["resources"][0]["perSec"] = 0.0
    assert math.isinf(meta._plan_restzeit(snap, "SHATTER_RUN", proj, 600))


# ================================================================ AM-Cap (16.3/17.4)

def _relic_snap():
    snap = make_snap(resources={
        "antimatter": {"value": 200, "max": 400, "rate": 0.1},
        "science": {"value": 10 ** 6, "max": 2 * 10 ** 6, "rate": 100},
        "kerosene": {"value": 10 ** 5, "max": 0, "rate": 1, "craftable": True}})
    snap["space"] = {"programs": [], "planets": [{
        "name": "helios", "label": "Helios", "buildings": [
            {"name": "containmentChamber", "label": "Containment Chamber",
             "val": 4, "unlocked": True, "energyConsumption": 50,
             "prices": [{"name": "science", "val": 500000},
                        {"name": "kerosene", "val": 2500}]}]}]}
    snap["workshop"]["upgrades"] = [{"name": "relicStation", "label": "Relic Station",
                                     "researched": False, "unlocked": True,
                                     "prices": [{"name": "antimatter", "val": 5000},
                                                {"name": "eludium", "val": 100}]}]
    return snap


def test_am_cap_milestones_block():
    snap = _relic_snap()
    ms = meta._am_cap_milestones(snap)
    assert [m.id for m in ms] == ["am_cap_5000", "relic_station"]
    cap, station = ms
    assert not cap.done(snap) and cap.visible(snap)
    assert not station.done(snap) and station.visible(snap)
    # Cap erreicht → erster Meilenstein fertig:
    snap["resources"][0]["maxValue"] = 5000
    assert cap.done(snap)
    # Ziel-Preisvektoren über die neuen Target-Kinds (tactics):
    p = tactics._target_prices(snap, {"kind": "space_build",
                                      "name": "containmentChamber"})
    assert p and p[0]["name"] == "science"
    p = tactics._target_prices(snap, {"kind": "workshop_upgrade",
                                      "name": "relicStation"})
    assert p and p[0]["name"] == "antimatter"


def test_space_building_energy_malus_16_2():
    snap = _relic_snap()
    # Energie-Balance 0, Verbrauch 50 → Defizit: Malus drückt unter Null.
    cands = []
    tactics._space_building_candidates(snap, None, None, cands,
                                       lam={"antimatter": 1.0})
    cc = next(c for c in cands if c.action.id == "space_bld:containmentChamber")
    assert cc.components["energyCost"] < 0
    assert cc.score < 0
    # Fallback ohne λ-Daten: Altverhalten (kein Malus).
    cands = []
    tactics._space_building_candidates(snap, None, None, cands, lam=None)
    cc = next(c for c in cands if c.action.id == "space_bld:containmentChamber")
    assert "energyCost" not in cc.components
    assert cc.score == pytest.approx(0.8)


# ================================================================ Tempus Fugit

def _tf_snap(accelerated: bool, flux_ticks: float):
    snap = make_snap(resources={"catnip": {"value": 100, "max": 5000, "rate": 10.0}})
    snap["time"] = _time_section(
        rr=None, isAccelerated=accelerated,
        temporalFlux={"value": flux_ticks, "maxValue": 3000})
    return snap


def test_tempus_fugit_on_with_flux_and_positive_profile():
    snap = _tf_snap(False, 1000)          # 200 s Vorrat ≥ 120 s
    cands = []
    tactics._tempus_fugit_candidate(snap, cands, lam={"catnip": 0.5}, horizon=600)
    tf = next(c for c in cands if c.action.id == "time:tempusFugit:on")
    # +50 % × (0.5 · 10/s) × 200 s Vorrat = 500 Ziel-Sekunden:
    assert tf.components["tfValue"] == pytest.approx(500.0)
    assert tf.action.atomicity == actions.REVERSIBLE
    assert tf.action.exec_spec == {"kind": "set_tempus_fugit", "on": True}
    assert "tfValue" in tactics.SHADOW_INFO_KEYS


def test_tempus_fugit_hysteresis_band_keeps_state():
    # 80 s Vorrat: unter der AN-Schwelle (120 s), über der AUS-Schwelle (30 s)
    # → in beiden Zuständen KEIN Kandidat (Anti-Flattern).
    for accelerated in (False, True):
        cands = []
        tactics._tempus_fugit_candidate(_tf_snap(accelerated, 400), cands,
                                        lam={"catnip": 0.5}, horizon=600)
        assert cands == []


def test_tempus_fugit_off_when_flux_scarce():
    snap = _tf_snap(True, 100)            # 20 s < 30 s → abschalten
    cands = []
    tactics._tempus_fugit_candidate(snap, cands, lam={"catnip": 0.5}, horizon=600)
    tf = next(c for c in cands if c.action.id == "time:tempusFugit:off")
    assert tf.action.exec_spec == {"kind": "set_tempus_fugit", "on": False}


def test_tempus_fugit_fallbacks():
    # Ohne isAccelerated im Snapshot (alte Snapshots): kein Kandidat.
    snap = make_snap(resources={"catnip": {"value": 100, "max": 5000, "rate": 10.0}})
    snap["time"] = _time_section(rr=None)
    cands = []
    tactics._tempus_fugit_candidate(snap, cands, lam={"catnip": 0.5}, horizon=600)
    assert cands == []
    # Ohne positives Produktionsprofil (λ leer): kein Einschalten.
    cands = []
    tactics._tempus_fugit_candidate(_tf_snap(False, 1000), cands, lam={},
                                    horizon=600)
    assert cands == []
