"""State-Reader: holt den kompletten Spielzustand als ein JSON-Snapshot.

Der eigentliche Lesecode ist JavaScript (snapshot.js) und läuft in einem
einzigen page.evaluate() — dadurch ist der Snapshot in sich konsistent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .browser import GameBrowser

_SNAPSHOT_JS = (Path(__file__).parent / "snapshot.js").read_text(encoding="utf-8")


async def read_snapshot(browser: GameBrowser) -> dict[str, Any]:
    """Liest den Spielzustand; wirft bei nicht initialisiertem Spiel RuntimeError."""
    snap = await browser.evaluate(_SNAPSHOT_JS)
    if not snap or not snap.get("ready"):
        raise RuntimeError("Spiel nicht bereit (window.game nicht initialisiert)")
    return snap
