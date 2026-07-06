"""Tests der M2-Kandidaten: Handel, Kundschafter, Praise, Festival."""

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


def test_trade_fires_on_bottleneck_race():
    snap = make_snap(
        resources={**_rich_food(),
                   "gold": {"value": 100, "max": 200, "rate": 0.5},
                   "manpower": {"value": 400, "max": 500, "rate": 1},
                   "minerals": {"value": 5000, "max": 10000, "rate": 10},
                   "wood": {"value": 10, "max": 5000, "rate": 0.1}},
        buildings={"hut": {"val": 2, "prices": {"wood": 4000}}},
        catnip_field_base=60, jobs={"farmer": 5}, kittens=5,
    )
    snap["diplomacy"] = {"undiscovered": True, "races": [{
        "name": "lizards", "title": "Lizards",
        "buys": [{"name": "minerals", "val": 1000}],
        "sells": [{"name": "wood", "value": 500, "chance": 100}],
    }]}
    cands, bn = _generate(snap, {"kind": "build", "name": "hut"})
    assert bn["resource"] == "wood"
    trade = next(c for c in cands if c.action.id == "trade:lizards")
    assert trade.components.get("bottleneck", 0) > 0
    assert trade.action.batch >= 1


def test_no_trade_without_inputs():
    snap = make_snap(
        resources={**_rich_food(),
                   "gold": {"value": 5, "max": 200, "rate": 0.5},   # zu wenig Gold
                   "manpower": {"value": 400, "max": 500, "rate": 1},
                   "wood": {"value": 10, "max": 5000, "rate": 0.1}},
        buildings={"hut": {"val": 2, "prices": {"wood": 4000}}},
        catnip_field_base=60, jobs={"farmer": 5}, kittens=5,
    )
    snap["diplomacy"] = {"undiscovered": False, "races": [{
        "name": "lizards", "title": "Lizards",
        "buys": [{"name": "minerals", "val": 1000}],
        "sells": [{"name": "wood", "value": 500, "chance": 100}],
    }]}
    cands, _ = _generate(snap, {"kind": "build", "name": "hut"})
    assert not any(c.action.id == "trade:lizards" for c in cands)


def test_explore_only_after_first_race():
    # Vor dem ersten Emissär (races leer): Kundschafter wären verschwendet.
    snap = make_snap(
        resources={**_rich_food(), "manpower": {"value": 1200, "max": 1500, "rate": 2}},
        catnip_field_base=60, jobs={"farmer": 5}, kittens=5,
    )
    snap["diplomacy"] = {"undiscovered": True, "races": []}
    cands, _ = _generate(snap)
    assert not any(c.action.id == "explore:races" for c in cands)

    # Nach dem ersten Partner: weitere Rassen aktiv suchen.
    snap["diplomacy"] = {"undiscovered": True, "races": [{
        "name": "lizards", "title": "Lizards", "buys": [], "sells": []}]}
    cands, _ = _generate(snap)
    assert any(c.action.id == "explore:races" for c in cands)


def test_praise_near_faith_cap():
    snap = make_snap(
        resources={**_rich_food(), "faith": {"value": 98, "max": 100, "rate": 0.5}},
        catnip_field_base=60, jobs={"farmer": 5}, kittens=5,
    )
    cands, _ = _generate(snap)
    assert any(c.action.id == "praise:sun" for c in cands)

    # unter 95 %: kein Praise
    snap = make_snap(
        resources={**_rich_food(), "faith": {"value": 50, "max": 100, "rate": 0.5}},
        catnip_field_base=60, jobs={"farmer": 5}, kittens=5,
    )
    cands, _ = _generate(snap)
    assert not any(c.action.id == "praise:sun" for c in cands)


def test_festival_when_affordable_and_drama():
    snap = make_snap(
        resources={**_rich_food(),
                   "manpower": {"value": 2000, "max": 3000, "rate": 2},
                   "culture": {"value": 6000, "max": 10000, "rate": 5},
                   "parchment": {"value": 3000, "max": 0, "rate": 0}},
        techs={"drama": {"researched": True, "prices": {"science": 250}}},
        catnip_field_base=60, jobs={"farmer": 5}, kittens=5,
    )
    cands, _ = _generate(snap)
    fest = next(c for c in cands if c.action.id == "festival:hold")
    assert fest.components.get("happiness", 0) > 0

    # Festival läuft bereits → kein Kandidat
    snap["calendar"]["festivalDays"] = 100
    cands, _ = _generate(snap)
    assert not any(c.action.id == "festival:hold" for c in cands)
