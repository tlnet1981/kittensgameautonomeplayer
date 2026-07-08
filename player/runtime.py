"""PlayerRuntime: Lebenszyklus des autonomen Spielers.

Orchestriert Browser (Spielfenster), Telemetrie-Schleife und — ab M1 —
die Brain-Entscheidungsschleife. Wird vom FastAPI-Server (server.py)
über die Cockpit-Controls gesteuert:

    Start  -> Browser starten, Spiel laden, Schleifen starten
    Pause  -> Brain hält nach der laufenden atomaren Aktion an
    Resume -> Brain läuft weiter (mit vollem Replan)
    Step   -> genau eine Aktion / eine Entscheidung, dann wieder Pause
    Stop   -> alles herunterfahren, Browser schließen

Agent-Zustände folgen der Cockpit-Spec Kap. 26.1.
"""

from __future__ import annotations

import asyncio
import json
import time
import traceback

from config import Config
from player.driver.browser import GameBrowser
from player.driver.reader import read_snapshot
from player.events import EventBus
from player.persistence import SessionStore
from player.state.derived import derive
from player import viewmodels


class PlayerRuntime:
    def __init__(self, config: Config, bus: EventBus) -> None:
        self.config = config
        self.bus = bus
        self.store: SessionStore | None = None
        self.browser: GameBrowser | None = None
        self.brain = None   # ab M1: player.brain.loop.Brain
        self._telemetry_task: asyncio.Task | None = None
        self._brain_task: asyncio.Task | None = None
        self._save_task: asyncio.Task | None = None
        self._state = "IDLE"
        self._errors: list[str] = []
        self.last_snapshot: dict | None = None
        self.last_snapshot_ts: float | None = None
        self.version_guard: dict = {}
        # AgentMode (Spec Anhang A.2 / G-02): ACTIVE | MODEL_MISMATCH | SAFE_STOP.
        # MODEL_MISMATCH sperrt alle nicht-lesenden Aktionen außer dem
        # Abschalten von Verbrauchern (loop.apply_mode_gate); SAFE_STOP sperrt
        # alles. Manuelle Freigabe: acknowledge_mismatch() (Cockpit-Control).
        self.agent_mode = "ACTIVE"
        self.agent_mode_reason = ""
        self._ack_version_key: str | None = None   # quittierte Abweichung
        # Von den Cockpit-Controls gesetzte Flags (Brain wertet sie aus, M1):
        self.pause_requested = False
        self.step_actions_remaining = 0
        self.step_until_decision = False
        # Ausbaugrenzen-Wächter: ausgelöste + quittierte Hinweise
        # (überleben Neustarts in data/frontier-state.json).
        self._frontier_file = self.config.data_dir / "frontier-state.json"
        self.frontier_fired: dict[str, dict] = {}    # id -> Hinweis-Payload
        self.frontier_dismissed: set[str] = set()
        self._load_frontier_state()

    # ------------------------------------------------------------ Frontier

    def _load_frontier_state(self) -> None:
        try:
            data = json.loads(self._frontier_file.read_text(encoding="utf-8"))
            self.frontier_fired = {n["id"]: n for n in data.get("fired", [])}
            self.frontier_dismissed = set(data.get("dismissed", []))
        except Exception:
            pass   # keine/kaputte Datei = frischer Zustand

    def _save_frontier_state(self) -> None:
        try:
            self.config.data_dir.mkdir(parents=True, exist_ok=True)
            self._frontier_file.write_text(json.dumps({
                "fired": list(self.frontier_fired.values()),
                "dismissed": sorted(self.frontier_dismissed),
            }, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass

    def frontier_notify(self, notice: dict) -> None:
        """Vom Brain gerufen, wenn eine Ausbaugrenze erreicht wird."""
        self.frontier_fired[notice["id"]] = notice
        self._save_frontier_state()
        self.bus.publish("frontier.reached", notice)

    def frontier_dismiss(self, fid: str) -> None:
        self.frontier_dismissed.add(fid)
        self._save_frontier_state()
        self.bus.publish("frontier.dismissed", {"id": fid})

    def frontier_active(self) -> list[dict]:
        return [n for fid, n in self.frontier_fired.items()
                if fid not in self.frontier_dismissed]

    # ------------------------------------------------------------------ Status

    @property
    def state(self) -> str:
        return self._state

    def _set_state(self, new_state: str, reason: str = "") -> None:
        if new_state == self._state:
            return
        old = self._state
        self._state = new_state
        self.bus.publish("agent.state", {"from": old, "to": new_state, "reason": reason})

    # Öffentlich fürs Brain (PLANNING/EXECUTING/WAITING/DEGRADED-Wechsel):
    def set_state(self, new_state: str, reason: str = "") -> None:
        self._set_state(new_state, reason)

    def status_payload(self) -> dict:
        snap = self.last_snapshot or {}
        age = (time.time() - self.last_snapshot_ts) if self.last_snapshot_ts else None
        run_info = None
        current_action = None
        plan = None
        if self.brain is not None:
            if self.brain.last_meta is not None:
                mv = self.brain.last_meta
                run_info = {"type": mv.run_type, "phase": mv.phase, "objective": mv.objective_label}
                plan = self.brain._plan_payload(mv, self.brain.last_bottleneck)
            if self.brain.last_record is not None:
                current_action = self.brain.last_record.to_dict()
        return {
            "status": viewmodels.status_vm(snap, self._state, self.version_guard, run_info,
                                           agent_mode={"mode": self.agent_mode,
                                                       "reason": self.agent_mode_reason}),
            "economy": viewmodels.economy_vm(snap) if snap else None,
            "population": viewmodels.population_vm(snap) if snap else None,
            "health": viewmodels.health_vm(self._state, age, self._errors),
            "systems": viewmodels.systems_vm(snap) if snap else None,
            "currentDecision": current_action,
            "plan": plan,
            "frontier": self.frontier_active(),
        }

    # ------------------------------------------------------------------ Controls

    async def start(self) -> None:
        if self._state not in ("IDLE", "ERROR"):
            return
        self._set_state("STARTING", "Cockpit-Start")
        try:
            self.store = SessionStore(self.config.data_dir)
            self.bus.set_persister(self.store.write_event)
            self.browser = GameBrowser(self.config.headless, self.config.game_window_size,
                                       self.config.chromium_path, self.config.profile_dir)
            url = self.config.effective_game_url
            self.bus.publish("narrative.chapter", {
                "title": "Session gestartet",
                "body": f"Spielfenster wird geöffnet: {url}",
                "priority": "P1",
            })
            await self.browser.start(url)
            await self._check_version()
            self._telemetry_task = asyncio.create_task(self._telemetry_loop())
            if self.config.save_export_interval > 0:
                self._save_task = asyncio.create_task(self._save_loop())
            # Brain (Entscheidungsschleife) starten:
            from player.brain.loop import Brain
            self.brain = Brain(self)
            self._brain_task = asyncio.create_task(self.brain.run())
            self._set_state("RUNNING", "Spiel geladen — Agent aktiv")
        except Exception as exc:
            self._errors.append(str(exc))
            self.bus.publish("model.error", {"error": str(exc), "trace": traceback.format_exc()})
            self._set_state("ERROR", str(exc))
            await self._teardown()

    async def stop(self) -> None:
        if self._state == "IDLE":
            return
        self._set_state("STOPPING", "Cockpit-Stop")
        await self._teardown()
        self._set_state("IDLE", "gestoppt")

    def pause(self) -> None:
        self.pause_requested = True
        self._set_state("PAUSED", "Cockpit-Pause")

    def resume(self) -> None:
        self.pause_requested = False
        self.step_actions_remaining = 0
        self.step_until_decision = False
        if self._state == "PAUSED":
            self._set_state("RUNNING", "Cockpit-Resume")

    def step_action(self) -> None:
        self.step_actions_remaining += 1

    def step_decision(self) -> None:
        self.step_until_decision = True

    # ------------------------------------------------------------------ AgentMode

    def enter_model_mismatch(self, reason: str, source: str = "model") -> None:
        """Harter Stop (G-02/G-10): nur noch lesende/sichernde Aktionen.
        Idempotent — im Mismatch bleibt der erste Grund stehen."""
        if self.agent_mode == "MODEL_MISMATCH":
            return
        self.agent_mode = "MODEL_MISMATCH"
        self.agent_mode_reason = reason
        self.bus.publish("model.mismatch", {"reason": reason, "source": source})

    def acknowledge_mismatch(self) -> None:
        """Manuelle Freigabe (Cockpit-Control): zurück auf ACTIVE. Die aktuell
        beobachtete Versionsabweichung wird quittiert und retriggert nicht
        erneut; der Prediction-Streak des Brains wird genullt."""
        vg = self.version_guard
        if vg and not vg.get("match", True):
            self._ack_version_key = f"{vg.get('gameVersion')}|{vg.get('buildRevision')}"
        self.agent_mode = "ACTIVE"
        self.agent_mode_reason = ""
        if self.brain is not None:
            self.brain.mismatch_streak = 0
        self.bus.publish("model.mismatch_acknowledged",
                         {"acknowledgedVersion": self._ack_version_key})

    # ------------------------------------------------------------------ Schleifen

    async def _telemetry_loop(self) -> None:
        assert self.browser is not None
        while True:
            try:
                snap = await read_snapshot(self.browser)
                derive(snap)
                self.last_snapshot = snap
                self.last_snapshot_ts = time.time()
                # Version Guard periodisch (G-02): billig auf dem frischen
                # Snapshot statt eines Extra-Reads.
                self.apply_version_guard(snap)
                if snap.get("errors"):
                    for e in snap["errors"]:
                        if e not in self._errors:
                            self._errors.append(e)
                            self.bus.publish("model.warning", {"error": e})
                self.bus.publish("state.snapshot", self.status_payload())
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._errors.append(str(exc))
                self.bus.publish("model.error", {"error": str(exc)})
            await asyncio.sleep(self.config.snapshot_interval)

    async def _save_loop(self) -> None:
        assert self.browser is not None
        while True:
            await asyncio.sleep(self.config.save_export_interval)
            try:
                save = await self.browser.export_save()
                if save and self.store:
                    path = self.store.write_save(save)
                    self.bus.publish("state.save_exported", {"path": str(path)})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.bus.publish("model.warning", {"error": f"Save-Export fehlgeschlagen: {exc}"})

    # ------------------------------------------------------------------ Intern

    async def _check_version(self) -> None:
        """Version Guard beim Start: liest einen Snapshot und prüft ihn."""
        assert self.browser is not None
        self.apply_version_guard(await read_snapshot(self.browser))

    def apply_version_guard(self, snap: dict) -> None:
        """Version Guard (G-02): bei Abweichung von der Referenzversion wird
        gewarnt (Badge + model.version_mismatch-Event). HART (AgentMode
        MODEL_MISMATCH, nur lesende/sichernde Aktionen) nur mit
        KGP_VERSION_GUARD_HARD=1 — Betreiberentscheidung, dokumentiert in
        config.py; der Prognose-Streak-Stopp (G-10) bleibt immer hart. Eine
        per acknowledge_mismatch quittierte Version retriggert nicht."""
        meta = snap.get("meta", {})
        version = meta.get("version")
        build = meta.get("buildRevision")
        # Telemetrie liefert die Version ohne Punkte (z. B. "1502" für 1.5.0.2).
        norm = lambda v: str(v or "").replace(".", "")
        matches = (norm(version) == norm(self.config.reference_version)
                   and build == self.config.reference_build_revision)
        first_check = not self.version_guard
        changed = (self.version_guard.get("gameVersion") != version
                   or self.version_guard.get("buildRevision") != build
                   or self.version_guard.get("match") != matches)
        self.version_guard = {
            "gameVersion": version,
            "buildRevision": build,
            "referenceVersion": self.config.reference_version,
            "referenceBuild": self.config.reference_build_revision,
            "match": matches,
        }
        if matches:
            return
        # Warn-Event nur bei Änderung/Erstprüfung (kein Sekundentakt-Spam):
        if first_check or changed:
            self.bus.publish("model.version_mismatch", self.version_guard)
        if not self.config.version_guard_hard:
            return   # weicher Guard: melden, weiterspielen (siehe Docstring)
        if f"{version}|{build}" != self._ack_version_key:
            self.enter_model_mismatch(
                f"Versionsabweichung: v{version} r{build} ≠ Referenz "
                f"v{self.config.reference_version} r{self.config.reference_build_revision}",
                source="version")

    async def _teardown(self) -> None:
        for task in (self._telemetry_task, self._brain_task, self._save_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._telemetry_task = None
        self._brain_task = None
        self._save_task = None
        self.brain = None
        if self.browser is not None:
            try:
                await self.browser.stop()
            except Exception:
                pass
            self.browser = None
        if self.store is not None:
            self.bus.set_persister(None)
            self.store.close()
            self.store = None
