"""Persistenz: Session-Verzeichnis, JSONL-Eventlog, Save-Exporte.

Pro Programmlauf entsteht ein Verzeichnis data/session-<Zeitstempel>/ mit:
- events.jsonl   alle Events des Event-Bus (Decisions, Narration, Fehler ...)
- saves/         periodische Save-Exporte des Spiels (LZString-Strings)

Das Timeline-Tab des Cockpits kann die Historie aus events.jsonl laden.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


class SessionStore:
    def __init__(self, data_dir: Path) -> None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.dir = data_dir / f"session-{stamp}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.saves_dir = self.dir / "saves"
        self.saves_dir.mkdir(exist_ok=True)
        self._events_file = open(self.dir / "events.jsonl", "a", encoding="utf-8")

    def write_event(self, event: dict) -> None:
        # Telemetrie-Snapshots sind groß und hochfrequent — die landen
        # bewusst NICHT im Log, nur Entscheidungen/Ereignisse.
        if event["type"].startswith("state.snapshot"):
            return
        self._events_file.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._events_file.flush()

    def write_save(self, save_string: str) -> Path:
        path = self.saves_dir / f"save-{time.strftime('%Y%m%d-%H%M%S')}.txt"
        path.write_text(save_string, encoding="utf-8")
        return path

    def read_events(self, limit: int = 2000) -> list[dict]:
        path = self.dir / "events.jsonl"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(line) for line in lines[-limit:]]

    def close(self) -> None:
        try:
            self._events_file.close()
        except Exception:
            pass
