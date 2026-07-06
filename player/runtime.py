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
        self._telemetry_task: asyncio.Task | None = None
        self._save_task: asyncio.Task | None = None
        self._state = "IDLE"
        self._errors: list[str] = []
        self.last_snapshot: dict | None = None
        self.last_snapshot_ts: float | None = None
        self.version_guard: dict = {}
        # Von den Cockpit-Controls gesetzte Flags (Brain wertet sie aus, M1):
        self.pause_requested = False
        self.step_actions_remaining = 0
        self.step_until_decision = False

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

    def status_payload(self) -> dict:
        snap = self.last_snapshot or {}
        age = (time.time() - self.last_snapshot_ts) if self.last_snapshot_ts else None
        return {
            "status": viewmodels.status_vm(snap, self._state, self.version_guard),
            "economy": viewmodels.economy_vm(snap) if snap else None,
            "population": viewmodels.population_vm(snap) if snap else None,
            "health": viewmodels.health_vm(self._state, age, self._errors),
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
                                       self.config.chromium_path)
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
            self._set_state("RUNNING", "Spiel geladen")
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

    # ------------------------------------------------------------------ Schleifen

    async def _telemetry_loop(self) -> None:
        assert self.browser is not None
        while True:
            try:
                snap = await read_snapshot(self.browser)
                derive(snap)
                self.last_snapshot = snap
                self.last_snapshot_ts = time.time()
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
        """Version Guard (weich): warnt bei Abweichung von der Referenzversion."""
        assert self.browser is not None
        snap = await read_snapshot(self.browser)
        meta = snap.get("meta", {})
        version = meta.get("version")
        build = meta.get("buildRevision")
        # Telemetrie liefert die Version ohne Punkte (z. B. "1502" für 1.5.0.2).
        norm = lambda v: str(v or "").replace(".", "")
        matches = (norm(version) == norm(self.config.reference_version)
                   and build == self.config.reference_build_revision)
        self.version_guard = {
            "gameVersion": version,
            "buildRevision": build,
            "referenceVersion": self.config.reference_version,
            "referenceBuild": self.config.reference_build_revision,
            "match": matches,
        }
        if not matches:
            self.bus.publish("model.version_mismatch", self.version_guard)

    async def _teardown(self) -> None:
        for task in (self._telemetry_task, self._save_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._telemetry_task = None
        self._save_task = None
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
