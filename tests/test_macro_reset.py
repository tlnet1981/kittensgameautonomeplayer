"""Tests des Makro-&-Reset-Pakets (#38+#39+#42, docs/spec-gaps.md):
Restzeiten projiziert statt Konstanten (8.3/18.2), Payback gegen den
geplanten Reset (10.4/6.4), Reset-Trigger je Run-Typ + V(post) (20.1/20.2)."""

import math

import pytest

from player.brain import challenge, chrono, meta, reset, safety, shadow, \
    simulate, tactics
from player.brain.meta import Milestone
from tests.helpers import make_snap


# ================================================== #38 SEED_RUN-Restzeit

def _seed_snap(cs=2, void_value=10.0, void_rate=0.1):
    return make_snap(
        resources={"void": {"value": void_value, "max": 0, "rate": void_rate},
                   "catnip": {"value": 1000, "max": 5000, "rate": 5.0}},
        buildings={"chronosphere": {"val": cs,
                                    "prices": {"unobtainium": 100}}},
    )


def test_seed_restzeit_reacts_to_state():
    """Auftragstest (#38): Die SEED-Restzeit ist zustandsabhängig statt
    6-h-Konstante — sie folgt Void-Rate und Chronosphere-Bestand."""
    proj = simulate.project(_seed_snap(), 600.0)
    # CS 2 → saveRatio 0.03; Ziel = 1/0.03 = 33,33 Void; (33,33−10)/0,1:
    base = meta._plan_restzeit(_seed_snap(), "SEED_RUN", proj, 600.0)
    assert base == pytest.approx((1 / 0.03 - 10) / 0.1, rel=1e-3)
    # Doppelte Rate → halbe Restzeit:
    fast = meta._plan_restzeit(_seed_snap(void_rate=0.2), "SEED_RUN",
                               proj, 600.0)
    assert fast == pytest.approx(base / 2, rel=1e-3)
    # Mehr Chronospheres → kleinere ganze Einheit → kürzer:
    more_cs = meta._plan_restzeit(_seed_snap(cs=4), "SEED_RUN", proj, 600.0)
    assert more_cs < base
    # Ohne Rate: ehrlich ∞ statt Konstante:
    assert math.isinf(meta._plan_restzeit(_seed_snap(void_rate=0.0),
                                          "SEED_RUN", proj, 600.0))


def test_seed_progress_basis_reached():
    snap = _seed_snap(void_value=40.0)          # floor(40×0.03) = 1
    prog = chrono.seed_progress(snap)
    assert prog["basisReached"]
    assert math.isfinite(prog["nextUnitEtaS"])
    # Ohne Chronosphere kein Carryover → keine Basis, ∞:
    prog0 = chrono.seed_progress(_seed_snap(cs=0))
    assert not prog0["basisReached"]
    assert math.isinf(prog0["nextUnitEtaS"])


# ============================================ #38 POSITIVE_CS-Restzeit

def test_positive_cs_restzeit_is_rebuild_earn_time():
    """Schleifeniterationsdauer = Verdienzeit der Wiederaufbaukosten über
    beobachtete Raten statt 60 s × n (#38, 19.4)."""
    snap = make_snap(
        resources={"unobtainium": {"value": 10000, "max": 20001, "rate": 1.0}},
        buildings={"chronosphere": {"val": 2, "prices": {"unobtainium": 100}}})
    proj = simulate.project(snap, 600.0)
    # Wiederaufbau Einheiten 1+2 = 100·(1+1.25)/1.25² = 144 UO bei 1 UO/s:
    rz = meta._plan_restzeit(snap, "POSITIVE_CS_RUN", proj, 600.0)
    assert rz == pytest.approx(144.0)
    # Rate 0 → ehrlich ∞:
    snap["resources"][0]["perSec"] = 0.0
    assert math.isinf(meta._plan_restzeit(snap, "POSITIVE_CS_RUN", proj, 600.0))


# ============================================ #38 SHATTER-TC-Ziel

