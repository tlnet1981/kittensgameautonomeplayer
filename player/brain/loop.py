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
"""

from __future__ import annotations

import asyncio
import time

from player.driver.actor import Actor
from player.driver.reader import read_snapshot
from player.narrator import Narrator
from player.state import access as A
from player.state.derived import derive

from . import frontier, meta, reset, safety, tactics
from .records import Candidate, DecisionRecord


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
        self.force_reset = False   # Debug-Control aus dem Cockpit
        # Verlauf der Paragon-Projektion für die Speedrun-Regel (Spec 20.4):
        self.paragon_samples: list[tuple[float, int]] = []
        self.run_started = time.time()
        self.decisions_made = 0

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

            await asyncio.sleep(cfg.decision_interval)

    # ------------------------------------------------------------ Ein Zyklus

    async def _cycle(self) -> None:
        bus = self.rt.bus
        self.rt.set_state("PLANNING", "")

        snap = derive(await read_snapshot(self.rt.browser))
        trigger = "Erster Zyklus" if self._first_cycle else "Replanning-Intervall"
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
        if reset_eval["recommended"] or self.force_reset:
            self.force_reset = False
            if not reset_eval["recommended"]:
                reset_eval = dict(reset_eval)
                reset_eval["reason"] = "Manuell ausgelöst (Cockpit-Debug)"
            self._publish_run_summary(meta_view)
            self.rt.set_state("EXECUTING", "Pre-Reset-Transaktion")
            await reset.execute_reset(self.rt, reset_eval)
            self._done_milestones = set()      # neuer Run, neue Meilensteine
            self._last_wait_reason = None
            self._first_cycle = True
            self.paragon_samples = []
            self.run_started = time.time()
            return

        # Kandidaten immer vollständig erzeugen (Cockpit zeigt Alternativen);
        # eine nötige Schutzaktion wird mit Vorrang eingereiht (G-04).
        candidates, bottleneck = tactics.generate(snap, meta_view, safety_result)
        if not safety_result.ok and safety_result.action is not None:
            protective = Candidate(safety_result.action, 10.0, {"safety": 10.0})
            candidates.insert(0, protective)
            trigger = f"SAFETY: {safety_result.reason}"
        # Kaufregel (Spec 10.3): nur Aktionen mit positivem NetValue; sonst WAIT.
        selected = next((c for c in candidates if c.feasible and c.score > 0),
                        next(c for c in candidates if c.action.type == "WAIT"))
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
        )
        self.last_record = record
        bus.publish("decision.committed", record.to_dict())
        bus.publish("plan.updated", self._plan_payload(meta_view, bottleneck))
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
        before = _observables(snap)
        result = await self.actor.execute(action.exec_spec)

        # --- Beobachten ---
        await asyncio.sleep(0.3)
        after_snap = derive(await read_snapshot(self.rt.browser))
        observed = _describe_effect(before, _observables(after_snap))
        record.execution = {"state": "COMPLETED" if result["ok"] else "FAILED", **result}
        record.observed = observed
        bus.publish("execution.result", {
            "decisionId": record.decision_id,
            "ok": result["ok"], "method": result["method"],
            "detail": result.get("detail", ""), "observed": observed,
        })
        if not result["ok"]:
            bus.publish("model.warning",
                        {"error": f"Aktion fehlgeschlagen: {action.label} — {result.get('detail')}"})
        self.narrator.on_action_executed(action.type, action.label, result["ok"])
        # Forschung als P2-Karte — außer sie ist selbst Meilenstein (die Karte
        # kommt dann von _announce_milestones, keine Dubletten):
        milestone_techs = {m.target["name"] for m in meta.P0_MILESTONES
                           if m.target and m.target["kind"] == "research"}
        for tech_name in _observables(after_snap)["techs"] - before["techs"]:
            if tech_name not in milestone_techs:
                label = next((t["label"] for t in after_snap.get("science", {}).get("techs", [])
                              if t["name"] == tech_name), tech_name)
                self.narrator.on_research(label, meta_view.objective_label)
        self.rt.set_state("RUNNING", "")

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

    def _plan_payload(self, meta_view: meta.MetaView, bottleneck: dict | None) -> dict:
        payload = meta_view.to_dict()
        payload["bottleneck"] = bottleneck
        payload["reset"] = self.last_reset_eval
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
