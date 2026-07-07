"""Tests des Ausbaugrenzen-Wächters (brain/frontier.py)."""

from player.brain import frontier
from tests.helpers import make_snap


def _ids(snap, run="FIRST_RUN", fired=None):
    return {n["id"] for n in frontier.check(snap, run, fired or set())}


def test_fresh_game_triggers_nothing():
    snap = make_snap(resources={"catnip": {"value": 10, "max": 5000, "rate": 1}})
    assert _ids(snap) == set()


def test_implemented_frontiers_removed():
    # „policies" (Spec 13.4 → brain/policy.py) und „challenges" (Spec 18 →
    # brain/challenge.py) sind umgesetzt — die Frontiers existieren nicht mehr
    # und feuern auch bei ihren früheren Triggern nicht.
    ids = {f.id for f in frontier.FRONTIERS}
    assert "policies" not in ids
    assert "challenges" not in ids
    snap = make_snap(techs={"civil": {"researched": True, "prices": {"science": 1500}}})
    assert "policies" not in _ids(snap)
    assert "challenges" not in _ids(snap, run="PARAGON_RUN")


def test_transcend_trigger_on_high_worship():
    snap = make_snap()
    snap["religion"] = {"worship": 60000, "epiphany": 0, "transcendenceTier": 0,
                        "upgrades": [], "ziggurat": []}
    assert "transcend" in _ids(snap)


def test_shatter_engine_trigger_on_tc_stock():
    snap = make_snap(resources={"timeCrystal": {"value": 60, "max": 0, "rate": 0}})
    assert "shatter_engine" in _ids(snap)


def test_pacts_trigger_on_black_pyramid():
    snap = make_snap()
    snap["religion"] = {"worship": 0, "epiphany": 0, "transcendenceTier": 0,
                        "upgrades": [],
                        "ziggurat": [{"name": "blackPyramid", "label": "Black Pyramid",
                                      "val": 1, "unlocked": True, "prices": []}]}
    assert "pacts" in _ids(snap)


def test_cs_loop_trigger_on_chronospheres():
    snap = make_snap(buildings={"chronosphere": {"val": 3, "prices": {"unobtainium": 2500}}})
    assert "cs_loop" in _ids(snap)


def test_already_fired_not_repeated():
    snap = make_snap()
    snap["religion"] = {"worship": 60000, "epiphany": 0, "transcendenceTier": 0,
                        "upgrades": [], "ziggurat": []}
    assert "transcend" not in _ids(snap, fired={"transcend"})


def test_every_frontier_has_complete_guidance():
    for f in frontier.FRONTIERS:
        d = frontier.to_dict(f)
        for key in ("title", "happening", "missing", "where", "prompt"):
            assert d[key] and len(d[key]) > 20, f"{f.id}.{key} zu dünn"
        # Der Prompt muss als eigenständiger Claude-Code-Auftrag taugen:
        assert "Kittens-Player" in d["prompt"]
