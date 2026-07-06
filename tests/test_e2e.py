"""End-to-End-Test: Der Agent spielt das lokal servierte Spiel headless.

Läuft nur mit RUN_E2E=1 (dauert mehrere Minuten und braucht den lokalen
Spiel-Clone unter ./gamefiles):

    RUN_E2E=1 KGP_CHROMIUM_PATH=/opt/pw-browsers/chromium python3 -m pytest tests/test_e2e.py -s

Geprüfte Progressionsmarker (Frühspiel, Spec 24.3 „Benchmark-Suite" Punkt 1,
stark verkürzt): Felder gebaut → Holz veredelt → Hütte → Kitten → Job.
"""

import asyncio
import os
import time

import pytest

RUN_E2E = os.environ.get("RUN_E2E") == "1"
pytestmark = pytest.mark.skipif(not RUN_E2E, reason="E2E nur mit RUN_E2E=1")


@pytest.mark.asyncio
async def test_early_game_progression():
    os.environ.setdefault("KGP_LOCAL_GAME", "1")
    os.environ.setdefault("KGP_HEADLESS", "1")
    os.environ.setdefault("KGP_DECISION_INTERVAL", "0.6")
    os.environ.setdefault("KGP_PORT", "8901")

    # Config-Modul frisch laden, damit die Env-Variablen greifen:
    import importlib
    import config as config_module
    importlib.reload(config_module)
    from config import CONFIG
    from player.events import EventBus
    from player.runtime import PlayerRuntime

    # Eigener Server ist unnötig — das Spiel muss aber von irgendwo kommen.
    # Wir servieren gamefiles über einen Mini-HTTP-Server:
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    handler = partial(SimpleHTTPRequestHandler, directory=str(CONFIG.gamefiles_dir))
    httpd = ThreadingHTTPServer(("127.0.0.1", 8902), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    CONFIG.local_game = False
    CONFIG.game_url = "http://127.0.0.1:8902/index.html"
    CONFIG.save_export_interval = 0

    bus = EventBus()
    rt = PlayerRuntime(CONFIG, bus)
    await rt.start()
    assert rt.state not in ("ERROR", "IDLE"), f"Start fehlgeschlagen: {rt._errors}"

    try:
        deadline = time.time() + 8 * 60
        markers = {"fields": False, "wood": False, "hut": False, "kitten": False, "job": False}
        while time.time() < deadline and not all(markers.values()):
            await asyncio.sleep(5)
            snap = rt.last_snapshot or {}
            blds = {b["name"]: b["val"] for b in snap.get("buildings", [])}
            res = {r["name"]: r["value"] for r in snap.get("resources", [])}
            jobs = {j["name"]: j["value"] for j in snap.get("village", {}).get("jobs", [])}
            markers["fields"] = markers["fields"] or blds.get("field", 0) >= 10
            markers["wood"] = markers["wood"] or res.get("wood", 0) >= 1
            markers["hut"] = markers["hut"] or blds.get("hut", 0) >= 1
            markers["kitten"] = markers["kitten"] or snap.get("village", {}).get("kittens", 0) >= 1
            markers["job"] = markers["job"] or any(v > 0 for v in jobs.values())
        assert all(markers.values()), f"Progressionsmarker unvollständig: {markers}"
    finally:
        await rt.stop()
        httpd.shutdown()
