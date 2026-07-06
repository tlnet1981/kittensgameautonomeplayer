"""Kittens Game Autonomer Player.

Paketstruktur (siehe docs/architecture.md):
- driver/   Playwright-Anbindung: Browser, State-Reader, sichtbarer Actor
- state/    Snapshot-Normalisierung und abgeleitete Kennzahlen
- brain/    Entscheidungslogik (Safety, Meta-Controller, Taktik, Reset)
- server.py Cockpit-Backend (FastAPI, WebSocket, Controls)
- events.py Event-Bus zwischen Agent und Cockpit
"""
