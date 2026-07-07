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
    """Neuer Vertrag seit der Soll-Allokation (12.2): Bei einem reinen
    Science-Ziel ohne weitere bepreiste Bedürfnisse DARF der Woodcutter
    zum zweiten Scholar werden (schnellere Zielzeit) — aber die Verteilung
    muss danach STABIL sein: Ist Soll = Ist, wird nichts mehr verschoben
    (der alte Testname prüfte die alte Kein-Anfassen-Heuristik)."""
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
    shifts = [c for c in cands if c.action.id.startswith("shift:")]
    if shifts:   # Umschulung Richtung Ziel ist erlaubt …
        assert shifts[0].action.exec_spec["to"] == "scholar"
    # … aber im Soll-Zustand (2 Scholars) ist Ruhe:
    snap2 = make_snap(
        resources={"catnip": {"value": 3000, "max": 5000, "rate": 10},
                   "science": {"value": 0, "max": 250, "rate": 0.35}},
        buildings={"library": {"val": 1, "prices": {"wood": 40}}},
        techs={"calendar": {"researched": False, "prices": {"science": 30}}},
        jobs={"woodcutter": 0, "scholar": 2}, kittens=2, max_kittens=2,
        catnip_field_base=12,
    )
    cands2, _ = tactics.generate(snap2, meta.evaluate(snap2), safety.check(snap2))
    assert not any(c.action.id.startswith("shift:") for c in cands2)
