"""Tests der M3-Logik: Run-Typen, Reset-Bewertung, Metaphysics-Ziel."""

from player.brain import meta, reset
from tests.helpers import make_snap


def _with_prestige(snap, paragon=0, karma=0, perks=None):
    snap["prestige"] = {"paragon": paragon, "burnedParagon": 0, "karma": karma,
                        "perks": perks or []}
    return snap


def test_first_run_detection():
    snap = _with_prestige(make_snap())
    assert meta.determine_run(snap) == "FIRST_RUN"


def test_price_ratio_run_after_first_reset():
    snap = _with_prestige(make_snap(), paragon=40, karma=1)
    assert meta.determine_run(snap) == "PRICE_RATIO_RUN"
    target = meta.next_metaphysics_target(snap)
    assert target["name"] == "engeneering"   # sic — so heißt der Perk im Spiel


def test_metaphysics_order_progression():
    perks = [
        {"name": "engeneering", "label": "Engineering", "researched": True,
         "unlocked": True, "prices": [{"name": "paragon", "val": 5}]},
        {"name": "diplomacy", "label": "Diplomacy", "researched": True,
         "unlocked": True, "prices": [{"name": "paragon", "val": 5}]},
        {"name": "goldenRatio", "label": "Golden Ratio", "researched": False,
         "unlocked": True, "prices": [{"name": "paragon", "val": 50}]},
    ]
    snap = _with_prestige(make_snap(), paragon=60, karma=2, perks=perks)
    target = meta.next_metaphysics_target(snap)
    assert target["name"] == "goldenRatio"


def test_paragon_run_when_chain_complete():
    perks = [{"name": n, "label": n, "researched": True, "unlocked": True,
              "prices": [{"name": "paragon", "val": 1}]}
             for n in meta.METAPHYSICS_ORDER]
    snap = _with_prestige(make_snap(), paragon=100, karma=5, perks=perks)
    assert meta.determine_run(snap) == "PARAGON_RUN"


def test_first_reset_threshold():
    # 100 Kitten → Projektion 30 → noch kein Reset
    snap = _with_prestige(make_snap(kittens=100))
    ev = reset.evaluate(snap, "FIRST_RUN", None)
    assert not ev["recommended"]
    assert ev["projection"] == 30

    # 110 Kitten → Projektion 40 ≥ 35 → Reset empfohlen
    snap = _with_prestige(make_snap(kittens=110))
    ev = reset.evaluate(snap, "FIRST_RUN", None)
    assert ev["recommended"]


def test_price_ratio_reset_funds_next_perk():
    perk = {"name": "goldenRatio", "label": "Golden Ratio", "researched": False,
            "unlocked": True, "prices": [{"name": "paragon", "val": 50}]}
    # 10 Paragon vorhanden, Projektion 25 → 35 < 50 → kein Reset
    snap = _with_prestige(make_snap(kittens=95), paragon=10, karma=1)
    ev = reset.evaluate(snap, "PRICE_RATIO_RUN", perk)
    assert not ev["recommended"]

    # 30 Paragon vorhanden, Projektion 25 → 55 ≥ 50 → Reset
    snap = _with_prestige(make_snap(kittens=95), paragon=30, karma=1)
    ev = reset.evaluate(snap, "PRICE_RATIO_RUN", perk)
    assert ev["recommended"]

    # Projektion unter Mindestgewinn → kein Mini-Run-Reset
    snap = _with_prestige(make_snap(kittens=75), paragon=100, karma=1)
    ev = reset.evaluate(snap, "PRICE_RATIO_RUN", perk)
    assert ev["projection"] == 5
    assert not ev["recommended"]


def test_perk_milestone_becomes_target():
    perks = [{"name": "engeneering", "label": "Engineering", "researched": False,
              "unlocked": True, "prices": [{"name": "paragon", "val": 5}]}]
    snap = _with_prestige(
        make_snap(
            resources={"catnip": {"value": 40000, "max": 50000, "rate": 50},
                       "paragon": {"value": 40, "max": 0, "rate": 0}},
            techs={"metaphysics": {"researched": True, "prices": {"science": 100}},
                   "philosophy": {"researched": True, "prices": {"science": 100}}},
            jobs={"farmer": 5}, kittens=5, catnip_field_base=60,
        ),
        paragon=40, karma=1, perks=perks,
    )
    # Alle P0-Meilensteine künstlich als erledigt markieren ist aufwendig —
    # stattdessen direkt die Perk-Milestone-Erzeugung prüfen:
    ms = meta._perk_milestones(snap, perks[0])
    assert ms[-1].target == {"kind": "perk", "name": "engeneering"}

    # und das Taktik-Ziel „perk" liefert einen kaufbaren Kandidaten:
    from player.brain import safety, tactics
    from player.brain.meta import Milestone
    mview = meta.evaluate(snap)
    mview.active = ms[-1]
    cands, bn = tactics.generate(snap, mview, safety.check(snap))
    perk_cand = next(c for c in cands if c.action.id == "perk:engeneering")
    assert perk_cand.feasible
    assert perk_cand.action.irreversible
    assert perk_cand.action.exec_spec["panel"] == "Metaphysics"
