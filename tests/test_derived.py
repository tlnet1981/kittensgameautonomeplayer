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


def test_projection_spring_surplus_is_ok_despite_small_stock():
    """Kern des Schleifen-Bugfixes: Im Frühling mit solider Feldbasis ist
    der Status ok, obwohl der aktuelle Bestand klein ist — die
    Überschuss-Saisons füllen den Vorrat vor dem Winter von selbst."""
    # 16 Felder (10/s Basis), 2 Kitten (1.7/s Bedarf), Bestand nur 100.
    # Frühling-Netto = 10*1.5 - 1.7 = 13.3/s → bis zum Winter sammeln sich
    # tausende Catnip an; Winter-Netto = 2.5 - 1.7 = +0.8 sogar positiv.
    snap = make_snap(
        resources={"catnip": {"value": 100, "max": 50000, "rate": 13.3}},
        catnip_field_base=10.0, kittens=2, season="spring",
    )
    food = snap["derived"]["food"]
    assert food["status"] == "ok"
    assert food["projectedMin"] >= 100


def test_projection_unsurvivable_winter_is_critical():
    """Winterdefizit größer als Bestand + Restüberschuss → kritisch,
    Tiefpunkt liegt im Winter (am Ende des Projektionshorizonts)."""
    # 4 Felder (2.5/s Basis), 6 Kitten (5.1/s Bedarf): Herbst-Netto
    # = 2.5 - 5.1 = -2.6/s, Winter-Netto = 0.625 - 5.1 = -4.5/s.
    snap = make_snap(
        resources={"catnip": {"value": 300, "max": 5000, "rate": -2.6}},
        catnip_field_base=2.5, kittens=6, season="autumn",
    )
    snap["village"]["catnipDemandPerSec"] = 5.1
    from player.state.derived import derive
    derive(snap)
    food = snap["derived"]["food"]
    assert food["status"] == "critical"
    assert food["projectedMin"] < food["criticalFloor"]
    # Tiefpunkt am Ende des Winters (Rest-Herbst 180 s + Winter 200 s):
    assert food["projectedMinInSeconds"] > 300


def test_projection_no_kittens_never_critical():
    """Ohne Kitten kann niemand verhungern — frisches Spiel ist nie 'kritisch'."""
    snap = make_snap(
        resources={"catnip": {"value": 0, "max": 5000, "rate": 0.0}},
        kittens=0,
    )
    assert snap["derived"]["food"]["status"] == "ok"


def test_project_catnip_deltas():
    """Was-wäre-wenn-Deltas: Feldkauf (Bestand runter, Rate rauf)."""
    from player.state.derived import project_catnip
    snap = make_snap(
        resources={"catnip": {"value": 500, "max": 5000, "rate": -1.0}},
        catnip_field_base=2.0, kittens=4, season="winter",
    )
    base = project_catnip(snap)
    # teures Feld: -400 Bestand, +0.625/s Basis → Projektion schlechter
    worse = project_catnip(snap, stock_delta=-400, field_rate_delta=0.625)
    assert worse["projectedMin"] < base["projectedMin"]
    # geschenktes Feld: nur Rate rauf → Projektion besser
    better = project_catnip(snap, field_rate_delta=0.625)
    assert better["projectedMin"] > base["projectedMin"]


def test_reset_paragon():
    snap = make_snap(kittens=75)
    assert snap["derived"]["resetParagon"] == 5
