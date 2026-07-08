"""Tests des Makro-&-Reset-Pakets (#38+#39+#42, docs/spec-gaps.md):
Restzeiten projiziert statt Konstanten (8.3/18.2), Payback gegen den
geplanten Reset (10.4/6.4), Reset-Trigger je Run-Typ + V(post) (20.1/20.2)."""

import math

import pytest

from player.brain import challenge, chrono, meta, simulate
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
