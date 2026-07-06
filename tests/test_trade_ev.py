"""Tests für EV-basiertes Trade-/Jagd-/Praise-Timing (Spec 14.1, 14.2, 15.1).

Spec-Gaps #8/#14: TradeValue als Erwartungswert über die Ergebnisverteilung
(Saison, Ships, Standing) und λ-basierte Sofort/Warten-Entscheidung für
Jagd und Praise. Fallbacks ohne λ-/races-Daten = Bestandsverhalten.
"""

import pytest

from player.brain import meta, safety, tactics
from player.brain.meta import Milestone
from tests.helpers import make_snap


def _generate(snap, target=None):
    sres = safety.check(snap)
    mview = meta.evaluate(snap)
    if target is not None:
        mview.active = Milestone("test", "Testziel", lambda s: False, target)
    cands, bn = tactics.generate(snap, mview, sres)
    return cands, bn


def _rich_food():
    return {"catnip": {"value": 40000, "max": 50000, "rate": 50}}


def _wood_goal_snap(races=None, **kw):
    """Snapshot mit Holz-Engpass am Hut-Ziel: λ_wood = 10 s/Einheit."""
    return make_snap(
        resources={**_rich_food(),
                   "gold": {"value": 100, "max": 200, "rate": 0.5},
                   "manpower": {"value": 400, "max": 1000, "rate": 1},
                   "minerals": {"value": 5000, "max": 10000, "rate": 10},
                   "wood": {"value": 10, "max": 5000, "rate": 0.1}},
        buildings={"hut": {"val": 2, "prices": {"wood": 4000}}},
        catnip_field_base=60, jobs={"farmer": 5}, kittens=5,
        races=races, **kw,
    )


LIZARDS_WOOD = {
    "name": "lizards", "title": "Lizards",
    "buys": [{"name": "minerals", "val": 1000}],
    "sells": [{"name": "wood", "value": 500, "chance": 100}],
}


# ================================================================ TradeValue

def test_trade_value_positive_for_bottleneck_supplier():
    # Engpass-liefernde Rasse mit λ: TradeValue > 0 → Kandidat mit Anzeige.
    snap = _wood_goal_snap(races=[LIZARDS_WOOD])
    cands, bn = _generate(snap, {"kind": "build", "name": "hut"})
    assert bn["resource"] == "wood"
    trade = next(c for c in cands if c.action.id == "trade:lizards")
    assert trade.components["tradeValue"] > 0
    assert trade.components.get("bottleneck") == 1.7
    # tradeValue ist reine Anzeige (SHADOW_INFO_KEYS) — Score bleibt fix:
    assert trade.score == pytest.approx(1.7)


def test_trade_value_negative_blocks_bottleneck_race():
    # Rasse liefert zwar den Engpass, aber viel zu wenig gegen zu teure
    # Ware (Catnip erbt λ über die Refine-Kaskade) → EV-Gate blockt den
    # Trade, den die alte Engpass-Regel noch gemacht hätte.
    race = {"name": "lizards", "title": "Lizards",
            "buys": [{"name": "catnip", "val": 10000}],
            "sells": [{"name": "wood", "value": 1, "chance": 10}]}
    snap = _wood_goal_snap(races=[race])
    cands, _ = _generate(snap, {"kind": "build", "name": "hut"})
    assert not any(c.action.id == "trade:lizards" for c in cands)


def test_trade_value_worthless_offer_no_candidate():
    # Angebot ohne λ-Wert (Ressource nicht zielrelevant), Kosten mit λ:
    # TradeValue negativ → kein Kandidat.
    race = {"name": "zebras", "title": "Zebras",
            "buys": [{"name": "catnip", "val": 5000}],
            "sells": [{"name": "titanium", "value": 1.5, "chance": 15}]}
    snap = _wood_goal_snap(races=[race])
    cands, _ = _generate(snap, {"kind": "build", "name": "hut"})
    assert not any(c.action.id == "trade:zebras" for c in cands)