def test_shatter_tc_target_follows_heat_headroom():
    snap = make_snap(resources={"timeCrystal": {"value": 0, "max": 0, "rate": 0}})
    # Ohne Heat-Daten: Fallback Reserve + 15 (Altverhalten):
    assert meta._shatter_tc_target(snap) == pytest.approx(20.0)
    # Heat-Spielraum 100 → Batch 10 → Ziel 15:
    snap["time"] = {"heat": 0, "heatMax": 100, "flux": 0,
                    "chronoforge": [], "voidspace": []}
    assert meta._shatter_tc_target(snap) == pytest.approx(15.0)
    # Fast voller Heat → Mindestbatch 1:
    snap["time"]["heat"] = 95
    assert meta._shatter_tc_target(snap) == pytest.approx(6.0)


# ============================================ #38 Challenge-Projektion

def test_completion_eta_per_goal():
    # anarchy: aiCore beobachtbar → Preis-ETA über die Rate:
    snap = make_snap(
        resources={"antimatter": {"value": 0, "max": 0, "rate": 0.5}},
        buildings={"aiCore": {"val": 0, "prices": {"antimatter": 100}}})
    eta, obs = challenge.completion_eta(snap, "anarchy")
    assert obs and eta == pytest.approx(200.0)
    # gebaut → 0:
    snap["buildings"][0]["val"] = 1
    assert challenge.completion_eta(snap, "anarchy") == (0.0, True)
    # bare Fixture → nicht beobachtbar:
    bare = make_snap()
    assert challenge.completion_eta(bare, "anarchy") == (math.inf, False)
    assert challenge.completion_eta(bare, "energy") == (math.inf, False)
    # pacifism über die Policy:
    psnap = make_snap(policies=[{"name": "outerSpaceTreaty",
                                 "researched": True}])
    assert challenge.completion_eta(psnap, "pacifism") == (0.0, True)
    # 1000Years: TC-Bedarf (1000−1)×1,5 über die Rate:
    tsnap = make_snap(resources={"timeCrystal": {"value": 0, "max": 0,
                                                 "rate": 1.0}})
    eta, obs = challenge.completion_eta(tsnap, "1000Years")
    assert obs and eta == pytest.approx(999 * 1.5)
    # unicornTears über pacts.necrocornPerDay (1 Tag = 2 s):
    usnap = make_snap(pacts={"list": [], "necrocornPerDay": 0.1})
    eta, obs = challenge.completion_eta(usnap, "unicornTears")
    assert obs and eta == pytest.approx(1.0 / 0.05)
    # postApocalypse: nie projizierbar, ehrlich ∞:
    assert challenge.completion_eta(bare, "postApocalypse") == (math.inf, True)


def test_challenge_value_zero_when_observable_but_unreachable():
    """Beobachtbares, aber unerreichbares Ziel → ChallengeValue ehrlich 0;
    ohne Zielobjekte im Snapshot bleibt die Referenz-Rangfolge (Fallback)."""
    snap = make_snap(
        resources={"starchart": {"value": 0, "max": 0, "rate": 0}},
        challenges=[{"name": "winterIsComing", "label": "Winter"}])
    snap["space"] = {"planets": [], "programs": [
        {"name": "heliosMission", "label": "Helios Mission", "val": 0,
         "unlocked": True, "prices": [{"name": "starchart", "val": 500}]}]}
    assert challenge.challenge_value(snap, "winterIsComing") == 0.0
    # Fallback-Pfad (keine Zielobjekte): alte Referenz-Rangfolge bleibt:
    bare = make_snap(challenges=[{"name": "winterIsComing"},
                                 {"name": "anarchy"}])
    assert (challenge.challenge_value(bare, "winterIsComing")
            > challenge.challenge_value(bare, "anarchy") > 0)


# ============================================ #39 Reset-Horizont

