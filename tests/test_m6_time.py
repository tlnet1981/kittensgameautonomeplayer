"""Tests der M6-Logik: Shatter-Regel, TC-Schutz-Gate, Leviathan-Handel."""

from player.brain import meta, reset, safety, tactics
from tests.helpers import make_snap


def _generate(snap):
    sres = safety.check(snap)
    mview = meta.evaluate(snap)
    cands, bn = tactics.generate(snap, mview, sres)
    return cands, bn


def _base():
    return dict(jobs={"farmer": 5}, kittens=5, catnip_field_base=60)


def _time(tc=0, rr=0, heat=0, heat_max=100):
    return {
        "heat": heat, "heatMax": heat_max, "flux": 0,
        "chronoforge": [{"name": "ressourceRetrieval", "label": "Resource Retrieval",
                         "val": rr, "unlocked": rr > 0,
                         "prices": [{"name": "timeCrystal", "val": 1000}]}],
        "voidspace": [],
    }


def test_shatter_requires_rr_and_heat_headroom():
    snap = make_snap(
        resources={"catnip": {"value": 40000, "max": 50000, "rate": 50},
                   "timeCrystal": {"value": 30, "max": 0, "rate": 0}},
        **_base(),
    )
    # Ohne RR: kein Shatter
    snap["time"] = _time(rr=0)
    cands, _ = _generate(snap)
    assert not any(c.action.id == "time:shatter" for c in cands)

    # Mit RR und Heat-Spielraum: Shatter mit Heat-begrenztem Batch.
    # Seit dem Pfad-λ (#34) liefert der Zyklus fast immer λ-Daten → die
    # λ-Regel B wählt den Batch bis zur Heat-Grenze (100/10 = 10) statt
    # der konservativen Regel C (≤ 5 ohne λ).
    snap["time"] = _time(rr=2, heat=0, heat_max=100)
    cands, _ = _generate(snap)
    sh = next(c for c in cands if c.action.id == "time:shatter")
    assert 1 <= sh.action.batch <= 10

    # Heat voll: kein Shatter
    snap["time"] = _time(rr=2, heat=95, heat_max=100)
    cands, _ = _generate(snap)
    assert not any(c.action.id == "time:shatter" for c in cands)


def test_tc_protection_gate_blocks_reset():
    # 110 Kitten → Reset wäre empfohlen, aber 10 TC ohne Anachronomancy:
    snap = make_snap(kittens=110,
                     resources={"timeCrystal": {"value": 10, "max": 0, "rate": 0}})
    snap["prestige"] = {"paragon": 0, "burnedParagon": 0, "karma": 0, "perks": []}
    ev = reset.evaluate(snap, "FIRST_RUN", None)
    assert not ev["recommended"]
    gate = next(g for g in ev["gates"] if "TC-Schutz" in g["name"])
    assert not gate["pass"]

    # Mit Anachronomancy: Reset wieder frei
    snap["prestige"]["perks"] = [{"name": "anachronomancy", "label": "Anachronomancy",
                                  "researched": True, "unlocked": True,
                                  "prices": [{"name": "paragon", "val": 125}]}]
    ev = reset.evaluate(snap, "FIRST_RUN", None)
    assert ev["recommended"]


def test_leviathan_trade_always_valuable():
    snap = make_snap(
        resources={"catnip": {"value": 40000, "max": 50000, "rate": 50},
                   "manpower": {"value": 500, "max": 1000, "rate": 2},
                   "gold": {"value": 200, "max": 500, "rate": 1},
                   "unobtainium": {"value": 5000, "max": 10000, "rate": 1}},
        **_base(),
    )
    snap["diplomacy"] = {"undiscovered": False, "races": [{
        "name": "leviathans", "title": "Leviathans",
        "buys": [{"name": "unobtainium", "val": 5000}],
        "sells": [{"name": "timeCrystal", "value": 0.25, "chance": 98}],
    }]}
    cands, _ = _generate(snap)
    lev = next(c for c in cands if c.action.id == "trade:leviathans")
    assert lev.score >= 1.5


def test_chronoforge_and_cryochamber_candidates():
    snap = make_snap(
        resources={"catnip": {"value": 40000, "max": 50000, "rate": 50},
                   "timeCrystal": {"value": 2000, "max": 0, "rate": 0},
                   "void": {"value": 200, "max": 0, "rate": 0},
                   "karma": {"value": 50, "max": 0, "rate": 0}},
        **_base(),
    )
    snap["time"] = {
        "heat": 0, "heatMax": 100, "flux": 0,
        "chronoforge": [{"name": "ressourceRetrieval", "label": "Resource Retrieval",
                         "val": 0, "unlocked": True,
                         "prices": [{"name": "timeCrystal", "val": 1000}]}],
        "voidspace": [{"name": "cryochambers", "label": "Cryochamber",
                       "val": 0, "unlocked": True,
                       "prices": [{"name": "void", "val": 100},
                                  {"name": "timeCrystal", "val": 2},
                                  {"name": "karma", "val": 1}]}],
    }
    cands, _ = _generate(snap)
    assert any(c.action.id == "chronoforge:ressourceRetrieval" for c in cands)
    assert any(c.action.id == "voidspace:cryochambers" for c in cands)