def test_trade_positive_ev_without_bottleneck_supply():
    # NEU gegenüber der Light-Regel: positive EV reicht auch ohne
    # Engpass-Lieferung (hier: Catnip trägt λ über die Refine-Kaskade).
    race = {"name": "sharks", "title": "Sharks",
            "buys": [{"name": "minerals", "val": 50}],
            "sells": [{"name": "catnip", "value": 5000, "chance": 100}]}
    snap = _wood_goal_snap(races=[race])
    cands, _ = _generate(snap, {"kind": "build", "name": "hut"})
    trade = next(c for c in cands if c.action.id == "trade:sharks")
    assert trade.components.get("economy") == 0.9
    assert trade.components["tradeValue"] > 0


def test_trade_fallback_without_lambda_keeps_bottleneck_rule():
    # Ohne λ-Daten: Bestandsverhalten (fester Score 1.7, Engpass-Regel).
    snap = _wood_goal_snap(races=[LIZARDS_WOOD])
    bn = {"resource": "wood", "etaSeconds": 100, "missing": [], "affordable": False}
    cands = []
    tactics._trade_candidates(snap, bn, cands, None)
    trade = next(c for c in cands if c.action.id == "trade:lizards")
    assert trade.components == {"bottleneck": 1.7}
    assert trade.score == pytest.approx(1.7)
    # … und ohne Engpass-Lieferung kein Trade:
    cands = []
    tactics._trade_candidates(snap, {"resource": "iron"}, cands, None)
    assert not any(c.action.id.startswith("trade:") for c in cands)


# ------------------------------------------------- Monotonie der EV-Faktoren

LAM_WOOD = {"wood": 10.0}


def _seasonal_race():
    return {"name": "lizards", "title": "Lizards", "buys": [],
            "sells": [{"name": "wood", "value": 500, "chance": 100,
                       "seasons": {"spring": 0.5, "summer": 0.0,
                                   "autumn": 0.0, "winter": -0.5}}]}


def test_trade_value_season_monotonic():
    race = _seasonal_race()
    spring = _wood_goal_snap(races=[race], season="spring")
    winter = _wood_goal_snap(races=[race], season="winter")
    ev_spring = tactics._trade_value(spring, race, spring["diplomacy"], LAM_WOOD)
    ev_winter = tactics._trade_value(winter, race, winter["diplomacy"], LAM_WOOD)
    assert ev_spring > ev_winter > 0


def test_trade_value_ship_bonus_monotonic():
    # tradeRatio aus dem Snapshot erhöht die Erfolgsmenge (+1 %/Schiff, 1.5.0.2):
    snap0 = _wood_goal_snap(races=[LIZARDS_WOOD], trade_ratio=0.0)
    snap1 = _wood_goal_snap(races=[LIZARDS_WOOD], trade_ratio=0.5)
    ev0 = tactics._trade_value(snap0, LIZARDS_WOOD, snap0["diplomacy"], LAM_WOOD)
    ev1 = tactics._trade_value(snap1, LIZARDS_WOOD, snap1["diplomacy"], LAM_WOOD)
    assert ev1 > ev0
    # Fallback ohne tradeRatio-Feld: +1 % pro Trade-Ship-Ressource.
    snap_ships = _wood_goal_snap(races=[LIZARDS_WOOD])
    snap_ships["resources"].append(
        {"name": "ship", "title": "Ship", "value": 50, "maxValue": 0,
         "craftable": True, "unlocked": True, "perSec": 0.0})
    del snap_ships["diplomacy"]["tradeRatio"]
    ev_ships = tactics._trade_value(snap_ships, LIZARDS_WOOD,
                                    snap_ships["diplomacy"], LAM_WOOD)
    assert ev_ships == pytest.approx(ev0 * 1.5, rel=1e-6)