def test_evaluate_exports_eta_seconds():
    """reset.evaluate exportiert die erwartete Restlaufzeit bis zum
    geplanten Reset (#39): Durchreichung der Makroplan-Restzeit, 0 bei
    empfohlenem Reset, None ohne Reset-Ziel oder bei TC-Block."""
    # FIRST_RUN unter der Schwelle: Restzeit wird durchgereicht.
    snap = make_snap(kittens=80,
                     resources={"catnip": {"value": 1000, "max": 5000,
                                           "rate": 5.0}})
    ev = reset.evaluate(snap, "FIRST_RUN", None, plan_restzeit_s=1234.5)
    assert not ev["recommended"] and ev["etaSeconds"] == 1234.5
    # Empfohlener Reset (110 Kitten, kein Wachstum) → etaSeconds 0.
    snap = make_snap(kittens=110, max_kittens=110,
                     resources={"catnip": {"value": 50000, "max": 60000,
                                           "rate": 20.0}},
                     catnip_field_base=40)
    ev = reset.evaluate(snap, "FIRST_RUN", None, plan_restzeit_s=999.0)
    assert ev["recommended"] and ev["etaSeconds"] == 0.0
    # TC-Schutz blockiert → kein geplanter Reset → None (Heuristik-Fallback).
    snap["resources"].append({"name": "timeCrystal", "title": "TC",
                              "value": 10, "maxValue": 0, "craftable": False,
                              "unlocked": True, "perSec": 0})
    ev = reset.evaluate(snap, "FIRST_RUN", None, plan_restzeit_s=999.0)
    assert not ev["recommended"] and ev["etaSeconds"] is None
    # Kein Reset-Ziel (else-Zweig; SHATTER_RUN endet nicht im Reset) → None.
    snap2 = make_snap(kittens=5)
    ev = reset.evaluate(snap2, "SHATTER_RUN", None, plan_restzeit_s=999.0)
    assert ev["etaSeconds"] is None
    # SEED_RUN hat seit #42 ein Reset-Ziel: Restzeit wird durchgereicht,
    # solange der Trigger (Seed-Basis) noch offen ist.
    ev = reset.evaluate(snap2, "SEED_RUN", None, plan_restzeit_s=999.0)
    assert not ev["recommended"] and ev["etaSeconds"] == 999.0


def _payback_5h_snap():
    """Kandidat mit Payback ≈ 5,6 h: Effekt-Gebäude produziert das
    λ-tragende Zielgut (0,001/s), Preis 20 Minerals × λ 1000 s/Einheit →
    Payback 20000 s — über der 4-h-Heuristik-Klemme, unter 6 h."""
    return make_snap(
        resources={"minerals": {"value": 30, "max": 0, "rate": 0.001},
                   "catnip": {"value": 5000, "max": 6000, "rate": 10.0}},
        buildings={"mint": {"val": 0, "prices": {"minerals": 20},
                            "unlocked": True,
                            "effects": {"mineralsPerTickProd": 0.0002}}},
        jobs={"miner": 1}, kittens=1, max_kittens=2, catnip_field_base=40,
    )


def _gen(snap, target, run_horizon_s=None):
    mv = meta.MetaView(phase="P0", run_type="FIRST_RUN",
                       active=Milestone("test", "Testziel",
                                        lambda s: False, target),
                       milestones=[], open_targets=None)
    return tactics.generate(snap, mv, safety.check(snap),
                            run_horizon_s=run_horizon_s)[0]


def test_run_horizon_follows_reset_projection():
    """Auftragstest (#39): Das Payback-Gate prüft gegen den GEPLANTEN
    Reset — ein 5,6-h-Payback wird ohne Projektion (Heuristik ≤ 4 h)
    abgelehnt, mit 6-h-Reset-Projektion zugelassen; die 4-h-Klemme fällt
    nur bei echter Projektion."""
    target = {"kind": "resource", "name": "minerals", "amount": 1000}
    # Ohne Projektion: Heuristik (frischer Kalender → HORIZON_MIN) lehnt ab:
    cands = _gen(_payback_5h_snap(), target)
    mint = next(c for c in cands if c.action.id == "build:mint")
    assert not mint.feasible and "Payback" in mint.reject_reason
    # Mit geplanter Reset-Projektion 6 h: Payback 5,6 h passt hinein:
    cands = _gen(_payback_5h_snap(), target, run_horizon_s=6 * 3600.0)
    mint = next(c for c in cands if c.action.id == "build:mint")
    assert mint.feasible
    # etaSeconds ≈ 0 (Reset steht bevor): Anti-Deadlock-Floor greift —
    # der Horizont kollabiert nicht auf 0, kurze Paybacks bleiben möglich:
    cands = _gen(_payback_5h_snap(), target, run_horizon_s=0.0)
    mint = next(c for c in cands if c.action.id == "build:mint")
    assert not mint.feasible
    assert f"{shadow.HORIZON_PLANNED_MIN / 60:.0f}" in mint.reject_reason \
        or "Payback" in mint.reject_reason


