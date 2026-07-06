"""Tests der abgeleiteten Kennzahlen (state/derived.py)."""

from tests.helpers import make_snap


def test_fill_time():
    snap = make_snap(resources={"wood": {"value": 50, "max": 200, "rate": 5.0}})
    d = snap["derived"]["resources"]["wood"]
    assert abs(d["fillTime"] - 30.0) < 1e-6
    assert d["depletionTime"] is None


def test_depletion_time():
    snap = make_snap(resources={"catnip": {"value": 100, "max": 5000, "rate": -2.0}})
    d = snap["derived"]["resources"]["catnip"]
    assert abs(d["depletionTime"] - 50.0) < 1e-6


def test_worst_winter_food_negative():
    # 10 Felder à 1.25/s Basisproduktion, Frühling (×1.5), 5 Kitten essen mit.
    snap = make_snap(
        resources={"catnip": {"value": 1000, "max": 5000, "rate": 10.0}},
        catnip_field_base=12.5, kittens=5, season="spring",
    )
    food = snap["derived"]["food"]
    # Winterproduktion = 10 - 12.5*1.5 + 12.5*0.25 = -5.625
    assert food["worstWinterNetPerSec"] < 0
    assert food["reserveSeconds"] is not None
    assert abs(food["reserveSeconds"] - 1000 / 5.625) < 1.0


def test_worst_winter_food_positive():
    snap = make_snap(
        resources={"catnip": {"value": 100, "max": 5000, "rate": 20.0}},
        catnip_field_base=10.0, season="winter",
    )
    food = snap["derived"]["food"]
    assert food["worstWinterNetPerSec"] > 0
    assert food["reserveSeconds"] is None
    assert food["safe"]


def test_reset_paragon():
    snap = make_snap(kittens=75)
    assert snap["derived"]["resetParagon"] == 5
