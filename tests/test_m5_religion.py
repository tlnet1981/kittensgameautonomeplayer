"""Tests der M5-Logik: Religion-Upgrades, Unicorn-Kette, Solar-Revolution-Ziel."""

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


def _religion(**kw):
    rel = {
        "worship": 0, "epiphany": 0, "transcendenceTier": 0,
        "upgrades": [], "ziggurat": [],
    }
    rel.update(kw)
    return rel


def test_solar_revolution_prioritized():
    snap = make_snap(
        resources={"catnip": {"value": 40000, "max": 50000, "rate": 50},
                   "faith": {"value": 900, "max": 1000, "rate": 1}},
        **_base(),
    )
    snap["religion"] = _religion(upgrades=[
        {"name": "solarRevolution", "label": "Solar Revolution", "val": 0, "on": 0,
         "unlocked": True, "noStackable": True,
         "prices": [{"name": "faith", "val": 750}]},
        {"name": "scholasticism", "label": "Scholasticism", "val": 0, "on": 0,
         "unlocked": True, "noStackable": True,
         "prices": [{"name": "faith", "val": 250}]},
    ])
    cands, _ = _generate(snap)
    sr = next(c for c in cands if c.action.id == "religion:solarRevolution")
    other = next(c for c in cands if c.action.id == "religion:scholasticism")
    assert sr.components.get("unlock", 0) == 2.0
    assert sr.score > other.score


def test_bought_upgrade_not_offered_again():
    snap = make_snap(
        resources={"catnip": {"value": 40000, "max": 50000, "rate": 50},
                   "faith": {"value": 900, "max": 1000, "rate": 1}},
        **_base(),
    )
    snap["religion"] = _religion(upgrades=[
        {"name": "solarRevolution", "label": "Solar Revolution", "val": 1, "on": 1,
         "unlocked": True, "noStackable": True,
         "prices": [{"name": "faith", "val": 750}]},
    ])
    cands, _ = _generate(snap)
    assert not any(c.action.id == "religion:solarRevolution" for c in cands)


def test_sacrifice_unicorns_with_ziggurat():
    snap = make_snap(
        resources={"catnip": {"value": 40000, "max": 50000, "rate": 50},
                   "unicorns": {"value": 3000, "max": 0, "rate": 1}},
        buildings={"ziggurat": {"val": 1, "prices": {"megalith": 50}}},
        **_base(),
    )
    snap["religion"] = _religion()
    cands, _ = _generate(snap)
    assert any(c.action.id == "religion:sacrificeUnicorns" for c in cands)

    # ohne Ziggurat: kein Opfern
    snap = make_snap(
        resources={"catnip": {"value": 40000, "max": 50000, "rate": 50},
                   "unicorns": {"value": 3000, "max": 0, "rate": 1}},
        **_base(),
    )
    snap["religion"] = _religion()
    cands, _ = _generate(snap)
    assert not any(c.action.id == "religion:sacrificeUnicorns" for c in cands)


def test_solar_revolution_milestone_target():
    snap = make_snap(
        resources={"catnip": {"value": 40000, "max": 50000, "rate": 50},
                   "faith": {"value": 100, "max": 1000, "rate": 0.5}},
        buildings={"temple": {"val": 1, "prices": {"gold": 50}}},
        techs={"theology": {"researched": True, "prices": {"science": 20000}}},
        **_base(),
    )
    snap["religion"] = _religion(upgrades=[
        {"name": "solarRevolution", "label": "Solar Revolution", "val": 0, "on": 0,
         "unlocked": True, "noStackable": True,
         "prices": [{"name": "faith", "val": 750}]},
    ])
    mview = meta.evaluate(snap)
    labels = {m["id"]: m["state"] for m in mview.milestones}
    assert "solar_revolution" in labels
    # Ziel-Art religion_upgrade liefert Preise → Faith wird Engpass:
    cands, bn = _generate(snap, {"kind": "religion_upgrade", "name": "solarRevolution"})
    assert bn["resource"] == "faith"
