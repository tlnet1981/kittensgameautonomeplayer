"""Tests der M3-Logik: Run-Typen, Reset-Bewertung, Metaphysics-Ziel —
plus die 12-Schritt-Pre-Reset-Transaktion (Spec 20.3, execute_reset)."""

import asyncio
import copy

from config import Config
from player.brain import meta, reset
from player.events import EventBus
from tests.helpers import make_snap


def _with_prestige(snap, paragon=0, karma=0, perks=None):
    snap["prestige"] = {"paragon": paragon, "burnedParagon": 0, "karma": karma,
                        "perks": perks or []}
    return snap


def test_first_run_detection():
    snap = _with_prestige(make_snap())
    assert meta.determine_run(snap) == "FIRST_RUN"


def test_price_ratio_run_after_first_reset():
    snap = _with_prestige(make_snap(), paragon=40, karma=1)
    assert meta.determine_run(snap) == "PRICE_RATIO_RUN"
    target = meta.next_metaphysics_target(snap)
    assert target["name"] == "engeneering"   # sic — so heißt der Perk im Spiel


def test_metaphysics_order_progression():
    perks = [
        {"name": "engeneering", "label": "Engineering", "researched": True,
         "unlocked": True, "prices": [{"name": "paragon", "val": 5}]},
        {"name": "diplomacy", "label": "Diplomacy", "researched": True,
         "unlocked": True, "prices": [{"name": "paragon", "val": 5}]},
        {"name": "goldenRatio", "label": "Golden Ratio", "researched": False,
         "unlocked": True, "prices": [{"name": "paragon", "val": 50}]},
    ]
    snap = _with_prestige(make_snap(), paragon=60, karma=2, perks=perks)
    target = meta.next_metaphysics_target(snap)
    assert target["name"] == "goldenRatio"


def test_paragon_run_when_chain_complete():
    perks = [{"name": n, "label": n, "researched": True, "unlocked": True,
              "prices": [{"name": "paragon", "val": 1}]}
             for n in meta.METAPHYSICS_ORDER]
    snap = _with_prestige(make_snap(), paragon=100, karma=5, perks=perks)
    assert meta.determine_run(snap) == "PARAGON_RUN"


def test_first_reset_threshold():
    # 100 Kitten → Projektion 30 → noch kein Reset
    snap = _with_prestige(make_snap(kittens=100))
    ev = reset.evaluate(snap, "FIRST_RUN", None)
    assert not ev["recommended"]
    assert ev["projection"] == 30

    # 110 Kitten → Projektion 40 ≥ 35 → Reset empfohlen
    snap = _with_prestige(make_snap(kittens=110))
    ev = reset.evaluate(snap, "FIRST_RUN", None)
    assert ev["recommended"]


def test_price_ratio_reset_funds_next_perk():
    perk = {"name": "goldenRatio", "label": "Golden Ratio", "researched": False,
            "unlocked": True, "prices": [{"name": "paragon", "val": 50}]}
    # 10 Paragon vorhanden, Projektion 25 → 35 < 50 → kein Reset
    snap = _with_prestige(make_snap(kittens=95), paragon=10, karma=1)
    ev = reset.evaluate(snap, "PRICE_RATIO_RUN", perk)
    assert not ev["recommended"]

    # 30 Paragon vorhanden, Projektion 25 → 55 ≥ 50 → Reset
    snap = _with_prestige(make_snap(kittens=95), paragon=30, karma=1)
    ev = reset.evaluate(snap, "PRICE_RATIO_RUN", perk)
    assert ev["recommended"]

    # Projektion unter Mindestgewinn → kein Mini-Run-Reset
    snap = _with_prestige(make_snap(kittens=75), paragon=100, karma=1)
    ev = reset.evaluate(snap, "PRICE_RATIO_RUN", perk)
    assert ev["projection"] == 5
    assert not ev["recommended"]


def test_reset_value_prefers_continuing_with_strong_growth():
    # Starkes Kitten-Wachstum: Weiterlaufen bankt in T mehr Paragon als ein
    # Neustart mit linearer Rampe → ResetValue < 0 → kein Reset trotz
    # erfüllter FIRST-Schwelle (Spec 20.1).
    snap = _with_prestige(make_snap(kittens=110, max_kittens=150))
    snap["village"]["kittensPerSec"] = 0.05
    ev = reset.evaluate(snap, "FIRST_RUN", None)
    assert not ev["recommended"]
    assert ev["resetValue"]["resetValue"] < 0
    assert "Weiterlaufen dominiert" in ev["reason"]


def test_reset_value_prefers_reset_without_growth():
    # Kein Wachstum mehr (Housing voll, keine Ankunftsrate): der Neustart
    # gewinnt über die Rampe → ResetValue > 0 → Reset.
    snap = _with_prestige(make_snap(kittens=110, max_kittens=110))
    ev = reset.evaluate(snap, "FIRST_RUN", None)
    assert ev["recommended"]
    assert ev["resetValue"]["resetValue"] > 0
    # Beide V-Werte stehen im reason-Text (Cockpit-Transparenz):
    assert "V(neu)" in ev["reason"] and "V(weiter)" in ev["reason"]


