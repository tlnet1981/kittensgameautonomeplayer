"""Tests der Challenge-Logik (Spec 18.1–18.4, brain/challenge.py)."""

from player.brain import actions, challenge, meta, reset, simulate
from tests.helpers import make_snap

AB_PERK = {"name": "adjustmentBureau", "label": "Adjustment Bureau",
           "researched": True, "unlocked": True,
           "prices": [{"name": "paragon", "val": 5}]}


def _with_prestige(snap, paragon=40, perks=None):
    snap["prestige"] = {"paragon": paragon, "burnedParagon": 0, "karma": 1,
                        "perks": perks or []}
    return snap


def _winter(**over):
    d = {"name": "winterIsComing", "label": "Winter Has Come"}
    d.update(over)
    return d


# ------------------------------------------------------------ 18.2 Bewertung

def test_challenge_value_ranking():
    snap = make_snap(challenges=[_winter(), {"name": "anarchy"},
                                 {"name": "energy", "researched": True, "on": 1}])
    v_winter = challenge.challenge_value(snap, "winterIsComing")
    v_anarchy = challenge.challenge_value(snap, "anarchy")
    assert v_winter > v_anarchy > 0
    # Erstabschluss-Regel: bereits researched → Wert 0:
    assert challenge.challenge_value(snap, "energy") == 0.0
    best = challenge.best_challenge(snap)
    assert best is not None and best[0] == "winterIsComing"


def test_best_challenge_fallbacks():
    # Ohne challenges-Sektion im Snapshot: kein Kandidat, kein Crash.
    assert challenge.best_challenge(make_snap()) is None
    # Alles erledigt → None:
    snap = make_snap(challenges=[_winter(researched=True, on=1)])
    assert challenge.best_challenge(snap) is None
    # Iron Will ist ausgenommen (Sonderregeln, challenges.js:885-888):
    snap = make_snap(challenges=[{"name": "ironWill"}])
    assert challenge.best_challenge(snap) is None
    # Gesperrte Challenges zählen nicht:
    snap = make_snap(challenges=[_winter(unlocked=False)])
    assert challenge.best_challenge(snap) is None


# ------------------------------------------------------------ Meta (Run-Typ)

def test_challenge_run_admissible_only_with_positive_value():
    # Positiver Wert + Challenges erreichbar (Adjustment Bureau) → zulässig:
    snap = _with_prestige(make_snap(challenges=[_winter()]), perks=[AB_PERK])
    assert "CHALLENGE_RUN" in meta._admissible_run_types(snap)
    # Ohne Adjustment Bureau/Tab sind Challenges unerreichbar → nicht zulässig:
    snap = _with_prestige(make_snap(challenges=[_winter()]))
    assert "CHALLENGE_RUN" not in meta._admissible_run_types(snap)
    # Kein unerledigter positiver Erstabschluss → nicht zulässig:
    snap = _with_prestige(make_snap(challenges=[_winter(researched=True, on=1)]),
                          perks=[AB_PERK])
    assert "CHALLENGE_RUN" not in meta._admissible_run_types(snap)
    # Ohne Challenge-Daten: Altverhalten unverändert:
    snap = _with_prestige(make_snap(), perks=[AB_PERK])
    assert meta._admissible_run_types(snap) == ["PRICE_RATIO_RUN"]


def test_active_challenge_binds_run_type():
    snap = _with_prestige(make_snap(challenges=[_winter(active=True)]),
                          perks=[AB_PERK])
    assert meta._admissible_run_types(snap) == ["CHALLENGE_RUN"]


def test_plan_restzeit_is_conservative_reference_constant():
    snap = _with_prestige(make_snap(
        resources={"catnip": {"value": 100, "max": 5000, "rate": 1.0}},
        kittens=10, challenges=[_winter()]), perks=[AB_PERK])
    proj = simulate.project(snap, 600.0)
    rz = meta._plan_restzeit(snap, "CHALLENGE_RUN", proj, 600.0)
    assert rz == challenge.est_completion_s("winterIsComing") == 6 * 3600.0


# ------------------------------------------------------------ 18.4 Reset-Gate

def test_reset_not_recommended_while_challenge_active():
    snap = _with_prestige(make_snap(challenges=[_winter(active=True)]))
    ev = reset.evaluate(snap, "CHALLENGE_RUN", None)
    assert not ev["recommended"]
    assert "18.4" in ev["reason"]


def test_reset_recommended_only_when_game_marks_researched():
    # Prognose reicht nicht — erst der researched-Übergang des Spiels
    # (researchChallenge, challenges.js:648-665) öffnet das Gate:
    snap = _with_prestige(make_snap(challenges=[_winter()]))
    ev = reset.evaluate(snap, "CHALLENGE_RUN", None)
    assert not ev["recommended"]

    snap = _with_prestige(make_snap(challenges=[_winter(researched=True, on=1)]))
    ev = reset.evaluate(snap, "CHALLENGE_RUN", None)
    assert ev["recommended"]
    assert "researched" in ev["reason"]


def test_reset_gate_without_data_stays_closed():
    ok, reason = challenge.reset_gate(make_snap())
    assert not ok and "18.4" in reason


# ------------------------------------------------------------ Aktivierung

def test_pending_challenge_planned_before_reset():
    # Makroplan CHALLENGE_RUN + keine aktive Challenge → die beste Challenge
    # wird als pending-Kandidat für den NÄCHSTEN Run ausgewiesen; execute_reset
    # aktiviert sie vor dem Reset (pending → active, game.js:5136-5141).
    snap = _with_prestige(make_snap(challenges=[_winter(), {"name": "anarchy"}]),
                          perks=[AB_PERK])
    ev = reset.evaluate(snap, "CHALLENGE_RUN", None)
    assert ev["pendingChallenge"] is not None
    assert ev["pendingChallenge"]["name"] == "winterIsComing"
    assert ev["pendingChallenge"]["value"] > 0
    # Läuft bereits eine Challenge, wird nichts Neues vorgemerkt (18.3: einzeln):
    snap = _with_prestige(make_snap(challenges=[_winter(active=True)]))
    ev = reset.evaluate(snap, "CHALLENGE_RUN", None)
    assert ev["pendingChallenge"] is None
    # Andere Run-Typen merken keine Challenge vor:
    snap = _with_prestige(make_snap(challenges=[_winter()]), perks=[AB_PERK])
    ev = reset.evaluate(snap, "PRICE_RATIO_RUN", None)
    assert ev["pendingChallenge"] is None


def test_activate_challenge_action_is_irreversible():
    act = actions.activate_challenge("winterIsComing", "Winter Has Come")
    assert act.atomicity == actions.IRREVERSIBLE
    assert act.irreversible
    assert act.exec_spec == {"kind": "activate_challenge",
                             "name": "winterIsComing",
                             "label": "Winter Has Come"}
