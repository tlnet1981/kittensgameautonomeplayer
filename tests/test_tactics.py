"""Tests des taktischen Optimierers (brain/tactics.py) — inkl. der beiden
im Live-Test gefundenen Deadlock-Szenarien."""

from player.brain import meta, safety, tactics
from tests.helpers import make_snap


def _generate(snap):
    sres = safety.check(snap)
    mview = meta.evaluate(snap)
    cands, bn = tactics.generate(snap, mview, sres)
    selected = next(c for c in cands if c.feasible)
    return cands, bn, selected, mview


def test_first_action_is_gathering():
    """Frisches Spiel: keine Felder, kein Catnip → sammeln."""
    snap = make_snap(resources={"catnip": {"value": 0, "max": 5000, "rate": 0}},
                     buildings={"field": {"val": 0, "prices": {"catnip": 10}}})
    cands, bn, selected, _ = _generate(snap)
    assert selected.action.id == "gather:catnip"


def test_milestone_build_selected_when_affordable():
    snap = make_snap(resources={"catnip": {"value": 100, "max": 5000, "rate": 1}},
                     buildings={"field": {"val": 0, "prices": {"catnip": 10}}})
    cands, bn, selected, mv = _generate(snap)
    assert mv.active.id == "field_1"
    assert selected.action.id == "build:field"
    assert selected.components.get("milestone", 0) > 0


def test_wood_deadlock_resolved_by_refine():
    """Deadlock 1 aus dem Live-Test: Holz nur über Refine erreichbar."""
    snap = make_snap(
        resources={"catnip": {"value": 300, "max": 5000, "rate": 10},
                   "wood": {"value": 1, "max": 200, "rate": 0}},
        buildings={"field": {"val": 15, "prices": {"catnip": 60}}},
        catnip_field_base=10,
    )
    cands, bn, selected, mv = _generate(snap)
    assert mv.active.id == "wood_first"
    assert bn["resource"] == "wood"
    assert selected.action.id == "refine:catnip"


def test_kitten_bootstrap_banking_mode():
    """Kitten-Bootstrap (0 Kitten, Job-Ressource als Engpass): Felder, die
    die Projektion verbessern, sind Engpasslöser; Catnip ist reserviert
    (generische Catnip-Käufe bestraft); Refine läuft nur fürs Housing-Holz."""
    snap = make_snap(
        resources={"catnip": {"value": 300, "max": 5000, "rate": 10},
                   "wood": {"value": 1, "max": 200, "rate": 0}},
        buildings={"field": {"val": 15, "prices": {"catnip": 60}},
                   "hut": {"val": 0, "prices": {"wood": 5}},
                   "aqueduct": {"val": 0, "prices": {"catnip": 75}}},
        catnip_field_base=10, kittens=0, max_kittens=0,
    )
    cands, bn, selected, _ = _generate(snap)
    assert bn["resource"] == "wood"   # wood ist Job-Ressource → Banking aktiv
    field = next(c for c in cands if c.action.id == "build:field")
    assert field.components.get("bottleneck", 0) > 0   # verbessert die Bank
    # Refine-Ausnahme fürs Hütten-Holz existiert:
    refine = next(c for c in cands if c.action.id == "refine:catnip")
    assert refine.feasible and refine.score > 0
    # generischer Catnip-Kauf (Aqueduct) wird bestraft und fällt unter 0:
    aqueduct = next(c for c in cands if c.action.id == "build:aqueduct")
    assert aqueduct.components.get("opportunity", 0) < 0
    assert aqueduct.score < 0


def test_free_kitten_assigned_to_bottleneck_job():
    snap = make_snap(
        resources={"catnip": {"value": 2000, "max": 5000, "rate": 15},
                   "wood": {"value": 5, "max": 200, "rate": 0.2}},
        buildings={"field": {"val": 20, "prices": {"catnip": 60}},
                   "hut": {"val": 1, "prices": {"wood": 10}},
                   "library": {"val": 0, "prices": {"wood": 25}}},
        jobs={"woodcutter": 0}, free_kittens=2, kittens=2, max_kittens=2,
        catnip_field_base=15,
    )
    cands, bn, selected, mv = _generate(snap)
    assert bn["resource"] == "wood"
    assert selected.action.exec_spec.get("kind") == "assign_job"
    assert selected.action.exec_spec.get("job") == "woodcutter"


def test_storage_only_when_cap_blocks():
    """Storage-Regel 11.3 A: Barn nur bauen, wenn ein Cap das Ziel blockiert."""
    base = dict(
        jobs={"woodcutter": 2}, kittens=2, max_kittens=4,
        catnip_field_base=15,
        techs={"calendar": {"researched": True, "prices": {"science": 30}},
               "agriculture": {"researched": True, "prices": {"science": 100}}},
    )
    # Fall A: kein Cap blockiert das Ziel → weiterer (generischer) Barn unzulässig.
    # (barn val=1, damit der barn_1-Meilenstein nicht selbst das Ziel ist)
    snap = make_snap(
        resources={"catnip": {"value": 500, "max": 5000, "rate": 15},
                   "wood": {"value": 100, "max": 400, "rate": 0.5}},
        buildings={"field": {"val": 20, "prices": {"catnip": 300}},
                   "barn": {"val": 1, "prices": {"wood": 50}}},
        **base,
    )
    cands, _, _, _ = _generate(snap)
    assert not any(c.action.id == "build:barn" and c.feasible for c in cands)

    # Fall B: Ziel braucht 400 wood, Cap ist 200 → Barn zulässig und hoch bewertet
    snap = make_snap(
        resources={"catnip": {"value": 500, "max": 5000, "rate": 15},
                   "wood": {"value": 200, "max": 200, "rate": 0.5}},
        buildings={"hut": {"val": 2, "prices": {"wood": 400}},
                   "barn": {"val": 0, "prices": {"wood": 50}}},
        **base,
    )
    # aktives Ziel manuell auf hut setzen (Meilensteinliste wäre hier weiter):
    sres = safety.check(snap)
    mview = meta.evaluate(snap)
    if not (mview.active and mview.active.target == {"kind": "build", "name": "hut"}):
        from player.brain.meta import Milestone
        mview.active = Milestone("hut_x", "Hütte", lambda s: False,
                                 {"kind": "build", "name": "hut"})
    cands, bn = tactics.generate(snap, mview, sres)
    barn = next(c for c in cands if c.action.id == "build:barn")
    assert barn.components.get("storage", 0) > 0


def test_wait_has_reason_and_is_last_resort():
    snap = make_snap(
        resources={"catnip": {"value": 10, "max": 5000, "rate": 3},
                   "wood": {"value": 0, "max": 200, "rate": 0}},
        buildings={"field": {"val": 15, "prices": {"catnip": 600}}},
        catnip_field_base=10,
    )
    cands, bn, selected, _ = _generate(snap)
    wait = next(c for c in cands if c.action.id == "wait")
    assert "Warte" in wait.action.exec_spec["reason"] or "Kein Kandidat" in wait.action.exec_spec["reason"]


def test_deterministic_ordering():
    snap = make_snap(
        resources={"catnip": {"value": 100, "max": 5000, "rate": 5}},
        buildings={"field": {"val": 0, "prices": {"catnip": 10}}},
    )
    c1, _, s1, _ = _generate(snap)
    c2, _, s2, _ = _generate(snap)
    assert [c.action.id for c in c1] == [c.action.id for c in c2]
    assert s1.action.id == s2.action.id
