"""Der Steuerzyklus des Agenten (Spielmechanik-Spec 3.2, vereinfacht).

Pro Zyklus:
    1. Frischen Snapshot lesen und Kennzahlen ableiten
    2. Sicherheitsinvarianten prüfen — Schutzaktion hat Vorrang (G-04)
    3. Phase + aktiven Meilenstein bestimmen (Meta-Controller)
    4. Kandidaten erzeugen und bewerten (Taktik)
    5. Entscheidung als DecisionRecord veröffentlichen (Cockpit!)
    6. Genau eine Aktion/Charge ausführen (Actor) oder bewusst warten
    7. Wirkung beobachten und in den Record schreiben
    8. Meilenstein-Abschlüsse als Narrations-Karte feiern

Pause/Step-Semantik (Cockpit-Spec 20.1):
    pause_requested  → nach der laufenden Aktion anhalten
    step_actions     → genau eine Aktion ausführen, dann wieder Pause
    step_decision    → bis zum nächsten Decision-Commit laufen, dann Pause

Governance (Spec 21/22, G-02/G-06/G-10):
    - AgentMode-Gate: MODEL_MISMATCH → nur READ_ONLY + Verbraucher-Abschalten;
      SAFE_STOP → nur Beobachtung (apply_mode_gate)
    - Commit-Grenze vor IRREVERSIBLE: Re-Read + Precondition (commit_guard)
    - Prognose-vs-Beobachtung mit Streak-Stop (check_prediction)
    - Weckzeit ereignisgetrieben statt festem Tick (brain/scheduler.py)
"""

from __future__ import annotations

import asyncio
import time

from player.driver.actor import Actor
from player.driver.reader import read_snapshot
from player.narrator import Narrator
from player.state import access as A
from player.state.derived import derive

from . import actions, frontier, meta, reset, safety, scheduler, tactics
from .records import Candidate, DecisionRecord, state_hash

# ---------------------------------------------------------------- Governance
# Prognose-Distanzprüfung (G-10/22.2): Toleranzen als dokumentierte Näherung.
# Deterministische Effekte: 15 % relativ + 5 Einheiten absolut + 2 s
# Produktionsdrift (zwischen den beiden Reads läuft das Spiel weiter).
# Stochastische Effekte (Trade/Jagd): nur Vorzeichen-/Größenordnungscheck
# (±100 % + Puffer; Faktor 10 nach oben).
PREDICTION_REL_TOL = 0.15
PREDICTION_ABS_TOL = 5.0
PREDICTION_DRIFT_S = 2.0
# Erst ≥ 3 harte Abweichungen IN FOLGE lösen MODEL_MISMATCH aus — ein
# einzelner Ausreißer (Astro-Event, Race-Bonus, UI-Verzögerung) stoppt nicht.
PREDICTION_MISMATCH_STREAK = 3

MISMATCH_REJECT = "MODEL_MISMATCH: nur lesende/sichernde Aktionen (G-02)"
SAFE_STOP_REJECT = "SAFE_STOP: keine Aktionen, nur Beobachtung"


def apply_mode_gate(candidates: list[Candidate], mode: str) -> None:
    """AgentMode-Gate (G-02/22.2): im MODEL_MISMATCH sind nur READ_ONLY-
    Aktionen und das Abschalten von Verbrauchern (toggle off) zulässig;
    im SAFE_STOP gar keine Aktion — nur Beobachtung (WAIT)."""
    if mode == "ACTIVE":
        return
    for c in candidates:
        a = c.action
        if a.atomicity == actions.READ_ONLY:
            continue   # WAIT/Export bleiben immer möglich
        if mode == "MODEL_MISMATCH" and a.type == "TOGGLE_BUILDING" \
                and not a.exec_spec.get("on", True):
            continue   # „riskante Verbraucher abschalten" bleibt erlaubt (22.2)
        c.feasible = False
        c.reject_reason = MISMATCH_REJECT if mode == "MODEL_MISMATCH" else SAFE_STOP_REJECT


