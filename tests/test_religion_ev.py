"""Tests der Religion-Endgame-Ökonomie (Spec 15.2–15.5, brain/religion.py):
TAP-Bilanz, Alicorn-/Tear-Grenzwertregeln, PactValue und Siphoning."""

import math

from player.brain import actions, meta, religion, safety, tactics
from tests.helpers import make_snap

ANACHRONOMANCY = {"name": "anachronomancy", "label": "Anachronomancy",
                  "researched": True, "unlocked": True,
                  "prices": [{"name": "paragon", "val": 125}]}


def _rel_upgrades(transcendence=True, apocrypha=True):
    ups = []
    if apocrypha:
        ups.append({"name": "apocripha", "label": "Apocrypha", "val": 1, "on": 1,
                    "unlocked": True, "noStackable": True, "prices": []})
    if transcendence:
        ups.append({"name": "transcendence", "label": "Transcendence", "val": 1,
                    "on": 1, "unlocked": True, "noStackable": True, "prices": []})
    return ups


def _with_perks(snap, perks):
    snap["prestige"]["perks"] = perks
    return snap


# ---------------------------------------------------------------- Preisformel

def test_transcend_price_formula_matches_reference():
    # totalPrice(t) = getInverseUnlimitedDR(e^t/10, 0.1) = 0.05·x·(x+1)
    # (religion.js:1655-1661 + game.js:5277):
    assert math.isclose(religion.transcend_total_price(0), 0.05 * 0.1 * 1.1)
    x1 = math.exp(1) / 10.0
    assert math.isclose(religion.transcend_total_price(1), 0.05 * x1 * (x1 + 1.0))
    assert math.isclose(
        religion.transcend_next_price(0),
        religion.transcend_total_price(1) - religion.transcend_total_price(0))
    # Inverse-Beziehung der DR-Funktionen (game.js:5270-5279):
    assert math.isclose(
        religion.unlimited_dr(religion.inverse_unlimited_dr(0.7, 0.1), 0.1), 0.7)


# ---------------------------------------------------------------- TAP (15.2)

def _tap_snap(worship=10_000.0, epiphany=0.1, faith_rate=50.0, faith_value=500.0,
              transcendence=True):
    return make_snap(
        resources={"faith": {"value": faith_value, "max": 200_000.0,
                             "rate": faith_rate}},
        jobs={"priest": 5}, kittens=5,
        religion={"worship": worship, "epiphany": epiphany,
                  "transcendenceTier": 0,
                  "upgrades": _rel_upgrades(transcendence=transcendence)},
    )


def test_transcend_value_worth_when_adore_gain_exceeds_price():
    # Tier 0→1 kostet ~0.0118 Epiphany; der Adore-Mehrgewinn (tt+2)²−(tt+1)²
    # = 3 · worship/1e6 · 1.01 übersteigt das ab worship ≈ 3887:
    tv = religion.transcend_value(_tap_snap(worship=10_000.0))
    assert tv["reachable"] and tv["worth"]
    assert tv["balance"] > 0
    assert math.isclose(tv["nextPrice"], religion.transcend_next_price(0),
                        abs_tol=1e-6)   # nextPrice ist auf 6 Stellen gerundet
    assert tv["recoveryS"] is not None


def test_transcend_value_not_worth_with_small_worship():
    tv = religion.transcend_value(_tap_snap(worship=2_000.0))
    assert tv["reachable"]
    assert not tv["worth"]
    assert tv["balance"] < 0
    assert "Bilanz" in tv["reason"]


def test_transcend_value_unreachable_without_epiphany_or_upgrade():
    tv = religion.transcend_value(_tap_snap(epiphany=0.005))  # < nextPrice
    assert not tv["reachable"] and not tv["worth"]
    tv = religion.transcend_value(_tap_snap(transcendence=False))
    assert not tv["reachable"]
    assert "Transcendence" in tv["reason"]


def test_transcend_value_blocked_by_worship_recovery_time():
    # Keine Faith-Produktion → Worship-Wiederanlauf unendlich → kein
    # Transcend trotz positiver Epiphany-Bilanz (Spec 15.2, Kriterium 3):
    tv = religion.transcend_value(_tap_snap(faith_rate=0.0, faith_value=0.0))
    assert tv["reachable"] and tv["balance"] > 0
    assert not tv["worth"]
    assert "Wiederanlauf" in tv["reason"]


def test_tap_plan_order_transcend_adore_praise():
    steps = religion.tap_plan(_tap_snap())
    assert [s["step"] for s in steps] == ["transcend", "adore", "praise"]
    # Der Adore-Schritt rechnet mit dem NEUEN Tier ((0+1+1)² = 4):
    adore = steps[1]
    assert math.isclose(adore["value"], 10_000 / 1e6 * 4 * 1.01, rel_tol=1e-6)
    # Ohne lohnenden Transcend beginnt der Plan mit Adore:
    steps = religion.tap_plan(_tap_snap(worship=2_000.0))
    assert [s["step"] for s in steps] == ["adore", "praise"]