def test_perk_milestone_becomes_target():
    perks = [{"name": "engeneering", "label": "Engineering", "researched": False,
              "unlocked": True, "prices": [{"name": "paragon", "val": 5}]}]
    snap = _with_prestige(
        make_snap(
            resources={"catnip": {"value": 40000, "max": 50000, "rate": 50},
                       "paragon": {"value": 40, "max": 0, "rate": 0}},
            techs={"metaphysics": {"researched": True, "prices": {"science": 100}},
                   "philosophy": {"researched": True, "prices": {"science": 100}}},
            jobs={"farmer": 5}, kittens=5, catnip_field_base=60,
        ),
        paragon=40, karma=1, perks=perks,
    )
    # Alle P0-Meilensteine künstlich als erledigt markieren ist aufwendig —
    # stattdessen direkt die Perk-Milestone-Erzeugung prüfen:
    ms = meta._perk_milestones(snap, perks[0])
    assert ms[-1].target == {"kind": "perk", "name": "engeneering"}

    # und das Taktik-Ziel „perk" liefert einen kaufbaren Kandidaten:
    from player.brain import safety, tactics
    from player.brain.meta import Milestone
    mview = meta.evaluate(snap)
    mview.active = ms[-1]
    cands, bn = tactics.generate(snap, mview, safety.check(snap))
    perk_cand = next(c for c in cands if c.action.id == "perk:engeneering")
    assert perk_cand.feasible
    assert perk_cand.action.irreversible
    assert perk_cand.action.exec_spec["panel"] == "Metaphysics"


# =====================================================================
# Pre-Reset-Transaktion (Spec 20.3, 12 Schritte) — Mock-Technik wie
# test_governance (StubRuntime + gestubbter Browser, reset.read_snapshot
# wird gemonkeypatcht, POST_RESET_WAIT_S auf 0 gesetzt).

class _FakeBrowser:
    """evaluate liefert Antworten nach JS-Substring-Markern; alles andere
    bekommt {"already": True} (Tab schon aktiv / Klick ohne Fehler)."""

    def __init__(self, script=None):
        self.js_calls: list[tuple[str, object]] = []
        self.script = list(script or [])
        self.reinitialized = False

    async def evaluate(self, js, args=None):
        self.js_calls.append((js, args))
        for marker, resp in self.script:
            if marker in js:
                return resp
        return {"already": True}

    def called(self, marker: str) -> bool:
        return any(marker in js for js, _ in self.js_calls)

    async def export_save(self):
        return "SAVEDATA"

    async def reinitialize(self, timeout_s=90):
        self.reinitialized = True


class _ResetRuntime:
    def __init__(self, browser):
        self.bus = EventBus()
        self.browser = browser
        self.config = Config()
        self.agent_mode = "ACTIVE"
        self.store = None


def _steps(rt):
    return [(e["payload"]["step"], e["payload"]["status"])
            for e in rt.bus.recent if e["type"] == "reset.step"]


def _run_execute(snap, reset_eval, monkeypatch, browser=None):
    async def fake_read(_browser):
        return copy.deepcopy(snap)

    monkeypatch.setattr(reset, "read_snapshot", fake_read)
    monkeypatch.setattr(reset, "POST_RESET_WAIT_S", 0.0)
    rt = _ResetRuntime(browser or _FakeBrowser())
    result = asyncio.run(reset.execute_reset(rt, reset_eval))
    return result, rt


def _eval_stub(**kw):
    ev = {"projection": 40, "paragonNow": 0, "reason": "Test",
          "runType": "FIRST_RUN", "pendingChallenge": None}
    ev.update(kw)
    return ev


def test_evaluate_exposes_run_type_and_tap_plan():
    snap = _with_prestige(make_snap(kittens=110))
    ev = reset.evaluate(snap, "FIRST_RUN", None)
    assert ev["runType"] == "FIRST_RUN"
    assert ev["tapPlan"] == []   # keine Religion-Daten → kein TAP-Schritt


def test_execute_reset_runs_all_twelve_steps_in_order(monkeypatch):
    snap = _with_prestige(make_snap(kittens=110))
    browser = _FakeBrowser(script=[
        ("ch.pending = true", {"before": False, "pending": True}),
        ("onRunReset", True),
    ])
    ok, rt = _run_execute(snap, _eval_stub(
        pendingChallenge={"name": "winterIsComing", "label": "Winter"}),
        monkeypatch, browser)
    assert ok is True
    steps = _steps(rt)
    assert [n for n, _ in steps] == list(range(1, 13))
    by_step = dict(steps)
    assert by_step[1] == "done"                  # Save-Export
    assert by_step[2] == "skipped"               # kein CHALLENGE_RUN
    assert by_step[4] == "done"                  # Paragon-Formel verifiziert
    assert by_step[10] == "done"                 # Assertions bestanden
    assert by_step[11] == "done"
    # Atomarer Reset + pending-Challenge liefen wirklich:
    assert browser.called("resetAutomatic")
    assert browser.called("ch.pending = true")
    assert browser.reinitialized
    # Kapitelkarte + committed-Event wie bisher:
    types = [e["type"] for e in rt.bus.recent]
    assert "reset.committed" in types
    assert types.count("narrative.chapter") == 2