# ============================================ #42 Reset-Trigger je Run-Typ

# Perk mit unbezahlbarem Preis: würde der Perk-Catch-all greifen, wäre
# recommended False — ein empfohlener Reset beweist den Run-Typ-Zweig.
_EXPENSIVE_PERK = {"name": "goldenRatio", "label": "Golden Ratio",
                   "researched": False, "unlocked": True,
                   "prices": [{"name": "paragon", "val": 100000}]}


def _with_prestige(snap, paragon=0, perks=None):
    snap["prestige"] = {"paragon": paragon, "burnedParagon": 0, "karma": 0,
                        "perks": perks or []}
    return snap


def _rel_upgrades():
    return [{"name": "apocripha", "label": "Apocrypha", "val": 1, "on": 1,
             "unlocked": True, "noStackable": True, "prices": []},
            {"name": "transcendence", "label": "Transcendence", "val": 1,
             "on": 1, "unlocked": True, "noStackable": True, "prices": []}]


def test_religion_run_reaches_reset_transaction(monkeypatch):
    """Auftragstest (#42): RELIGION_RUN erreicht seine Reset-Transaktion —
    TAP-Punkt erreicht → recommended (vor dem Perk-Catch-all), und
    execute_reset führt TAP (Schritt 5) und den Reset (Schritt 11) aus."""
    from tests.test_reset import _FakeBrowser, _run_execute, _steps

    snap = _with_prestige(make_snap(
        resources={"faith": {"value": 500, "max": 200000, "rate": 50.0},
                   "catnip": {"value": 50000, "max": 60000, "rate": 20.0}},
        jobs={"priest": 5}, kittens=110, max_kittens=110,
        catnip_field_base=40,
        religion={"worship": 10000, "epiphany": 0.1, "transcendenceTier": 0,
                  "upgrades": _rel_upgrades()}))
    ev = reset.evaluate(snap, "RELIGION_RUN", _EXPENSIVE_PERK,
                        plan_restzeit_s=500.0)
    assert ev["recommended"], ev["reason"]
    assert "TAP-Punkt" in ev["reason"]          # Run-Typ-Zweig, nicht Perk
    assert ev["tapPlan"] and ev["tapPlan"][0]["step"] == "transcend"
    assert ev["etaSeconds"] == 0.0
    ok, rt = _run_execute(snap, ev, monkeypatch, _FakeBrowser())
    assert ok is True
    by_step = dict(_steps(rt))
    assert by_step[5] == "done"                 # TAP ausgeführt
    assert by_step[11] == "done"                # Reset committed


def test_unicorn_run_reset_trigger():
    def _snap(unicorns):
        return _with_prestige(make_snap(
            resources={"unicorns": {"value": unicorns, "max": 0, "rate": 5.0},
                       "catnip": {"value": 50000, "max": 60000, "rate": 20.0}},
            buildings={"ziggurat": {"val": 1, "prices": {"megalith": 50}}},
            kittens=110, max_kittens=110, catnip_field_base=40))
    ev = reset.evaluate(_snap(3000), "UNICORN_RUN", _EXPENSIVE_PERK)
    assert ev["recommended"] and "Unicorn-Ziel erreicht" in ev["reason"]
    ev = reset.evaluate(_snap(100), "UNICORN_RUN", _EXPENSIVE_PERK)
    assert not ev["recommended"] and "Unicorn-Ziel offen" in ev["reason"]


def test_seed_run_reset_trigger():
    def _snap(void):
        return _with_prestige(make_snap(
            resources={"void": {"value": void, "max": 0, "rate": 0.1},
                       "catnip": {"value": 50000, "max": 60000, "rate": 20.0}},
            buildings={"chronosphere": {"val": 2,
                                        "prices": {"unobtainium": 100}}},
            kittens=110, max_kittens=110, catnip_field_base=40))
    # CS 2 → saveRatio 0.03: 40 Void → floor(1.2) = 1 Einheit überlebt.
    ev = reset.evaluate(_snap(40), "SEED_RUN", _EXPENSIVE_PERK)
    assert ev["recommended"] and "Seed-Basis erreicht" in ev["reason"]
    ev = reset.evaluate(_snap(5), "SEED_RUN", _EXPENSIVE_PERK)
    assert not ev["recommended"]