def test_tap_plan_empty_without_religion_data():
    assert religion.tap_plan(make_snap()) == []


# ------------------------------------------------------- Alicorn/Tears (15.4)

def _alicorn_snap(alicorns=50.0, anachronomancy=True):
    snap = make_snap(
        resources={"alicorn": {"value": alicorns, "max": 0, "rate": 0.001}},
        religion={"tcRefineRatio": 0.0},
    )
    return _with_perks(snap, [ANACHRONOMANCY] if anachronomancy else [])


def test_alicorn_conversion_lambda_rule():
    lam = {"timeCrystal": 100.0, "alicorn": 1.0}
    due, det = religion.alicorn_conversion_due(_alicorn_snap(), lam)
    assert due and det["batches"] == 2
    assert det["gainS"] > det["keepS"]
    # Haltewert dominiert → keine Konvertierung:
    lam = {"timeCrystal": 1.0, "alicorn": 10.0}
    due, det = religion.alicorn_conversion_due(_alicorn_snap(), lam)
    assert not due and "halten" in det["reason"]
    # Ohne λ-Daten: konservativ halten:
    due, det = religion.alicorn_conversion_due(_alicorn_snap(), {})
    assert not due


def test_alicorn_conversion_requires_anachronomancy():
    # TC überleben den Reset ohne Anachronomancy nicht (game.js
    # _resetInternal) — Konvertierung gesperrt, selbst mit starkem λ_TC:
    lam = {"timeCrystal": 1000.0, "alicorn": 0.0}
    due, det = religion.alicorn_conversion_due(
        _alicorn_snap(anachronomancy=False), lam)
    assert not due
    assert "Anachronomancy" in det["reason"]
    # pre_reset mit Anachronomancy: Alicorns verfallen (persists: false) →
    # immer konvertieren, auch ohne λ:
    due, det = religion.alicorn_conversion_due(_alicorn_snap(), None,
                                               pre_reset=True)
    assert due and det["batches"] == 2


def _tears_snap(tears=25_000.0, sorrow=0.0, sorrow_max=20.0):
    return make_snap(
        resources={"tears": {"value": tears, "max": 0, "rate": 0},
                   "sorrow": {"value": sorrow, "max": sorrow_max, "rate": 0}},
        religion={"ziggurat": [{"name": "blackPyramid", "label": "Black Pyramid",
                                "val": 0, "on": 0, "unlocked": True,
                                "prices": []}]},
    )


def test_tears_refine_lambda_rule_and_cap():
    lam = {"sorrow": 50_000.0, "tears": 1.0}
    due, det = religion.tears_refine_due(_tears_snap(), lam)
    assert due and det["batches"] == 2
    # Sorrow am Cap (religion.js:2271-2276) → gesperrt:
    due, det = religion.tears_refine_due(_tears_snap(sorrow=20.0), lam)
    assert not due and "Cap" in det["reason"]
    # Headroom klemmt die Batchzahl:
    due, det = religion.tears_refine_due(_tears_snap(sorrow=19.0), lam)
    assert due and det["batches"] == 1
    # pre_reset: Tears persists:false, Sorrow persists:true → immer fällig:
    due, det = religion.tears_refine_due(_tears_snap(), None, pre_reset=True)
    assert due


# ---------------------------------------------------------------- Pacts (15.5)

def _pact_snap(pyramids=4, necrocorns=10.0, deficit=0.0, available=1,
               cleansing_on=0, relic=200.0, siphoning=False):
    return make_snap(
        resources={"relic": {"value": relic, "max": 0, "rate": 0}},
        religion={"transcendenceTier": 25,
                  "ziggurat": [{"name": "blackPyramid", "label": "Black Pyramid",
                                "val": pyramids, "on": pyramids,
                                "unlocked": True, "prices": []}]},
        pacts={"list": [{"name": "pactOfCleansing", "label": "Pact of Cleansing",
                         "val": cleansing_on, "on": cleansing_on,
                         "unlocked": True, "prices": {"relic": 100}}],
               "necrocorns": necrocorns, "necrocornDeficit": deficit,
               "pactsAvailable": available, "siphoning": siphoning},
    )


def test_pact_value_positive_with_pyramids_and_stock():
    pv = religion.pact_value(_pact_snap(), "pactOfCleansing",
                             lam={"necrocorn": 1.0}, horizon=3600.0)
    assert pv is not None and pv["positive"]
    # ΔBPU = 0.0005 · max(25−24,1) · 4 Pyramiden · 3600 s:
    assert math.isclose(pv["deltaBpuS"], 0.0005 * 1 * 4 * 3600.0, rel_tol=1e-6)
    # Upkeep = 0.0005/Tag · 1800 Tage · λ_necrocorn:
    assert math.isclose(pv["upkeepCostS"], 0.0005 * 1800.0 * 1.0, rel_tol=1e-6)
    assert pv["debtCostS"] == 0.0