def commit_guard(action, snap: dict) -> tuple[bool, str]:
    """Commit-Grenze (21.3, G-06/7.4): unmittelbar vor einer irreversiblen
    Aktion wird der Zustand erneut gelesen (Aufrufer) und hier werden die
    Kosten aus der Prognose gegen den frischen Bestand geprüft. Ohne
    Kostenmodell (predicted=None) ist nichts prüfbar → ok (dokumentiert)."""
    deltas = (action.predicted or {}).get("deltas") or {}
    for res in sorted(deltas):
        need = -deltas[res]
        if need <= 0:
            continue
        have = A.res_value(snap, res)
        if have + 1e-6 < need:
            return False, f"{res}: benötigt {need:.0f}, vorhanden {have:.0f}"
    return True, "Preconditions ok"


def check_prediction(predicted: dict, before: dict, after: dict) -> tuple[dict, bool]:
    """Distanzvergleich beobachtete Δ vs. Prognose (G-10). before/after sind
    _observables-Dicts. Rückgabe: (observed_delta, prediction_ok)."""
    deltas = predicted.get("deltas") or {}
    stochastic = bool(predicted.get("stochastic"))
    observed: dict[str, float] = {}
    ok = True
    for res in sorted(deltas):
        pred = deltas[res]
        obs = after["resources"].get(res, 0.0) - before["resources"].get(res, 0.0)
        observed[res] = round(obs, 3)
        drift = abs(before.get("rates", {}).get(res, 0.0)) * PREDICTION_DRIFT_S
        if stochastic:
            tol = abs(pred) + PREDICTION_ABS_TOL + drift
            if pred > 0 and obs < -tol:
                ok = False        # Vorzeichen kippt
            elif pred < 0 and obs > tol:
                ok = False
            elif abs(obs) > abs(pred) * 10 + tol:
                ok = False        # Größenordnung gesprengt
        else:
            tol = PREDICTION_REL_TOL * abs(pred) + PREDICTION_ABS_TOL + drift
            if abs(obs - pred) > tol:
                ok = False
    return observed, ok