def test_positive_cs_run_reset_trigger():
    def _snap(uo):
        return _with_prestige(make_snap(
            resources={"unobtainium": {"value": uo, "max": 2 * uo + 1,
                                       "rate": 1.0}},
            buildings={"chronosphere": {"val": 2,
                                        "prices": {"unobtainium": 100}}}))
    # Carryover 300 > Wiederaufbau 144 → Dominanz (ohne Projektionsdaten
    # wäre rv None → Trigger allein entscheidet, Fallback ohne Daten):
    ev = reset.evaluate(_snap(10000), "POSITIVE_CS_RUN", _EXPENSIVE_PERK)
    assert ev["recommended"] and "Positive CS-Schleife" in ev["reason"]
    ev = reset.evaluate(_snap(1000), "POSITIVE_CS_RUN", _EXPENSIVE_PERK)
    assert not ev["recommended"]


# ============================================ #42 V(post) simuliert

def test_reset_value_vpost_simulated_vs_ramp():
    """Mit beobachteter Ankunftsrate simuliert V(post) den Neustart
    (Kurzsimulation, vPostMode "simuliert"); ohne Rate bleibt die
    lineare Rampe als Fallback (vPostMode "rampe")."""
    grow = make_snap(kittens=110, max_kittens=150,
                     resources={"catnip": {"value": 50000, "max": 60000,
                                           "rate": 20.0}},
                     catnip_field_base=40, kittens_per_sec=0.05)
    ev = reset.evaluate(_with_prestige(grow), "FIRST_RUN", None)
    assert ev["resetValue"]["vPostMode"] == "simuliert"
    # Post-Run erreicht 70 Kitten nicht im Vergleichsfenster → Weiterlaufen:
    assert not ev["recommended"]
    frozen = make_snap(kittens=110, max_kittens=110,
                       resources={"catnip": {"value": 50000, "max": 60000,
                                             "rate": 20.0}},
                       catnip_field_base=40)
    ev = reset.evaluate(_with_prestige(frozen), "FIRST_RUN", None)
    assert ev["resetValue"]["vPostMode"] == "rampe"
    assert ev["recommended"]


def test_paragon_production_ratio_matches_prestige_js():
    """Portierte Formel gegen prestige.js:523-534 / game.js getLimitedDR:
    100 Paragon → +100 % (unter der 75-%-Freigrenze des 2×-Limits);
    300 Paragon → 1.875 (Diminishing Returns); burnedParagon Kappe 1×."""
    assert reset.paragon_production_ratio(100) == pytest.approx(1.0)
    assert reset.paragon_production_ratio(300) == pytest.approx(1.875)
    assert reset.paragon_production_ratio(0, 50) == pytest.approx(0.5)
    # burned 300 bei Kappe 1×: 0.75 frei + (1−0.25/2.5)·0.25 = 0.975:
    assert reset.paragon_production_ratio(0, 300) == pytest.approx(0.975)


def test_reward_seconds_mapping():
    snap = make_snap(
        resources={"catnip": {"value": 100, "max": 5000, "rate": 10.0}},
        catnip_field_base=40.0)
    # Δ = 0.05 × 40 × 1.5 × 0.25 = 0.75; /10 × 1000 s Horizont = 75 s:
    assert challenge.reward_seconds(snap, "winterIsComing", 1000.0) == \
        pytest.approx(75.0)
    # pacifism: Δrate/rate = ratio exakt, nur bei laufender Produktion:
    asnap = make_snap(resources={"alicorn": {"value": 1, "max": 0,
                                             "rate": 0.01}})
    assert challenge.reward_seconds(asnap, "pacifism", 1000.0) == \
        pytest.approx(100.0)
    assert challenge.reward_seconds(make_snap(), "pacifism", 1000.0) is None
    # Nicht abbildbare Effekte → None (Aufrufer nutzt Referenzschätzung):
    assert challenge.reward_seconds(snap, "anarchy", 1000.0) is None