def test_pact_value_negative_without_pyramid_or_with_default_necro_value():
    # Ohne Black Pyramid entfaltet der Pact keinen Nutzen (religion.js
    # cashPreDeficitEffects wirkt über die Pyramide):
    pv = religion.pact_value(_pact_snap(pyramids=0), "pactOfCleansing",
                             lam={"necrocorn": 1.0}, horizon=3600.0)
    assert pv is not None and not pv["positive"]
    # Ohne λ_necrocorn greift die konservative Referenzschätzung (1800 s)
    # und der Upkeep dominiert:
    pv = religion.pact_value(_pact_snap(), "pactOfCleansing", horizon=3600.0)
    assert pv is not None and not pv["positive"]


def test_pact_value_none_without_snapshot_data():
    assert religion.pact_value(make_snap(), "pactOfCleansing") is None
    # special-Pacts sind keine Kauf-Kandidaten:
    assert religion.pact_value(_pact_snap(), "payDebt") is None


def test_pact_value_debt_penalty():
    # Kein Necrocorn-Bestand + bestehende Schuld → prognostiziertes Defizit
    # drückt den Wert (getDebtPenaltyRatio ≈ 1 − deficit/50):
    pv = religion.pact_value(_pact_snap(necrocorns=0.0, deficit=45.0),
                             "pactOfCleansing", lam={"necrocorn": 1.0},
                             horizon=3600.0)
    assert pv is not None
    assert pv["debtCostS"] > 0
    assert not pv["positive"]


def test_siphoning_rule():
    # Große Schuld + laufende Pacts, Necrocorn-λ klein → Reduktion der
    # Schuldkosten dominiert → Siphoning AN:
    snap = _pact_snap(deficit=30.0, cleansing_on=2)
    due, det = religion.siphoning_due(snap, lam={"necrocorn": 0.01})
    assert due and det["reductionS"] > det["foregoneS"]
    # Mit teuren Necrocorns (Fallback-Referenzwert) bleibt Siphoning AUS:
    due, det = religion.siphoning_due(snap)
    assert not due
    # Ohne Daten: dokumentiert konservativ AUS:
    due, det = religion.siphoning_due(make_snap())
    assert not due and "konservativ AUS" in det["reason"]
    # Ohne Schuld kein Siphoning:
    due, det = religion.siphoning_due(_pact_snap(), lam={"necrocorn": 0.01})
    assert not due


# ---------------------------------------------------------- Aktionen/Kandidaten

def test_new_actions_are_irreversible():
    assert actions.transcend().atomicity == actions.IRREVERSIBLE
    assert actions.convert_alicorns(2).atomicity == actions.IRREVERSIBLE
    assert actions.refine_tears(1).atomicity == actions.IRREVERSIBLE
    assert actions.buy_pact("pactOfCleansing", "Pact of Cleansing",
                            [{"name": "relic", "val": 100}]
                            ).atomicity == actions.IRREVERSIBLE
    # Commit-Grenze braucht das Kostenmodell (G-06):
    assert actions.convert_alicorns(2).predicted["deltas"] == {"alicorn": -50.0}
    assert actions.refine_tears(3).predicted["deltas"] == {
        "tears": -30000.0, "sorrow": 3.0}


def test_religion_ev_candidates_wiring():
    snap = _pact_snap()
    snap["resources"].append({"name": "alicorn", "title": "alicorn",
                              "value": 50.0, "maxValue": 0, "craftable": False,
                              "unlocked": True, "perSec": 0.0})
    _with_perks(snap, [ANACHRONOMANCY])
    lam = {"necrocorn": 0.5, "timeCrystal": 100.0, "alicorn": 0.1}
    cands = []
    tactics._religion_ev_candidates(snap, cands, lam, 3600.0)
    by_id = {c.action.id: c for c in cands}
    # Pact-Kauf mit pactValue-Sekundenwert (SHADOW_INFO_KEYS):
    pact = by_id["pact:pactOfCleansing"]
    assert pact.components["pactValue"] > 0
    assert "pactValue" in tactics.SHADOW_INFO_KEYS
    # Alicorn-Konvertierung mit tapValue-Komponente:
    conv = by_id["religion:convertAlicorns"]
    assert conv.components["tapValue"] > 0
    assert "tapValue" in tactics.SHADOW_INFO_KEYS
    # Der Sekundenwert zählt NICHT additiv in den Score (nur Anzeige):
    assert pact.score < 2.0


def test_transcend_never_in_normal_cycle():
    # Spec 15.2: Transcend läuft ausschließlich über die Pre-Reset-
    # Transaktion — generate() liefert nie einen TRANSCEND-Kandidaten:
    snap = _tap_snap()
    cands, _ = tactics.generate(snap, meta.evaluate(snap), safety.check(snap))
    assert not any(c.action.type == "TRANSCEND" for c in cands)


def test_no_pact_candidates_without_data():
    snap = make_snap(resources={"relic": {"value": 500, "max": 0, "rate": 0}})
    cands, _ = tactics.generate(snap, meta.evaluate(snap), safety.check(snap))
    assert not any(c.action.type == "BUY_PACT" for c in cands)
