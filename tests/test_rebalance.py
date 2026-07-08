"""Regressionstest für den dritten Live-Deadlock: Engpass-Job unbesetzt,
keine freien Kitten → lokale Tauschoperation (Spec 12.2 Schritt 7)."""

from player.brain import meta, safety, tactics
from tests.helpers import make_snap


def test_rebalance_to_empty_bottleneck_job():
    # Beide Kitten sind Woodcutter, Ziel Calendar braucht Science, scholar = 0.
    snap = make_snap(
        resources={"catnip": {"value": 3000, "max": 5000, "rate": 10},
                   "wood": {"value": 100, "max": 200, "rate": 0.4},
                   "science": {"value": 0, "max": 250, "rate": 0}},
        buildings={"field": {"val": 20, "prices": {"catnip": 100}},
                   "hut": {"val": 1, "prices": {"wood": 10}},
                   "library": {"val": 1, "prices": {"wood": 40}}},
        techs={"calendar": {"researched": False, "prices": {"science": 30}}},
        jobs={"woodcutter": 2, "scholar": 0}, kittens=2, max_kittens=2,
        catnip_field_base=12,
    )
    sres = safety.check(snap)
    mview = meta.evaluate(snap)
    assert mview.active.id == "calendar"
    cands, bn = tactics.generate(snap, mview, sres)
    assert bn["resource"] == "science"
    shift = next(c for c in cands if c.action.id.startswith("shift:"))
    assert shift.action.exec_spec["from"] == "woodcutter"
    assert shift.action.exec_spec["to"] == "scholar"


def test_rebalance_converges_and_does_not_churn():
    """Vertrag der Soll-Allokation (12.2) seit dem Pfad-Vektor: Die
    Allokation kennt neben dem Science-Ziel auch die Pfad-Ressourcen
    (Wood für Mine/Housing) — eine tote Pfad-Ressource darf ein Kitten
    bekommen (Live-Fund „nie Miner/Hunter"). Entscheidend ist die
    STABILITÄT: Ist Soll = Ist, wird nichts mehr verschoben."""
    snap = make_snap(
        resources={"catnip": {"value": 3000, "max": 5000, "rate": 10},
                   "science": {"value": 0, "max": 250, "rate": 0.1}},
        buildings={"library": {"val": 1, "prices": {"wood": 40}}},
        techs={"calendar": {"researched": False, "prices": {"science": 30}}},
        jobs={"woodcutter": 1, "scholar": 1}, kittens=2, max_kittens=2,
        catnip_field_base=12,
    )
    sres = safety.check(snap)
    mview = meta.evaluate(snap)
    cands, _ = tactics.generate(snap, mview, sres)
    # Scholar (Science, Rang nah) + Woodcutter (tote Pfad-Ressource Wood)
    # ist der Fixpunkt — hier wird NICHTS verschoben:
    assert not any(c.action.id.startswith("shift:") for c in cands)
    # Aus der Monokultur (2 Scholars) genau EINE Bewegung zum Fixpunkt:
    snap2 = make_snap(
        resources={"catnip": {"value": 3000, "max": 5000, "rate": 10},
                   "science": {"value": 0, "max": 250, "rate": 0.35}},
        buildings={"library": {"val": 1, "prices": {"wood": 40}}},
        techs={"calendar": {"researched": False, "prices": {"science": 30}}},
        jobs={"woodcutter": 0, "scholar": 2}, kittens=2, max_kittens=2,
        catnip_field_base=12,
    )
    cands2, _ = tactics.generate(snap2, meta.evaluate(snap2), safety.check(snap2))
    shifts2 = [c for c in cands2 if c.action.id.startswith("shift:")]
    assert len(shifts2) == 1
    assert shifts2[0].action.exec_spec["from"] == "scholar"
    assert shifts2[0].action.exec_spec["to"] == "woodcutter"