def test_trade_value_standing_monotonic():
    snap = _wood_goal_snap(races=[])
    hostile_lo = dict(LIZARDS_WOOD, attitude="hostile", standing=0.2)
    hostile_hi = dict(LIZARDS_WOOD, attitude="hostile", standing=0.8)
    neutral = dict(LIZARDS_WOOD)
    friendly = dict(LIZARDS_WOOD, attitude="friendly", standing=0.5)
    diplo = snap["diplomacy"]
    ev = {k: tactics._trade_value(snap, r, diplo, LAM_WOOD)
          for k, r in [("h_lo", hostile_lo), ("h_hi", hostile_hi),
                       ("neutral", neutral), ("friendly", friendly)]}
    # Hostile: Erfolgswahrscheinlichkeit < 1 senkt den EV monoton:
    assert ev["h_lo"] < ev["h_hi"] < ev["neutral"]
    # Friendly: Bonus-Trades (×1.25) heben den EV über neutral:
    assert ev["friendly"] > ev["neutral"]


# ================================================================ Jagd-EV

def test_hunt_now_when_loot_serves_goal():
    # Ziel braucht Furs (λ_furs > 0): EV(sofort) > Batch-Vorteil → jagen,
    # obwohl der 85-%-Füllstand weit entfernt ist.
    snap = make_snap(
        resources={**_rich_food(),
                   "manpower": {"value": 300, "max": 1000, "rate": 0.5}},
        catnip_field_base=60, jobs={"farmer": 5, "hunter": 1}, kittens=6,
    )
    cands, _ = _generate(snap, {"kind": "resource", "name": "furs", "amount": 100})
    hunt = next(c for c in cands if c.action.id == "hunt:all")
    assert hunt.components["huntValue"] > 0
    assert hunt.score == pytest.approx(1.3)


def test_hunt_waits_without_cap_pressure_or_loot_value():
    # λ vorhanden, aber Beute zielirrelevant und Cap fern → warten (Batch).
    snap = _wood_goal_snap(races=None)
    cands, _ = _generate(snap, {"kind": "build", "name": "hut"})
    assert not any(c.action.id == "hunt:all" for c in cands)


def test_hunt_now_on_cap_pressure_with_lambda():
    # Cap-Zeit unter dem Entscheidungspuffer (60 s) → sofort jagen,
    # obwohl der Füllstand unter 85 % liegt.
    snap = make_snap(
        resources={**_rich_food(),
                   "manpower": {"value": 400, "max": 1000, "rate": 20},
                   "wood": {"value": 10, "max": 5000, "rate": 0.1}},
        buildings={"hut": {"val": 2, "prices": {"wood": 4000}}},
        catnip_field_base=60, jobs={"farmer": 5, "hunter": 1}, kittens=6,
    )
    cands, _ = _generate(snap, {"kind": "build", "name": "hut"})
    hunt = next(c for c in cands if c.action.id == "hunt:all")
    assert hunt.components.get("capLoss") == 1.5


def test_hunt_fallback_without_lambda():
    # Bestandsverhalten ohne λ: 85-%-Schwelle entscheidet.
    def snap_with(mp_value):
        return make_snap(
            resources={**_rich_food(),
                       "manpower": {"value": mp_value, "max": 1000, "rate": 1}},
            catnip_field_base=60, jobs={"farmer": 5, "hunter": 1}, kittens=6,
        )
    cands = []
    tactics._hunt_candidate(snap_with(900), cands, None)
    assert any(c.action.id == "hunt:all" for c in cands)
    cands = []
    tactics._hunt_candidate(snap_with(500), cands, None)
    assert not any(c.action.id == "hunt:all" for c in cands)


# ================================================================ Praise-EV

