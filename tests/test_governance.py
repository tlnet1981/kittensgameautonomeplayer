"""Governance-Kern (Spec G-02/G-06/G-10, 21.3, 22.2, Anhang A.2):
AgentMode-Gate, Version Guard + acknowledge, Prognose-Streak, Commit-Grenze.
"""

import asyncio
import copy

from config import Config
from player.brain import actions, loop, meta, safety, tactics
from player.brain.loop import Brain
from player.brain.records import Candidate
from player.events import EventBus
from player.runtime import PlayerRuntime
from tests.helpers import make_snap


def _runtime(tmp_path) -> PlayerRuntime:
    cfg = Config()
    cfg.data_dir = tmp_path
    return PlayerRuntime(cfg, EventBus())


class _StubRuntime:
    """Minimaler Runtime-Ersatz für Brain-Unit-Tests (kein Browser)."""

    def __init__(self):
        self.bus = EventBus()
        self.browser = None
        self.config = Config()
        self.agent_mode = "ACTIVE"
        self.agent_mode_reason = ""
        self.pause_requested = False
        self.step_actions_remaining = 0
        self.step_until_decision = False
        self.frontier_fired = {}
        self.frontier_dismissed = set()
        self.state = "RUNNING"

    def enter_model_mismatch(self, reason, source="model"):
        self.agent_mode = "MODEL_MISMATCH"
        self.agent_mode_reason = reason

    def set_state(self, new_state, reason=""):
        self.state = new_state

    def frontier_notify(self, notice):
        self.frontier_fired[notice["id"]] = notice


# ---------------------------------------------------------------- Atomicity

def test_atomicity_classification():
    assert actions.wait("x", "y").atomicity == actions.READ_ONLY
    assert actions.buy_building("field", "Field", 0).atomicity == actions.REVERSIBLE
    assert actions.craft("beam", "Beam", 5).atomicity == actions.BATCH_REVERSIBLE
    assert actions.craft("beam", "Beam", 1).atomicity == actions.REVERSIBLE
    assert actions.buy_perk("engineering", "Engineering").atomicity == actions.IRREVERSIBLE
    assert actions.adore().atomicity == actions.IRREVERSIBLE
    assert actions.sacrifice_unicorns().atomicity == actions.IRREVERSIBLE
    assert actions.reset_run().atomicity == actions.IRREVERSIBLE
    # Shatter: große Batches (> 2) sind irreversibel (Spec 7.4), kleine nicht.
    assert actions.shatter(5).atomicity == actions.IRREVERSIBLE
    assert actions.shatter(2).atomicity == actions.BATCH_REVERSIBLE
    assert actions.festival().atomicity == actions.REVERSIBLE


# ---------------------------------------------------------------- AgentMode-Gate

def _gate_candidates():
    return [
        Candidate(actions.buy_building("field", "Field", 0,
                                       prices=[{"name": "catnip", "val": 10}]),
                  2.0, {"milestone": 2.0}),
        Candidate(actions.research("calendar", "Calendar"), 1.9, {"unlock": 1.9}),
        Candidate(actions.toggle_building("steamworks", "Steamworks", on=False),
                  1.5, {"energyRelief": 1.5}),
        Candidate(actions.toggle_building("steamworks", "Steamworks", on=True),
                  1.0, {"energyRelief": 1.0}),
        Candidate(actions.wait("warten", "wecken"), 0.01, {"base": 0.01}),
    ]


def test_mode_gate_mismatch_allows_only_readonly_and_toggle_off():
    cands = _gate_candidates()
    loop.apply_mode_gate(cands, "MODEL_MISMATCH")
    by_id = {c.action.id: c for c in cands}
    assert not by_id["build:field"].feasible
    assert by_id["build:field"].reject_reason == loop.MISMATCH_REJECT
    assert not by_id["research:calendar"].feasible
    assert by_id["toggle:steamworks:off"].feasible      # Verbraucher abschalten ok
    assert not by_id["toggle:steamworks:on"].feasible   # Anschalten nicht
    assert by_id["wait"].feasible                       # WAIT bleibt möglich


def test_mode_gate_safe_stop_blocks_everything_but_wait():
    cands = _gate_candidates()
    loop.apply_mode_gate(cands, "SAFE_STOP")
    for c in cands:
        if c.action.type == "WAIT":
            assert c.feasible
        else:
            assert not c.feasible and c.reject_reason == loop.SAFE_STOP_REJECT


