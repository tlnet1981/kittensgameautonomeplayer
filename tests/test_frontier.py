"""Tests des Ausbaugrenzen-Wächters (brain/frontier.py)."""

from player.brain import frontier
from tests.helpers import make_snap


def _ids(snap, run="FIRST_RUN", fired=None):
    return {n["id"] for n in frontier.check(snap, run, fired or set())}


def test_fresh_game_triggers_nothing():
    snap = make_snap(resources={"catnip": {"value": 10, "max": 5000, "rate": 1}})
    assert _ids(snap) == set()


def test_implemented_frontiers_removed():
    # „policies" (Spec 13.4 → brain/policy.py), „challenges" (Spec 18 →
    # brain/challenge.py), „transcend" (Spec 15.2 → brain/religion.py +
    # reset.execute_reset Schritt 5), „pacts" (Spec 15.4/15.5 →
    # brain/religion.py + tactics._religion_ev_candidates),
    # „shatter_engine" (Spec 17 → brain/timecrystal.py +
    # tactics._time_candidates) und „cs_loop" (Spec 19.2/19.3 →
    # chrono.positive_cs_check/seed_run_admissible, SEED_/POSITIVE_CS_RUN
    # in meta.py) sind umgesetzt — die Frontiers existieren nicht mehr und
    # feuern auch bei ihren früheren Triggern nicht.
    ids = {f.id for f in frontier.FRONTIERS}
    for done in ("policies", "challenges", "transcend", "pacts",
                 "shatter_engine", "cs_loop"):
        assert done not in ids
    snap = make_snap(techs={"civil": {"researched": True, "prices": {"science": 1500}}})
    assert "policies" not in _ids(snap)
    assert "challenges" not in _ids(snap, run="PARAGON_RUN")
    # Frühere Transcend-/Pacts-Trigger (hoher Worship, Black Pyramid):
    snap = make_snap(religion={
        "worship": 60000,
        "ziggurat": [{"name": "blackPyramid", "label": "Black Pyramid",
                      "val": 1, "unlocked": True, "prices": []}]})
    assert "transcend" not in _ids(snap)
    assert "pacts" not in _ids(snap)
    # Frühere Shatter-/CS-Loop-Trigger (TC-Bestand, Chronosphere-Flotte):
    snap = make_snap(resources={"timeCrystal": {"value": 60, "max": 0, "rate": 0}})
    assert "shatter_engine" not in _ids(snap)
    snap = make_snap(buildings={"chronosphere": {"val": 3, "prices": {"unobtainium": 2500}}})
    assert "cs_loop" not in _ids(snap)


def test_already_fired_not_repeated(monkeypatch):
    # Die Liste ist aktuell leer — der Wächter-Mechanismus selbst bleibt
    # bestehen und wird über eine Test-Frontier geprüft.
    probe = frontier.Frontier(
        id="probe", title="Test-Frontier für den Wächter-Mechanismus",
        trigger=lambda snap, run: True,
        happening="Konstruierter Trigger für den Unit-Test des Wächters.",
        missing="Nichts — reine Mechanik-Prüfung von frontier.check().",
        where="tests/test_frontier.py (kein Spielbezug, nur Testartefakt).",
        prompt="Kittens-Player: Test-Frontier, niemals umsetzen (Testartefakt).")
    monkeypatch.setattr(frontier, "FRONTIERS", [probe])
    snap = make_snap()
    assert "probe" in _ids(snap)
    assert "probe" not in _ids(snap, fired={"probe"})


def test_every_frontier_has_complete_guidance():
    for f in frontier.FRONTIERS:
        d = frontier.to_dict(f)
        for key in ("title", "happening", "missing", "where", "prompt"):
            assert d[key] and len(d[key]) > 20, f"{f.id}.{key} zu dünn"
        # Der Prompt muss als eigenständiger Claude-Code-Auftrag taugen:
        assert "Kittens-Player" in d["prompt"]
