#!/usr/bin/env python3
"""Einstiegspunkt: startet den Cockpit-Server des Kittens-Game-Players.

Beispiele:
    python run.py                          # Normalbetrieb (kittensgame.com, sichtbares Spielfenster)
    python run.py --local-game             # Spiel aus ./gamefiles lokal servieren (Dev/Test)
    python run.py --headless               # Spielfenster unsichtbar (Tests/Server)
    python run.py --port 9000              # Cockpit-Port ändern

Danach im Browser öffnen: http://127.0.0.1:8000
"""

import argparse
import webbrowser

import uvicorn

from config import CONFIG


def main() -> None:
    parser = argparse.ArgumentParser(description="Kittens Game Autonomer Player")
    parser.add_argument("--host", default=None, help="Cockpit-Host (Default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Cockpit-Port (Default 8000)")
    parser.add_argument("--game-url", default=None, help="URL des Spiels (Default kittensgame.com/web/)")
    parser.add_argument("--local-game", action="store_true", help="Spiel aus ./gamefiles lokal servieren")
    parser.add_argument("--headless", action="store_true", help="Spielfenster unsichtbar starten")
    parser.add_argument("--no-open", action="store_true", help="Cockpit nicht automatisch im Browser öffnen")
    args = parser.parse_args()

    if args.host:
        CONFIG.host = args.host
    if args.port:
        CONFIG.port = args.port
    if args.game_url:
        CONFIG.game_url = args.game_url
    if args.local_game:
        CONFIG.local_game = True
    if args.headless:
        CONFIG.headless = True

    from player.server import create_app
    app = create_app()

    cockpit_url = f"http://{CONFIG.host}:{CONFIG.port}"
    print(f"\n  Cockpit:     {cockpit_url}")
    print(f"  Spielquelle: {CONFIG.effective_game_url}\n")
    if not args.no_open:
        try:
            webbrowser.open(cockpit_url)
        except Exception:
            pass

    uvicorn.run(app, host=CONFIG.host, port=CONFIG.port, log_level="warning")


if __name__ == "__main__":
    main()