def test_mode_gate_active_changes_nothing():
    cands = _gate_candidates()
    loop.apply_mode_gate(cands, "ACTIVE")
    assert all(c.feasible for c in cands)


def test_manipulated_version_gates_full_candidate_set(tmp_path):
    """End-to-End des Gates: manipulierte Version ⇒ MODEL_MISMATCH ⇒ in der
    echten Kandidatenliste ist nur noch WAIT (bzw. toggle-off) machbar."""
    rt = _runtime(tmp_path)
    snap = make_snap(resources={"catnip": {"value": 100, "max": 5000, "rate": 1}},
                     buildings={"field": {"val": 0, "prices": {"catnip": 10}}})
    snap["meta"]["version"] = "9999"     # Abweichung von der Referenz
    rt.apply_version_guard(snap)
    assert rt.agent_mode == "MODEL_MISMATCH"

    cands, _ = tactics.generate(snap, meta.evaluate(snap), safety.check(snap))
    loop.apply_mode_gate(cands, rt.agent_mode)
    feasible = [c for c in cands if c.feasible]
    assert all(c.action.atomicity == actions.READ_ONLY
               or (c.action.type == "TOGGLE_BUILDING"
                   and not c.action.exec_spec.get("on")) for c in feasible)
    # Auswahlregel des Loops fällt auf WAIT zurück:
    selected = next((c for c in cands if c.feasible and c.score > 0),
                    next(c for c in cands if c.action.type == "WAIT"))
    assert selected.action.type == "WAIT"


# ---------------------------------------------------------------- Version Guard

def test_version_guard_match_stays_active(tmp_path):
    rt = _runtime(tmp_path)
    rt.apply_version_guard(make_snap())    # Referenzversion 1502 r3
    assert rt.agent_mode == "ACTIVE"
    assert rt.version_guard["match"] is True


def test_acknowledge_resets_and_prevents_retrigger(tmp_path):
    rt = _runtime(tmp_path)
    snap = make_snap()
    snap["meta"]["version"] = "9999"
    rt.apply_version_guard(snap)
    assert rt.agent_mode == "MODEL_MISMATCH"

    rt.acknowledge_mismatch()
    assert rt.agent_mode == "ACTIVE"
    # Dieselbe quittierte Version retriggert NICHT (kein Endlos-Loop):
    rt.apply_version_guard(snap)
    assert rt.agent_mode == "ACTIVE"
    # Eine NEUE abweichende Version triggert wieder:
    snap2 = make_snap()
    snap2["meta"]["version"] = "8888"
    rt.apply_version_guard(snap2)
    assert rt.agent_mode == "MODEL_MISMATCH"


# ---------------------------------------------------------------- Prognose (G-10)

def _obs(res: dict[str, float], rates: dict[str, float] | None = None) -> dict:
    return {"resources": res, "rates": rates or {}}


def test_check_prediction_within_tolerance():
    pred = {"deltas": {"catnip": -100.0, "wood": 1.0}, "stochastic": False}
    before = _obs({"catnip": 500.0, "wood": 0.0}, {"catnip": 2.0})
    after = _obs({"catnip": 404.0, "wood": 1.0})   # −96: Drift + Toleranz deckt das
    observed, ok = loop.check_prediction(pred, before, after)
    assert ok
    assert observed["catnip"] == -96.0


def test_check_prediction_hard_deviation():
    pred = {"deltas": {"catnip": -100.0}, "stochastic": False}
    before = _obs({"catnip": 500.0})
    after = _obs({"catnip": 500.0})    # nichts passiert → harte Abweichung
    _, ok = loop.check_prediction(pred, before, after)
    assert not ok


def test_check_prediction_stochastic_only_sign_and_magnitude():
    pred = {"deltas": {"furs": 79.5, "manpower": -100.0}, "stochastic": True}
    before = _obs({"furs": 0.0, "manpower": 200.0})
    # Beute weit über EV ist ok (Zufall), solange Vorzeichen/Größenordnung stimmen:
    _, ok = loop.check_prediction(pred, before, _obs({"furs": 150.0, "manpower": 100.0}))
    assert ok
    # Vorzeichen kippt deutlich → Abweichung:
    _, ok = loop.check_prediction(pred, before, _obs({"furs": -200.0, "manpower": 100.0}))
    assert not ok