class Brain:
    def __init__(self, runtime) -> None:
        self.rt = runtime
        self.actor = Actor(runtime.browser, runtime.config.click_glow_ms)
        self.narrator = Narrator(runtime.bus)
        self._done_milestones: set[str] = set()
        self._first_cycle = True
        self._last_wait_reason: str | None = None   # WAIT-Verdichtung (Spec 2.6)
        self.last_record: DecisionRecord | None = None
        self.last_meta: meta.MetaView | None = None
        self.last_bottleneck: dict | None = None
        self.last_reset_eval: dict | None = None
        self.last_lambda_top: list[dict] = []   # λ-Topliste (#34, Cockpit)
        self.force_reset = False   # Debug-Control aus dem Cockpit
        # Verlauf der Paragon-Projektion für die Speedrun-Regel (Spec 20.4):
        self.paragon_samples: list[tuple[float, int]] = []
        self.run_started = time.time()
        self.decisions_made = 0
        # --- Governance (G-02/G-10, Kap. 21) ---
        self.mismatch_streak = 0            # aufeinanderfolgende Prognose-Fehler
        self._prev_signature: dict | None = None   # Vorzyklus für harte Trigger
        self._prev_mode = "ACTIVE"
        self._last_exec_failed = False
        self._last_snap: dict | None = None
        self._last_cycle_acted = False      # letzte Entscheidung war eine echte Aktion
        self._next_reason: dict | None = None       # geplanter Weckgrund (21.2)
        self._reset_blocked_warned = False

    # ------------------------------------------------------------ Hauptschleife

    async def run(self) -> None:
        bus = self.rt.bus
        cfg = self.rt.config
        while True:
            # --- Pause / Step ---
            if self.rt.pause_requested and self.rt.step_actions_remaining <= 0 \
                    and not self.rt.step_until_decision:
                if self.rt.state != "PAUSED":
                    self.rt.set_state("PAUSED", "Pause aktiv")
                await asyncio.sleep(0.3)
                continue

            try:
                await self._cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                bus.publish("model.error", {"error": f"Brain-Zyklus: {exc}"})
                self.rt.set_state("DEGRADED", str(exc))
                await asyncio.sleep(3.0)
                continue

            # Step-Kredite verbrauchen:
            if self.rt.step_actions_remaining > 0:
                self.rt.step_actions_remaining -= 1
            if self.rt.step_until_decision:
                self.rt.step_until_decision = False
                self.rt.pause_requested = True

            # Ereignisgetriebenes Replanning (21.2): nach einer echten Aktion
            # sofort wieder planen (der Zustand hat sich gerade geändert);
            # beim Warten weckt der Scheduler zum nächsten relevanten Ereignis.
            if self._last_cycle_acted:
                delay = cfg.decision_interval
                self._next_reason = None
            else:
                delay, self._next_reason = scheduler.next_wakeup(
                    self._last_snap or {},
                    (self.last_bottleneck or {}).get("etaSeconds"),
                    cfg.decision_interval)
            await asyncio.sleep(delay)

    # ------------------------------------------------------------ Ein Zyklus

    async def _cycle(self) -> None:
        bus = self.rt.bus
        self.rt.set_state("PLANNING", "")

        snap = derive(await read_snapshot(self.rt.browser))
        self._last_snap = snap
        self._last_cycle_acted = False
        mode = getattr(self.rt, "agent_mode", "ACTIVE")

        # --- Trigger-Klassifikation (21.1): hart schlägt weich ---
        sig = scheduler.signature(snap)
        hard = scheduler.classify_hard_trigger(self._prev_signature, sig,
                                               self._last_exec_failed)
        if mode != "ACTIVE" and mode != self._prev_mode:
            hard = {"type": "hard", "source": "mismatch",
                    "detail": f"AgentMode → {mode}"}
        self._prev_signature = sig
        self._prev_mode = mode
        self._last_exec_failed = False
        if self._first_cycle:
            replan_reason = {"type": "hard", "source": "start", "detail": "Erster Zyklus"}
        elif hard:
            replan_reason = hard
        else:
            replan_reason = self._next_reason or {
                "type": "soft", "source": "interval", "detail": "Replanning-Intervall"}
        trigger = replan_reason["detail"]
        self._first_cycle = False

        # --- Safety (Vorrang) ---
        safety_result = safety.check(snap)
        meta_view = meta.evaluate(snap)
        self.last_meta = meta_view
        self._announce_milestones(meta_view)

        # --- Ausbaugrenzen-Wächter: naht eine nicht implementierte Schicht? ---
        known = set(self.rt.frontier_fired) | self.rt.frontier_dismissed
        for notice in frontier.check(snap, meta_view.run_type, known):
            self.rt.frontier_notify(notice)

        # --- Reset-Bewertung (Spec Kap. 20) ---
        self.paragon_samples.append((time.time(), snap["derived"]["resetParagon"]))
        if len(self.paragon_samples) > 4000:
            del self.paragon_samples[:2000]
        reset_eval = reset.evaluate(snap, meta_view.run_type, meta_view.next_perk,
                                    self.paragon_samples)
        self.last_reset_eval = reset_eval
        if (reset_eval["recommended"] or self.force_reset) and mode != "ACTIVE":
            # G-02: Reset ist irreversibel — im MODEL_MISMATCH/SAFE_STOP gesperrt.
            self.force_reset = False
            if not self._reset_blocked_warned:
                self._reset_blocked_warned = True
                bus.publish("model.warning", {
                    "error": f"Reset-Empfehlung im AgentMode {mode} blockiert (G-02)"})
        elif reset_eval["recommended"] or self.force_reset:
            self.force_reset = False
            self._reset_blocked_warned = False
            if not reset_eval["recommended"]:
                reset_eval = dict(reset_eval)
                reset_eval["reason"] = "Manuell ausgelöst (Cockpit-Debug)"
            self._publish_run_summary(meta_view)
            self.rt.set_state("EXECUTING", "Pre-Reset-Transaktion")
            await reset.execute_reset(self.rt, reset_eval)
            self._done_milestones = set()      # neuer Run, neue Meilensteine
            self._last_wait_reason = None
            self._first_cycle = True
            self._prev_signature = None        # neuer Run = neue Vergleichsbasis
            self.paragon_samples = []
            self.run_started = time.time()
            return

        # Kandidaten immer vollständig erzeugen (Cockpit zeigt Alternativen).
        # Schutzaktionen sind seit dem Schleifen-Bugfix ABGESTUFTE Kandidaten
        # (Leitplanke statt Monopol, G-04): food-neutrale Fortschritte wie
        # Forschung konkurrieren normal weiter.
        candidates, bottleneck = tactics.generate(snap, meta_view, safety_result)
        if safety_result.critical and safety_result.candidates:
            candidates.extend(safety_result.candidates)
            candidates.sort(key=lambda c: (-c.score, c.action.id))
        # AgentMode-Gate (G-02): im MODEL_MISMATCH/SAFE_STOP werden nicht
        # zulässige Kandidaten infeasible — WAIT bleibt immer möglich.
        apply_mode_gate(candidates, mode)
        # Kaufregel (Spec 10.3): nur Aktionen mit positivem NetValue; sonst WAIT.
        selected = next((c for c in candidates if c.feasible and c.score > 0),
                        next(c for c in candidates if c.action.type == "WAIT"))
        # Deadlock-Auflösung (Spec 22.3): kein positiver Kandidat UND WAIT
        # ohne endliche Weckbedingung → deterministisch (a) Horizont
        # verdoppeln, (b) Suchraum lockern, (c) Frontier-Meldung „deadlock".
        # Nur im ACTIVE-Modus (im MISMATCH/SAFE_STOP ist Nichtstun gewollt);
        # Sicherheitsinvarianten werden nie gelockert (22.3 Satz 2).
        if mode == "ACTIVE" and selected.action.type == "WAIT" \
                and tactics.is_deadlock(candidates, bottleneck, snap):
            candidates, bottleneck, dl = tactics.resolve_deadlock(
                snap, meta_view, safety_result)
            apply_mode_gate(candidates, mode)
            selected = next((c for c in candidates if c.feasible and c.score > 0),
                            next(c for c in candidates if c.action.type == "WAIT"))
            trigger = f"DEADLOCK: Auflösung Stufe {dl['stage']} (22.3)"
            replan_reason = {"type": "hard", "source": "deadlock",
                             "detail": dl["detail"]}
            notice = dl.get("notice")
            if notice and notice["id"] not in known:
                self.rt.frontier_notify(notice)
        if "safety" in selected.components and safety_result.reason:
            trigger = f"SAFETY: {safety_result.reason}"
            replan_reason = {"type": "hard", "source": "safety",
                             "detail": safety_result.reason}
        self.last_bottleneck = bottleneck

        # WAIT-Verdichtung: identisches Warten (gleiches Ziel, gleicher Engpass)
        # nicht jede Sekunde erneut ins Journal spülen. Die ETA im Text ändert
        # sich laufend, deshalb ist der Schlüssel Ziel+Engpass.
        if selected.action.type == "WAIT":
            wait_key = f"{meta_view.objective_label}|{(bottleneck or {}).get('resource')}"
            if wait_key == self._last_wait_reason:
                self.rt.set_state("WAITING", selected.action.exec_spec.get("reason", ""))
                return
            self._last_wait_reason = wait_key
        else:
            self._last_wait_reason = None

        self.decisions_made += 1
        record = DecisionRecord(
            trigger=trigger,
            phase=meta_view.phase,
            run_type=meta_view.run_type,
            objective=meta_view.objective_label,
            bottleneck=bottleneck,
            candidates=candidates,
            selected=selected,
            reason=tactics.reason_for(selected, bottleneck),
            safety=safety_result.view,
            game_time={"year": snap["calendar"]["year"], "season": snap["calendar"]["seasonName"],
                       "day": snap["calendar"]["day"]},
            state_hash=state_hash(snap),
            replan_reason=replan_reason,
            predicted=selected.action.predicted,
        )
        self.last_record = record
        bus.publish("decision.committed", record.to_dict())
        # λ-Topliste fürs Cockpit (#34): bewusst billige Doppelrechnung des
        # Pfad-λ (deterministisch, 2 ETA-Auswertungen je Preisposition) —
        # generate() kapselt seinen λ-Satz, der Payload braucht nur die Top-N.
        lam, lam_rate = tactics.path_lambdas(snap, meta_view)
        bus.publish("plan.updated", self._plan_payload(
            meta_view, bottleneck, tactics.lambda_top(lam, lam_rate)))
        self.narrator.track_bottleneck((bottleneck or {}).get("resource"),
                                       meta_view.objective_label)

        # --- Ausführen ---
        action = selected.action
        if action.type == "WAIT":
            self.rt.set_state("WAITING", action.exec_spec.get("reason", ""))
            record.execution = {"state": "WAITING", "method": "none"}
            bus.publish("execution.result", {"decisionId": record.decision_id,
                                             "ok": True, "method": "none",
                                             "detail": "WAIT", "observed": None})
            return

        self.rt.set_state("EXECUTING", action.label)
        base_snap = snap
        if action.atomicity == actions.IRREVERSIBLE:
            # Commit-Grenze (21.3, G-06/7.4): Re-Read + Precondition-Check
            # unmittelbar vor der Ausführung; schlägt er fehl → Abbruch,
            # kein Retry im selben Zyklus.
            base_snap = derive(await read_snapshot(self.rt.browser))
            guard_ok, guard_detail = commit_guard(action, base_snap)
            if not guard_ok:
                detail = f"Commit-Grenze (G-06/7.4): {guard_detail}"
                selected.reject_reason = detail
                record.execution = {"state": "ABORTED", "method": "none",
                                    "detail": detail}
                bus.publish("execution.result", {
                    "decisionId": record.decision_id, "ok": False,
                    "method": "none", "detail": detail, "observed": None})
                self._last_exec_failed = True   # harter Trigger (21.1)
                self.rt.set_state("RUNNING", "")
                return
        before = _observables(base_snap)
        result = await self.actor.execute(action.exec_spec)
        self._last_cycle_acted = True

        # --- Beobachten ---
        await asyncio.sleep(0.3)
        after_snap = derive(await read_snapshot(self.rt.browser))
        after_obs = _observables(after_snap)
        observed = _describe_effect(before, after_obs)
        record.execution = {"state": "COMPLETED" if result["ok"] else "FAILED", **result}
        record.observed = observed
        # Prognose-vs-Beobachtung (G-10): nur bei erfolgreicher Ausführung
        # und vorhandenem Modell (predicted != None).
        if result["ok"] and action.predicted and action.predicted.get("deltas"):
            record.observed_delta, record.prediction_ok = check_prediction(
                action.predicted, before, after_obs)
            self._note_prediction(record.prediction_ok, action)
        bus.publish("execution.result", {
            "decisionId": record.decision_id,
            "ok": result["ok"], "method": result["method"],
            "detail": result.get("detail", ""), "observed": observed,
        })
        if not result["ok"]:
            self._last_exec_failed = True       # harter Trigger (21.1)
            bus.publish("model.warning",
                        {"error": f"Aktion fehlgeschlagen: {action.label} — {result.get('detail')}"})
        self.narrator.on_action_executed(action.type, action.label, result["ok"])
        # Forschung als P2-Karte — außer sie ist selbst Meilenstein (die Karte
        # kommt dann von _announce_milestones, keine Dubletten):
        milestone_techs = {m.target["name"] for m in meta.P0_MILESTONES
                           if m.target and m.target["kind"] == "research"}
        for tech_name in after_obs["techs"] - before["techs"]:
            if tech_name not in milestone_techs:
                label = next((t["label"] for t in after_snap.get("science", {}).get("techs", [])
                              if t["name"] == tech_name), tech_name)
                self.narrator.on_research(label, meta_view.objective_label)
        self.rt.set_state("RUNNING", "")

    # ------------------------------------------------------------ Prognosen

    def _note_prediction(self, ok: bool, action) -> None:
        """Streak-Zähler (G-10): erst PREDICTION_MISMATCH_STREAK harte
        Abweichungen IN FOLGE lösen MODEL_MISMATCH aus, ein Treffer nullt."""
        if ok:
            self.mismatch_streak = 0
            return
        self.mismatch_streak += 1
        self.rt.bus.publish("model.warning", {
            "error": (f"Prognose-Abweichung ({self.mismatch_streak}/"
                      f"{PREDICTION_MISMATCH_STREAK}): {action.label}")})
        if self.mismatch_streak >= PREDICTION_MISMATCH_STREAK:
            enter = getattr(self.rt, "enter_model_mismatch", None)
            if enter is not None:
                enter(f"{PREDICTION_MISMATCH_STREAK} Prognose-Abweichungen in "
                      f"Folge (G-10), zuletzt: {action.label}",
                      source="prediction")

    # ------------------------------------------------------------ Meilensteine

    def _announce_milestones(self, meta_view: meta.MetaView) -> None:
        done_now = {m["id"] for m in meta_view.milestones if m["state"] == "done"}
        if not self._done_milestones:
            self._done_milestones = done_now   # Startbestand nicht feiern
            return
        for mid in sorted(done_now - self._done_milestones):
            label = next((m["label"] for m in meta_view.milestones if m["id"] == mid), mid)
            nxt = meta_view.objective_label
            self.rt.bus.publish("narrative.milestone", {
                "priority": "P2",
                "title": f"Meilenstein erreicht: {label}",
                "body": f"Nächstes Ziel: {nxt}",
            })
        self._done_milestones = done_now

    def _publish_run_summary(self, meta_view: meta.MetaView) -> None:
        """Session-Summary am Run-Ende (Cockpit-Spec 17.5, deterministisch)."""
        runtime_min = (time.time() - self.run_started) / 60
        done = sum(1 for m in meta_view.milestones if m["state"] == "done")
        self.rt.bus.publish("narrative.chapter", {
            "priority": "P1",
            "title": "Run-Zusammenfassung",
            "body": (f"{runtime_min:.0f} min Laufzeit · {self.decisions_made} Entscheidungen · "
                     f"{done} Meilensteine · Run-Typ {meta_view.run_type}"),
        })
        self.decisions_made = 0

    def _plan_payload(self, meta_view: meta.MetaView, bottleneck: dict | None,
                      lambda_top: list[dict] | None = None) -> dict:
        payload = meta_view.to_dict()
        payload["bottleneck"] = bottleneck
        payload["reset"] = self.last_reset_eval
        # λ-Topliste (#34): frisch aus dem Zyklus oder der letzte Stand
        # (Status-Payload außerhalb des Zyklus, runtime.status_payload).
        if lambda_top is not None:
            self.last_lambda_top = lambda_top
        payload["lambdaTop"] = self.last_lambda_top
        return payload


