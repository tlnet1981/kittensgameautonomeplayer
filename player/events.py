"""Event-Bus: verbindet den Agenten mit Cockpit-WebSockets und dem JSONL-Log.

Jedes Event ist ein flaches Dict:
    {"seq": int, "ts": float, "type": "namespace.name", "payload": {...}}

Namespaces folgen der Cockpit-Spec Kap. 23 (state.*, decision.*, plan.*,
execution.*, safety.*, narrative.*, model.*, reset.*, agent.*).

Der Bus ist bewusst simpel: asyncio-Queues pro Abonnent (WebSocket),
plus optionaler persistenter Writer (JSONL). Kein Backpressure-Handling
über "Queue voll -> älteste Events verwerfen" hinaus.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

MAX_QUEUE = 500


class EventBus:
    def __init__(self) -> None:
        self._seq = 0
        self._subscribers: set[asyncio.Queue] = set()
        self._persist: Callable[[dict], None] | None = None
        # Ringpuffer der letzten Events, damit ein frisch verbundenes
        # Cockpit die jüngste Historie (z. B. Live-Feed) sofort sieht.
        self._recent: list[dict] = []
        self._recent_max = 200

    def set_persister(self, fn: Callable[[dict], None] | None) -> None:
        self._persist = fn

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    @property
    def recent(self) -> list[dict]:
        return list(self._recent)

    def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> dict:
        """Event an alle Cockpit-Verbindungen und ins Log schreiben."""
        self._seq += 1
        event = {
            "seq": self._seq,
            "ts": time.time(),
            "type": event_type,
            "payload": payload or {},
        }
        self._recent.append(event)
        if len(self._recent) > self._recent_max:
            del self._recent[: len(self._recent) - self._recent_max]
        if self._persist is not None:
            try:
                self._persist(event)
            except Exception:
                pass  # Logging darf den Agenten nie stoppen
        dead: list[asyncio.Queue] = []
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Langsamer Client: ältestes Event opfern, neues rein.
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    dead.append(q)
        for q in dead:
            self._subscribers.discard(q)
        return event


BUS = EventBus()