def test_praise_on_cap_pressure_with_lambda():
    # λ da, Faith zielirrelevant, Cap-Zeit < Puffer → Praise vor der
    # 95-%-Schwelle (verhindert Cap-Verlust der Faith-Produktion).
    snap = make_snap(
        resources={**_rich_food(),
                   "faith": {"value": 500, "max": 1000, "rate": 20},
                   "wood": {"value": 10, "max": 5000, "rate": 0.1}},
        buildings={"hut": {"val": 2, "prices": {"wood": 4000}}},
        catnip_field_base=60, jobs={"farmer": 5}, kittens=5,
    )
    cands, _ = _generate(snap, {"kind": "build", "name": "hut"})
    assert any(c.action.id == "praise:sun" for c in cands)

    # Cap fern (langsame Rate) → kein Praise unter 95 %:
    snap = make_snap(
        resources={**_rich_food(),
                   "faith": {"value": 500, "max": 1000, "rate": 0.1},
                   "wood": {"value": 10, "max": 5000, "rate": 0.1}},
        buildings={"hut": {"val": 2, "prices": {"wood": 4000}}},
        catnip_field_base=60, jobs={"farmer": 5}, kittens=5,
    )
    cands, _ = _generate(snap, {"kind": "build", "name": "hut"})
    assert not any(c.action.id == "praise:sun" for c in cands)


def test_praise_saving_rule_survives_ev_path():
    # Sparregel hat absoluten Vorrang: erreichbares Religion-Upgrade
    # blockiert Praise auch bei Cap-Druck MIT λ-Daten.
    snap = make_snap(
        resources={**_rich_food(),
                   "faith": {"value": 990, "max": 1000, "rate": 20},
                   "wood": {"value": 10, "max": 5000, "rate": 0.1}},
        buildings={"hut": {"val": 2, "prices": {"wood": 4000}}},
        catnip_field_base=60, jobs={"farmer": 5}, kittens=5,
    )
    snap["religion"]["upgrades"] = [{
        "name": "solarRevolution", "label": "Solar Revolution",
        "unlocked": True, "noStackable": True, "on": 0, "val": 0,
        "prices": [{"name": "faith", "val": 800}],
    }]
    cands, _ = _generate(snap, {"kind": "build", "name": "hut"})
    assert not any(c.action.id == "praise:sun" for c in cands)


def test_praise_holds_when_goal_needs_faith():
    # Ziel braucht die Faith direkt (λ_faith > 0) und der Pool regeneriert
    # langsam → Halten wertvoller als der integrierte Produktionsgewinn.
    snap = make_snap(
        resources={**_rich_food(),
                   "faith": {"value": 950, "max": 1000, "rate": 0.01}},
        catnip_field_base=60, jobs={"farmer": 5}, kittens=5,
    )
    cands, _ = _generate(snap, {"kind": "resource", "name": "faith", "amount": 990})
    assert not any(c.action.id == "praise:sun" for c in cands)


def test_praise_when_pool_regenerates_fast():
    # Schnelle Regeneration: Produktionsgewinn über den Horizont schlägt
    # den λ-Wert des kleinen Bestands → Praise mit praiseValue-Anzeige.
    snap = make_snap(
        resources={**_rich_food(),
                   "faith": {"value": 96, "max": 100, "rate": 5}},
        catnip_field_base=60, jobs={"farmer": 5}, kittens=5,
    )
    cands, _ = _generate(snap, {"kind": "resource", "name": "faith", "amount": 99})
    praise = next(c for c in cands if c.action.id == "praise:sun")
    assert praise.components["praiseValue"] > 0
    assert praise.score == pytest.approx(1.5)


def test_praise_fallback_without_lambda():
    # Bestandsverhalten ohne λ: 95-%-Schwelle.
    snap = make_snap(
        resources={**_rich_food(), "faith": {"value": 98, "max": 100, "rate": 0.5}},
        catnip_field_base=60, jobs={"farmer": 5}, kittens=5,
    )
    cands = []
    tactics._praise_candidate(snap, cands, None, None)
    assert any(c.action.id == "praise:sun" for c in cands)
    snap = make_snap(
        resources={**_rich_food(), "faith": {"value": 50, "max": 100, "rate": 0.5}},
        catnip_field_base=60, jobs={"farmer": 5}, kittens=5,
    )
    cands = []
    tactics._praise_candidate(snap, cands, None, None)
    assert not any(c.action.id == "praise:sun" for c in cands)
