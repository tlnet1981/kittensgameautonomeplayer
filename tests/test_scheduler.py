"""Ereignisgetriebenes Replanning (Spec 21.1–21.3 / Gap #28):
next_wakeup-Zeitwahl und harte Trigger-Klassifikation.
"""

from player.brain import scheduler
from tests.helpers import make_snap


# ---------------------------------------------------------------- next_wakeup

def test_wakeup_season_boundary_wins():
    """Kurz vor Saisonende weckt der Saisonwechsel (Resttage × 2 s)."""
    snap = make_snap(resources={"catnip": {"value": 10, "max": 5000, "rate": 0.1}})
    snap["calendar"]["day"] = 97       # 3 Resttage → 6 s
    delay, reason = scheduler.next_wakeup(snap, target_eta=None)
    assert reason["source"] == "season"
    assert delay == 6.0


def test_wakeup_half_cap_time_wins():
    """Cap in 8 s → Weckzeit = ½ Cap-Zeit (21.2)."""
    snap = make_snap(resources={"catnip": {"value": 4992, "max": 5000, "rate": 1.0}})
    delay, reason = scheduler.next_wakeup(snap, target_eta=None)
    assert reason["source"] == "cap"
    assert abs(delay - 4.0) < 1e-6


def test_wakeup_eta_checkpoint_wins():
    """10 % der Ziel-ETA als weicher Kontrollpunkt (21.2)."""
    snap = make_snap(resources={"catnip": {"value": 10, "max": 5000, "rate": 0.01}})
    delay, reason = scheduler.next_wakeup(snap, target_eta=100.0)
    assert reason["source"] == "eta"
    assert abs(delay - 10.0) < 1e-6


def test_wakeup_interval_fallback_and_upper_clamp():
    """Ohne nahe Ereignisse: periodischer Kontrollpunkt, nie über 30 s."""
    snap = make_snap(resources={"catnip": {"value": 10, "max": 5000, "rate": 0.001}})
    delay, reason = scheduler.next_wakeup(snap, target_eta=100000.0)
    assert reason["source"] == "interval"
    assert delay == 30.0


def test_wakeup_lower_clamp_is_decision_interval():
    snap = make_snap(resources={"catnip": {"value": 4999.9, "max": 5000, "rate": 5.0}})
    delay, reason = scheduler.next_wakeup(snap, target_eta=None, decision_interval=1.5)
    assert delay == 1.5                # geklemmt auf [decision_interval, 30]
    assert reason["source"] == "cap"


def test_wakeup_without_snapshot_falls_back():
    delay, reason = scheduler.next_wakeup({}, None, decision_interval=2.0)
    assert delay == 2.0
    assert reason["source"] == "interval"


# ---------------------------------------------------------------- Harte Trigger

def _sig(**overrides):
    snap = make_snap(
        resources={"catnip": {"value": 10, "max": 5000, "rate": 1.0}},
        techs={"calendar": {"researched": False, "prices": {"science": 30}}},
        kittens=2, max_kittens=2,
    )
    sig = scheduler.signature(snap)
    sig.update(overrides)
    return sig


def test_no_change_is_no_hard_trigger():
    assert scheduler.classify_hard_trigger(_sig(), _sig()) is None
    assert scheduler.classify_hard_trigger(None, _sig()) is None


def test_exec_failure_is_hard_trigger():
    reason = scheduler.classify_hard_trigger(_sig(), _sig(), exec_failed=True)
    assert reason == {"type": "hard", "source": "error",
                      "detail": "Aktionsfehler im Vorzyklus (21.1)"}


def test_new_research_is_hard_unlock_trigger():
    prev = _sig()
    cur = _sig(techs=prev["techs"] | {"calendar"})
    reason = scheduler.classify_hard_trigger(prev, cur)
    assert reason["type"] == "hard" and reason["source"] == "unlock"
    assert "calendar" in reason["detail"]


def test_cap_reached_is_hard_trigger():
    prev = _sig()
    cur = _sig(caps_reached={"catnip"})
    reason = scheduler.classify_hard_trigger(prev, cur)
    assert reason["source"] == "cap"


def test_season_and_kitten_changes_are_hard_triggers():
    prev = _sig()
    assert scheduler.classify_hard_trigger(prev, _sig(season=1))["source"] == "season"
    assert scheduler.classify_hard_trigger(prev, _sig(kittens=3))["source"] == "kitten"


def test_signature_detects_cap_reached():
    snap = make_snap(resources={"catnip": {"value": 5000, "max": 5000, "rate": 1.0}})
    assert "catnip" in scheduler.signature(snap)["caps_reached"]


def test_hard_trigger_priority_is_deterministic():
    """Unlock schlägt Cap schlägt Saison (feste Reihenfolge, 21.1)."""
    prev = _sig()
    cur = _sig(techs=prev["techs"] | {"calendar"}, caps_reached={"catnip"}, season=1)
    assert scheduler.classify_hard_trigger(prev, cur)["source"] == "unlock"


def test_signature_with_real_tab_dicts_is_hashable():
    """Live-Regression (E2E-Fund): snapshot.js liefert tabs als Dicts
    {id, visible} — die Signatur muss daraus hashbare IDs machen, sonst
    stirbt jeder Zyklus mit TypeError und der Agent steht komplett still."""
    snap = make_snap()
    snap["tabs"] = [{"id": "Bonfire", "visible": True},
                    {"id": "Science", "visible": False}]
    prev = scheduler.signature(snap)
    assert prev["tabs"] == {"Bonfire"}          # nur sichtbare IDs

    snap["tabs"][1]["visible"] = True           # Science-Tab erscheint
    cur = scheduler.signature(snap)
    trigger = scheduler.classify_hard_trigger(prev, cur)
    assert trigger["source"] == "unlock"
    assert "Science" in trigger["detail"]
