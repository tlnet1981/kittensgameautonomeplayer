"""Tests der Food-Sicherheitsinvariante (brain/safety.py)."""

from player.brain import safety
from tests.helpers import make_snap


def _critical_snap(**kwargs):
    """Snapshot mit akut negativer Worst-Winter-Bilanz und kleiner Reserve."""
    defaults = dict(
        resources={"catnip": {"value": 100, "max": 5000, "rate": 1.0}},
        catnip_field_base=8.0, kittens=6, season="spring",
    )
    defaults.update(kwargs)
    return make_snap(**defaults)


def test_safe_when_reserve_grows():
    snap = make_snap(resources={"catnip": {"value": 10, "max": 5000, "rate": 5.0}},
                     catnip_field_base=4.0, season="winter")
    result = safety.check(snap)
    assert result.ok
    assert result.action is None


def test_critical_assigns_free_kitten_as_farmer():
    snap = _critical_snap(jobs={"farmer": 0, "woodcutter": 3}, free_kittens=2)
    result = safety.check(snap)
    assert not result.ok
    assert result.action.exec_spec["kind"] == "assign_job"
    assert result.action.exec_spec["job"] == "farmer"


def test_critical_shifts_from_biggest_job():
    snap = _critical_snap(jobs={"farmer": 1, "woodcutter": 4, "scholar": 2}, free_kittens=0)
    result = safety.check(snap)
    assert result.action.exec_spec["kind"] == "shift_job"
    assert result.action.exec_spec["from"] == "woodcutter"
    assert result.action.exec_spec["to"] == "farmer"


def test_critical_without_farmer_builds_field():
    snap = _critical_snap(
        buildings={"field": {"val": 5, "prices": {"catnip": 20}}},
        jobs={"woodcutter": 2},
    )
    result = safety.check(snap)
    assert result.action.id == "build:field"


def test_housing_blocked_below_comfort():
    # Reserve zwischen Floor und Comfort: ok, aber Housing gesperrt.
    snap = _critical_snap(resources={"catnip": {"value": 3000, "max": 5000, "rate": 1.0}})
    result = safety.check(snap)
    reserve = snap["derived"]["food"]["reserveSeconds"]
    assert safety.RESERVE_FLOOR_SECONDS < reserve < safety.RESERVE_COMFORT_SECONDS
    assert result.ok
    assert "housing" in result.blocked_types
