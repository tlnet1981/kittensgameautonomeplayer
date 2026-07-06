"""Tests des dynamischen Housing-Evaluators (Spec 12.1, tactics._housing_eval)."""

from player.brain import meta, safety, tactics
from tests.helpers import make_snap


def _generate(snap):
    sres = safety.check(snap)
    mview = meta.evaluate(snap)
    cands, bn = tactics.generate(snap, mview, sres)
    return cands


def _safe_food():
    """Reichlich Felder + Vorrat: Projektion trägt auch neue Kitten."""
    return dict(
        resources={"catnip": {"value": 40000, "max": 50000, "rate": 40},
                   "wood": {"value": 500, "max": 1000, "rate": 1}},
        catnip_field_base=40.0, season="spring",
    )


def test_no_housing_while_capacity_free():
    """(a) Ungenutzte Plätze → kein Housing trotz Geld (12.1)."""
    snap = make_snap(buildings={"hut": {"val": 2, "prices": {"wood": 30}}},
                     kittens=2, max_kittens=4, jobs={"farmer": 2}, **_safe_food())
    cands = _generate(snap)
    hut = next(c for c in cands if c.action.id == "build:hut")
    assert not hut.feasible
    assert "ungenutzte" in hut.reject_reason.lower()


def test_housing_when_full_and_food_holds():
    """(b) Kapazität voll + Projektion trägt → Housing schlägt Generik."""
    snap = make_snap(buildings={"hut": {"val": 2, "prices": {"wood": 30}},
                                "aqueduct": {"val": 0, "prices": {"wood": 30}}},
                     kittens=4, max_kittens=4, jobs={"farmer": 4}, **_safe_food())
    cands = _generate(snap)
    hut = next(c for c in cands if c.action.id == "build:hut")
    aqueduct = next(c for c in cands if c.action.id == "build:aqueduct")
    assert hut.feasible and hut.components.get("housing") == 1.6
    assert hut.score > aqueduct.score


def test_housing_rejected_when_projection_would_tip():
    """(c) Kapazität voll, aber neue Kitten würden den Winter kippen."""
    snap = make_snap(
        resources={"catnip": {"value": 400, "max": 5000, "rate": 1.0},
                   "wood": {"value": 500, "max": 1000, "rate": 1}},
        buildings={"hut": {"val": 2, "prices": {"wood": 30}}},
        kittens=4, max_kittens=4, jobs={"farmer": 4},
        catnip_field_base=3.5, season="autumn",
    )
    snap["village"]["catnipDemandPerSec"] = 3.4
    from player.state.derived import derive
    derive(snap)
    cands = _generate(snap)
    hut = next(c for c in cands if c.action.id == "build:hut")
    assert not hut.feasible
    assert "kippen" in hut.reject_reason or "blockiert" in hut.reject_reason


def test_paragon_component_near_reset_threshold():
    """(d) Ab 68 Kitten zählt der Paragon-Grenzwert (ab 70: +1/Kitten)."""
    snap = make_snap(buildings={"hut": {"val": 40, "prices": {"wood": 30}}},
                     kittens=69, max_kittens=69, jobs={"farmer": 69}, **_safe_food())
    cands = _generate(snap)
    hut = next(c for c in cands if c.action.id == "build:hut")
    assert hut.components.get("paragon") == 0.4


def test_first_hut_without_milestone():
    """(e) Bootstrap: maxKittens == 0 gilt als voll — die erste Hütte
    entsteht dynamisch, ohne hut_1-Meilenstein."""
    assert not any(m.id.startswith("hut_") for m in meta.P0_MILESTONES)
    snap = make_snap(
        resources={"catnip": {"value": 2000, "max": 5000, "rate": 12},
                   "wood": {"value": 20, "max": 200, "rate": 0}},
        buildings={"hut": {"val": 0, "prices": {"wood": 5}},
                   "field": {"val": 12, "prices": {"catnip": 40}},
                   "library": {"val": 0, "prices": {"wood": 25}}},
        kittens=0, max_kittens=0,
        catnip_field_base=7.5, season="spring",
    )
    cands = _generate(snap)
    hut = next(c for c in cands if c.action.id == "build:hut")
    assert hut.feasible
    assert hut.components.get("housing") == 1.6