# ---------------------------------------------------------------- Beobachtung

def _observables(snap: dict) -> dict:
    """Kompakte Größen für den Vorher/Nachher-Vergleich einer Aktion."""
    return {
        "buildings": {b["name"]: b["val"] for b in snap.get("buildings", [])},
        "techs": {t["name"] for t in snap.get("science", {}).get("techs", []) if t["researched"]},
        "kittens": snap.get("village", {}).get("kittens", 0),
        "jobs": {j["name"]: j["value"] for j in snap.get("village", {}).get("jobs", [])},
        "resources": {r["name"]: r["value"] for r in snap.get("resources", [])},
        # Raten für die Drift-Toleranz der Prognoseprüfung (G-10):
        "rates": {r["name"]: r.get("perSec", 0.0) for r in snap.get("resources", [])},
    }


def _describe_effect(before: dict, after: dict) -> str:
    """Menschlich lesbare Zusammenfassung der beobachteten Änderung."""
    parts: list[str] = []
    for name, val in after["buildings"].items():
        if val > before["buildings"].get(name, 0):
            parts.append(f"{name} → {val}")
    for tech_name in after["techs"] - before["techs"]:
        parts.append(f"erforscht: {tech_name}")
    for job, val in after["jobs"].items():
        d = val - before["jobs"].get(job, 0)
        if d:
            parts.append(f"{job} {'+' if d > 0 else ''}{d}")
    if not parts:
        # größte Ressourcenänderung zeigen
        deltas = [(abs(v - before["resources"].get(k, 0)), k, v - before["resources"].get(k, 0))
                  for k, v in after["resources"].items()]
        deltas.sort(reverse=True)
        if deltas and deltas[0][0] > 0.5:
            _, k, d = deltas[0]
            parts.append(f"{k} {'+' if d > 0 else ''}{d:.0f}")
    return ", ".join(parts) if parts else "keine messbare Änderung"
