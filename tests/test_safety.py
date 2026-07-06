"""Tests der Food-Sicherheitslogik (brain/safety.py) — neue Semantik:
Saisonprojektion + abgestufte Schutzkandidaten statt Score-10-Monopol."""

from player.brain import meta, safety, tactics
from tests.helpers import make_snap


def _critical_snap(**kwargs):
    """Herbst, wenige Felder, viele Kitten: Winter rechnerisch nicht überlebbar."""
    defaults = dict(
        resources={"catnip": {"value": 200, "max": 5000, "rate": -2.6}},
        catnip_field_base=2.5, kittens=6, season="autumn",
    )
    defaults.update(kwargs)
    snap = make_snap(**defaults)
    snap["village"]["catnipDemandPerSec"] = 5.1
    from player.state.derived import derive
    return derive(snap)


def test_ok_when_projection_holds():
    snap = make_snap(
        resources={"catnip": {"value": 100, "max": 50000, "rate": 13.0}},
        catnip_field_base=10.0, kittens=2, season="spring",
    )
    result = safety.check(snap)
    assert result.ok
    assert not result.candidates


def test_critical_offers_graded_candidates():
    snap = _critical_snap(jobs={"farmer": 0, "woodcutter": 3}, free_kittens=2)
    result = safety.check(snap)
    assert result.critical
    scores = {c.action.exec_spec.get("kind", c.action.id): c.score
              for c in result.candidates if c.feasible}
    # Farmer (6.0) > Feld (falls sinnvoll) > Gather (1.2)
    assert scores.get("assign_job") == 6.0
    assert any(c.action.id == "gather:catnip" and c.score == 1.2
               for c in result.candidates)


def test_critical_shifts_from_biggest_job_when_no_free_kittens():
    snap = _critical_snap(jobs={"farmer": 1, "woodcutter": 4, "scholar": 2},
                          free_kittens=0)
    result = safety.check(snap)
    shift = next(c for c in result.candidates
                 if c.action.exec_spec.get("kind") == "shift_job")
    assert shift.action.exec_spec["from"] == "woodcutter"
    assert shift.action.exec_spec["to"] == "farmer"


def test_field_purchase_requires_projection_improvement():
    """Fix der beobachteten Schleife: teures Feld verschlechtert die
    Projektion → abgelehnt; billiges Feld verbessert sie → Kandidat."""
    # Teuer: Feld kostet fast den ganzen Bestand
    snap = _critical_snap(
        buildings={"field": {"val": 4, "prices": {"catnip": 190}}})
    result = safety.check(snap)
    field = next(c for c in result.candidates if c.action.id == "build:field")
    assert not field.feasible
    assert "verschlechtern" in field.reject_reason

    # Billig: Feld kostet 15 → Winterrate-Gewinn überwiegt
    snap = _critical_snap(
        buildings={"field": {"val": 4, "prices": {"catnip": 15}}})
    result = safety.check(snap)
    field = next(c for c in result.candidates if c.action.id == "build:field")
    assert field.feasible
    assert field.score == 4.0


def test_regression_research_beats_gather_loop():
    """Das vom Nutzer beobachtete Szenario: Food kritisch, Science für
    Agriculture vorhanden → die FORSCHUNG gewinnt (food-neutral), nicht
    die Gather-Schleife."""
    snap = _critical_snap(
        resources={"catnip": {"value": 200, "max": 5000, "rate": -2.6},
                   "science": {"value": 150, "max": 250, "rate": 0.5},
                   "wood": {"value": 50, "max": 200, "rate": 0.3}},
        buildings={"field": {"val": 15, "prices": {"catnip": 190}},
                   "library": {"val": 1, "prices": {"wood": 40}},
                   "hut": {"val": 3, "prices": {"wood": 20}}},
        techs={"calendar": {"researched": True, "prices": {"science": 30}},
               "agriculture": {"researched": False, "unlocked": True,
                               "prices": {"science": 100}}},
        jobs={"woodcutter": 6}, free_kittens=0,
    )
    safety_result = safety.check(snap)
    assert safety_result.critical
    mview = meta.evaluate(snap)
    assert mview.active.id == "agriculture"
    cands, _ = tactics.generate(snap, mview, safety_result)
    cands.extend(safety_result.candidates)
    cands.sort(key=lambda c: (-c.score, c.action.id))
    # Umschulen zum Farmer (6.0) ist die beste Sofortmaßnahme; direkt danach
    # kommt die Agriculture-Forschung (3.0) — Gather (1.2) weit dahinter.
    # Entscheidend: Forschung schlägt Gather und das teure Feld ist raus.
    feasible = [c for c in cands if c.feasible and c.score > 0]
    ids = [c.action.id for c in feasible]
    assert ids.index("research:agriculture") < ids.index("gather:catnip")
    assert not any(c.action.id == "build:field" and c.feasible and c.score > 0
                   for c in cands)


def test_warn_blocks_housing_only():
    """Warnstufe (Projektion unter Warn-, über Kritisch-Schwelle):
    kein Schutzmonopol, aber Housing gesperrt."""
    snap = make_snap(
        resources={"catnip": {"value": 1150, "max": 5000, "rate": -0.2}},
        catnip_field_base=4.0, kittens=5, season="autumn",
    )
    snap["village"]["catnipDemandPerSec"] = 4.25
    from player.state.derived import derive
    derive(snap)
    food = snap["derived"]["food"]
    assert food["status"] == "warn", food
    result = safety.check(snap)
    assert result.ok
    assert "housing" in result.blocked_types
    assert not result.candidates