def test_prediction_mismatch_streak_triggers_after_three():
    """Erst ≥ 3 harte Abweichungen IN FOLGE stoppen (ein Ausreißer nicht)."""
    rt = _StubRuntime()
    brain = Brain(rt)
    act = actions.gather_catnip(10)
    brain._note_prediction(False, act)
    brain._note_prediction(False, act)
    assert rt.agent_mode == "ACTIVE"           # 2 < Schwelle
    brain._note_prediction(True, act)          # Treffer nullt den Streak
    assert brain.mismatch_streak == 0
    brain._note_prediction(False, act)
    brain._note_prediction(False, act)
    assert rt.agent_mode == "ACTIVE"
    brain._note_prediction(False, act)         # dritter Fehlschlag in Folge
    assert rt.agent_mode == "MODEL_MISMATCH"
    assert "G-10" in rt.agent_mode_reason


# ---------------------------------------------------------------- Commit-Grenze

def test_commit_guard_aborts_on_changed_price():
    """G-06/7.4: Re-Read zeigt zu wenig Bestand (Preis/Zustand hat sich seit
    der Planung geändert) → Abbruch der irreversiblen Aktion."""
    act = actions.buy_perk("engineering", "Engineering",
                           prices=[{"name": "paragon", "val": 50}])
    rich = make_snap(resources={"paragon": {"value": 60, "max": 0, "rate": 0}})
    poor = make_snap(resources={"paragon": {"value": 40, "max": 0, "rate": 0}})
    ok, _ = loop.commit_guard(act, rich)
    assert ok
    ok, detail = loop.commit_guard(act, poor)
    assert not ok
    assert "paragon" in detail


def test_commit_guard_without_model_passes():
    """Ohne Kostenmodell (predicted=None) ist nichts prüfbar → ok (dokumentiert)."""
    ok, _ = loop.commit_guard(actions.adore(), make_snap())
    assert ok


# ---------------------------------------------------------------- Zyklus-Smoke

class _StubBrowser:
    """Actor-Ausführung ohne Playwright: evaluate liefert Erfolgs-Dicts."""

    async def evaluate(self, js, args=None):
        return {"clicked": True}


def test_cycle_end_to_end_fills_decision_trace(monkeypatch):
    """Ein voller Async-Zyklus (gestubbter Reader): state_hash, replan_reason,
    predicted/observed_delta/prediction_ok landen im DecisionRecord — und der
    zweite Zyklus klassifiziert den weichen Trigger aus dem Scheduler."""
    snap_before = make_snap(
        resources={"catnip": {"value": 0, "max": 5000, "rate": 0}},
        buildings={"field": {"val": 0, "prices": {"catnip": 10}}})
    snap_after = copy.deepcopy(snap_before)
    next(r for r in snap_after["resources"] if r["name"] == "catnip")["value"] = 10.0

    reads = [copy.deepcopy(snap_before), snap_after]

    async def fake_read(browser):
        return copy.deepcopy(reads.pop(0) if len(reads) > 1 else reads[0])

    monkeypatch.setattr(loop, "read_snapshot", fake_read)
    rt = _StubRuntime()
    rt.browser = _StubBrowser()
    brain = Brain(rt)
    asyncio.run(brain._cycle())

    rec = brain.last_record
    assert rec is not None
    assert rec.selected.action.id == "gather:catnip"
    assert rec.state_hash and len(rec.state_hash) == 16
    assert rec.replan_reason == {"type": "hard", "source": "start",
                                 "detail": "Erster Zyklus"}
    assert rec.predicted == {"deltas": {"catnip": 10.0}, "stochastic": False}
    assert rec.observed_delta == {"catnip": 10.0}
    assert rec.prediction_ok is True
    assert brain.mismatch_streak == 0
    # camelCase-Felder im to_dict (Cockpit erbt sie ohne Whitelist):
    d = rec.to_dict()
    assert d["stateHash"] == rec.state_hash
    assert d["replanReason"]["source"] == "start"
    assert d["predictionOk"] is True
    assert brain._last_cycle_acted is True


def test_cycle_in_safe_stop_only_waits(monkeypatch):
    snap = make_snap(
        resources={"catnip": {"value": 100, "max": 5000, "rate": 1}},
        buildings={"field": {"val": 0, "prices": {"catnip": 10}}})

    async def fake_read(browser):
        return copy.deepcopy(snap)

    monkeypatch.setattr(loop, "read_snapshot", fake_read)
    rt = _StubRuntime()
    rt.browser = _StubBrowser()
    rt.agent_mode = "SAFE_STOP"
    brain = Brain(rt)
    asyncio.run(brain._cycle())
    rec = brain.last_record
    assert rec.selected.action.type == "WAIT"
    assert brain._last_cycle_acted is False
