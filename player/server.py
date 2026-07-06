"""Cockpit-Backend: FastAPI-App mit statischem Frontend, WebSocket und Controls.

Routen:
    GET  /                     Cockpit (statisches Frontend aus ./cockpit)
    GET  /game/...             lokal serviertes Spiel (nur im Dev-Modus LOCAL_GAME=1)
    WS   /ws                   Event-Stream: hello + alle Bus-Events als JSON
    POST /api/control/{cmd}    start | stop | pause | resume | step_action | step_decision
    GET  /api/status           aktueller Status (View-Models)
    GET  /api/timeline         Event-Historie der laufenden Session (JSONL)
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import CONFIG, PROJECT_ROOT
from player.events import BUS
from player.runtime import PlayerRuntime

COCKPIT_DIR = PROJECT_ROOT / "cockpit"


def create_app() -> FastAPI:
    app = FastAPI(title="Kittens Game Autonomer Player")
    runtime = PlayerRuntime(CONFIG, BUS)
    app.state.runtime = runtime

    # --- Spiel lokal servieren (Dev/Test) ---
    if CONFIG.local_game and CONFIG.gamefiles_dir.exists():
        app.mount("/game", StaticFiles(directory=CONFIG.gamefiles_dir, html=True), name="game")

    # --- API ---

    @app.get("/api/status")
    async def status() -> JSONResponse:
        return JSONResponse(runtime.status_payload())

    @app.post("/api/control/{cmd}")
    async def control(cmd: str) -> JSONResponse:
        if cmd == "start":
            asyncio.create_task(runtime.start())
        elif cmd == "stop":
            asyncio.create_task(runtime.stop())
        elif cmd == "pause":
            runtime.pause()
        elif cmd == "resume":
            runtime.resume()
        elif cmd == "step_action":
            runtime.step_action()
        elif cmd == "step_decision":
            runtime.step_decision()
        elif cmd == "force_reset":
            # Debug/Test: Reset-Transaktion beim nächsten Zyklus erzwingen.
            if runtime.brain is not None:
                runtime.brain.force_reset = True
        else:
            return JSONResponse({"ok": False, "error": f"Unbekanntes Kommando: {cmd}"}, status_code=400)
        return JSONResponse({"ok": True, "state": runtime.state})

    @app.post("/api/debug/eval")
    async def debug_eval(payload: dict) -> JSONResponse:
        """Debug/Test: beliebiges JS im Spielkontext ausführen (nur localhost).
        Für Entwicklung und zum „Cheaten" beim privaten Zusehen gedacht."""
        if runtime.browser is None:
            return JSONResponse({"ok": False, "error": "Browser nicht gestartet"}, status_code=409)
        try:
            result = await runtime.browser.evaluate(payload.get("js", "() => null"))
            return JSONResponse({"ok": True, "result": result})
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    @app.get("/api/timeline")
    async def timeline(limit: int = 500) -> JSONResponse:
        events = runtime.store.read_events(limit) if runtime.store else []
        return JSONResponse({"events": events})

    # --- WebSocket ---

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        queue = BUS.subscribe()
        try:
            await websocket.send_json({
                "type": "hello",
                "payload": {
                    "status": runtime.status_payload(),
                    "recentEvents": BUS.recent,
                },
            })
            while True:
                event = await queue.get()
                await websocket.send_json(event)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            BUS.unsubscribe(queue)

    # --- Statisches Cockpit (zuletzt mounten, damit /api und /ws gewinnen) ---

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(COCKPIT_DIR / "index.html")

    app.mount("/", StaticFiles(directory=COCKPIT_DIR), name="cockpit")

    return app
