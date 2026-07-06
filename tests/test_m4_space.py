"""Tests der M4-Logik: Craft-Kaskade, Energie-Regel, Space-Ziele."""

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


def _base():
    return dict(jobs={"farmer": 5}, kittens=5, catnip_field_base=60)


def test_craft_cascade_descends_to_feasible_level():
    """Ziel braucht Blueprints; Compendia fehlen, Manuscripts machbar."""
    crafts = [
        {"name": "manuscript", "label": "Manuscript", "unlocked": True,
         "prices": [{"name": "parchment", "val": 25}, {"name": "culture", "val": 400}]},
        {"name": "compedium", "label": "Compendium", "unlocked": True,
         "prices": [{"name": "manuscript", "val": 50}, {"name": "science", "val": 10000}]},
        {"name": "blueprint", "label": "Blueprint", "unlocked": True,
         "prices": [{"name": "compedium", "val": 25}, {"name": "science", "val": 25000}]},
    ]
    snap = make_snap(
        resources={"catnip": {"value": 40000, "max": 50000, "rate": 50},
                   "science": {"value": 50000, "max": 60000, "rate": 100},
                   "parchment": {"value": 500, "max": 0, "rate": 1},
                   "culture": {"value": 5000, "max": 8000, "rate": 5},
                   "manuscript": {"value": 0, "max": 0, "rate": 0},
                   "compedium": {"value": 0, "max": 0, "rate": 0},
                   "blueprint": {"value": 0, "max": 0, "rate": 0}},
        techs={"electronics": {"researched": False, "unlocked": True,
                               "prices": {"science": 135000, "blueprint": 70}}},
        crafts=crafts, **_base(),
    )
    cands, bn = _generate(snap, {"kind": "research", "name": "electronics"})
    # Blueprint/Compendium nicht machbar, Manuscript schon → Kaskade liefert Manuscript:
    craft_ids = [c.action.id for c in cands if c.action.id.startswith("craft:")]
    assert "craft:manuscript" in craft_ids
    assert "craft:blueprint" not in craft_ids


def test_energy_producer_prioritized_on_deficit():
    snap = make_snap(
        resources={"catnip": {"value": 40000, "max": 50000, "rate": 50},
                   "wood": {"value": 5000, "max": 10000, "rate": 5},
                   "minerals": {"value": 5000, "max": 10000, "rate": 5},
                   "iron": {"value": 500, "max": 1000, "rate": 1}},
        buildings={"steamworks": {"val": 0, "prices": {"steel": 65, "gear": 20}},
                   "magneto": {"val": 0, "prices": {"alloy": 10, "gear": 5, "blueprint": 1}}},
        **_base(),
    )
    snap["resources"] += [
        {"name": "steel", "title": "steel", "value": 100, "maxValue": 0,
         "craftable": True, "unlocked": True, "perSec": 0},
        {"name": "gear", "title": "gear", "value": 50, "maxValue": 0,
         "craftable": True, "unlocked": True, "perSec": 0},
    ]
    snap["energy"] = {"prod": 2, "cons": 5}
    from player.state.derived import derive
    derive(snap)
    cands, _ = _generate(snap)
    sw = next(c for c in cands if c.action.id == "build:steamworks")
    assert sw.components.get("energy", 0) > 0


def test_space_program_target():
    snap = make_snap(
        resources={"catnip": {"value": 40000, "max": 50000, "rate": 50},
                   "starchart": {"value": 300, "max": 0, "rate": 0.1},
                   "science": {"value": 60000, "max": 100000, "rate": 100},
                   "oil": {"value": 2000, "max": 5000, "rate": 2}},
        **_base(),
    )
    snap["space"] = {"programs": [{
        "name": "orbitalLaunch", "label": "Orbital Launch", "val": 0, "unlocked": True,
        "prices": [{"name": "starchart", "val": 250}, {"name": "science", "val": 50000},
                   {"name": "oil", "val": 1500}],
    }], "planets": []}
    cands, bn = _generate(snap, {"kind": "space_program", "name": "orbitalLaunch"})
    launch = next(c for c in cands if c.action.id == "space:orbitalLaunch")
    assert launch.feasible
    assert launch.components.get("milestone", 0) > 0


def test_space_building_bottleneck_coupling():
    snap = make_snap(
        resources={"catnip": {"value": 40000, "max": 50000, "rate": 50},
                   "unobtainium": {"value": 0, "max": 150, "rate": 0},
                   "science": {"value": 200000, "max": 300000, "rate": 100},
                   "uranium": {"value": 500, "max": 1000, "rate": 1},
                   "alloy": {"value": 100, "max": 0, "rate": 0},
                   "concrate": {"value": 100, "max": 0, "rate": 0}},
        **_base(),
    )
    snap["space"] = {"programs": [], "planets": [{
        "name": "moon", "label": "Moon",
        "buildings": [{"name": "moonOutpost", "label": "Lunar Outpost", "val": 0,
                       "unlocked": True,
                       "prices": [{"name": "uranium", "val": 500}]}],
    }]}
    # Ziel braucht Unobtainium → Lunar Outpost liefert es → Engpass-Kopplung:
    cands, bn = _generate(snap, {"kind": "resource", "name": "unobtainium", "amount": 100})
    outpost = next(c for c in cands if c.action.id == "space_bld:moonOutpost")
    assert outpost.components.get("bottleneck", 0) > 0