def test_execute_reset_runs_tap_and_conversions(monkeypatch):
    # Snapshot mit lohnendem TAP + vollem Alicorn-Batch + Anachronomancy:
    snap = _with_prestige(make_snap(
        resources={"faith": {"value": 500, "max": 200000, "rate": 50},
                   "alicorn": {"value": 50, "max": 0, "rate": 0}},
        jobs={"priest": 5}, kittens=110,
        religion={"worship": 10000, "epiphany": 0.1, "transcendenceTier": 0,
                  "upgrades": [
                      {"name": "apocripha", "label": "Apocrypha", "val": 1,
                       "on": 1, "unlocked": True, "noStackable": True,
                       "prices": []},
                      {"name": "transcendence", "label": "Transcendence",
                       "val": 1, "on": 1, "unlocked": True,
                       "noStackable": True, "prices": []}]},
    ), perks=[{"name": "anachronomancy", "label": "Anachronomancy",
               "researched": True, "unlocked": True,
               "prices": [{"name": "paragon", "val": 125}]}])
    browser = _FakeBrowser(script=[
        ("_getTranscendNextPrice", {"before": 0, "after": 1, "paid": 0.0118}),
        ("addResEvent(\"alicorn\"", {"batches": 2, "before": 0.0, "after": 2.0}),
    ])
    ok, rt = _run_execute(snap, _eval_stub(), monkeypatch, browser)
    assert ok is True
    by_step = dict(_steps(rt))
    assert by_step[5] == "done"                  # TAP ausgeführt
    assert by_step[6] == "done"                  # Alicorn-Konvertierung
    assert browser.called("_getTranscendNextPrice")   # Transcend-Kern-JS
    assert browser.called("addResEvent(\"alicorn\"")  # Alicorn→TC-Kern-JS


def test_hard_assertion_aborts_without_reset(monkeypatch):
    # ≥ 3 TC ohne Anachronomancy → Schritt 10 bricht ab, KEIN Reset (I-02):
    snap = _with_prestige(make_snap(
        kittens=110,
        resources={"timeCrystal": {"value": 10, "max": 0, "rate": 0}}))
    browser = _FakeBrowser()
    ok, rt = _run_execute(snap, _eval_stub(), monkeypatch, browser)
    assert ok is False
    assert not browser.called("resetAutomatic")
    steps = _steps(rt)
    assert steps[-1] == (10, "failed")
    assert not any(n in (11, 12) for n, _ in steps)
    warnings = [e for e in rt.bus.recent if e["type"] == "model.warning"]
    assert any("Schritt 10" in w["payload"]["error"] for w in warnings)


def test_challenge_gate_aborts_at_step_two(monkeypatch):
    # CHALLENGE_RUN mit noch AKTIVER Challenge → 18.4-Gate schlägt in
    # Schritt 2 fehl, Transaktion endet ohne Reset:
    snap = _with_prestige(make_snap(
        kittens=110,
        challenges=[{"name": "anarchy", "active": True, "unlocked": True}]))
    browser = _FakeBrowser()
    ok, rt = _run_execute(snap, _eval_stub(runType="CHALLENGE_RUN"),
                          monkeypatch, browser)
    assert ok is False
    assert not browser.called("resetAutomatic")
    assert _steps(rt)[-1] == (2, "failed")


def test_optional_step_failure_does_not_abort(monkeypatch):
    # Perk bezahlbar, aber der Button ist nicht klickbar → Schritt 3 loggt
    # "failed", die Transaktion läuft weiter und der Reset findet statt:
    snap = _with_prestige(make_snap(
        kittens=110,
        resources={"paragon": {"value": 40, "max": 0, "rate": 0}}),
        paragon=40,
        perks=[{"name": "engeneering", "label": "Engineering",
                "researched": False, "unlocked": True,
                "prices": [{"name": "paragon", "val": 5}]}])
    browser = _FakeBrowser(script=[
        ("btnTitle", {"error": "disabled"}),     # jeder Button-Klick scheitert
    ])
    ok, rt = _run_execute(snap, _eval_stub(), monkeypatch, browser)
    assert ok is True
    assert browser.called("resetAutomatic")
    statuses = dict(_steps(rt))
    assert statuses[3] == "failed"
    assert statuses[11] == "done"
