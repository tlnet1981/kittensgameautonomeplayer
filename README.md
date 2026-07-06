# Kittens Game — Autonomer Player 🐈‍⬛

Ein autonomer Agent spielt [Kittens Game](https://kittensgame.com/web/) — und du siehst
ihm dabei zu, Let's-Play-mäßig. Zwei Fenster:

1. **Das Cockpit** (dieser Server, im Browser): zeigt live, *was* der Agent tut,
   *warum* genau das jetzt die beste Aktion ist, welche Alternativen er verworfen
   hat und wohin der Plan führt. Mit Start/Pause/Step/Stop-Steuerung.
2. **Das Spielfenster** (separates Chromium, von Playwright gesteuert): hier spielt
   der Agent sichtbar — man sieht die Klicks mit Highlight-Glow.

Grundlage sind zwei Spezifikationen: *„Autonome Optimimale Spiel-Mechanik"*
(die Entscheidungslogik) und *„Cockpit Konzept"* (die Beobachtungsoberfläche).
Referenzversion des Spiels: **1.5.0.2, Build Revision 3**.

## Quickstart

Voraussetzungen: Python 3.11+, einmalig:

```bash
pip install -r requirements.txt
playwright install chromium
```

Starten:

```bash
python run.py
```

Das Cockpit öffnet sich unter <http://127.0.0.1:8000>. Klick auf **▶ Start** öffnet
das Chromium-Spielfenster mit kittensgame.com und der Agent legt los.

### Wichtige Optionen

| Option | Wirkung |
|---|---|
| `--game-url URL` | andere Spielquelle (Default: `https://kittensgame.com/web/`) |
| `--local-game` | Spiel aus lokalem Clone `./gamefiles` servieren (offline, versionsstabil) |
| `--headless` | Spielfenster unsichtbar (Tests/Server) |
| `--port N` | Cockpit-Port (Default 8000) |
| `--no-open` | Cockpit nicht automatisch im Browser öffnen |

Für den lokalen Spielmodus einmalig:

```bash
git clone --depth 1 https://github.com/nuclear-unicorn/kittensgame.git gamefiles
```

Alle Optionen gibt es auch als Umgebungsvariablen (`KGP_*`, siehe `config.py`).

## Bedienung des Cockpits

- **▶ Start / ■ Stop** — Spielfenster öffnen/schließen, Agent starten/beenden.
- **⏸ Pause** — Agent hält nach der laufenden atomaren Aktion an (Telemetrie läuft weiter).
- **⏵ Weiter** — Agent läuft weiter (mit vollem Replan).
- **⏭ Step** — genau eine Aktion ausführen, dann wieder Pause.
- **Tabs** — Mission Control (Live-Hauptansicht), Decisions (Entscheidungsjournal +
  Inspector), Economy (Ressourcen/Engpässe), Plan (Phasen & Ziele), Systems
  (Religion/Space/Time/…), Timeline, Diagnostics.

Unten läuft der **Live-Feed** mit Narrations-Karten und Ereignissen.

## Projektstand (Meilensteine)

| Meilenstein | Status | Inhalt |
|---|---|---|
| M0 Gerüst | ✅ | Server, Cockpit-Shell, Playwright-Driver, Live-Telemetrie |
| M1 Brain-Kern | ✅ | Steuerzyklus, Food-Safety, Jobs, P0-Frühspiel, Decision Records, Mission-Control/Decisions/Plan-Tabs |
| M2 Frühspiel komplett | ✅ | Handel + Kundschafter, Religion-Basis (Praise/Tempel), Festivals, Narrations-Karten, Timeline-Tab |
| M3 Erster Reset | ✅ | Reset-Transaktion, Run-Typen, Metaphysics-Kaufkette |
| M4 Space & Energie | ✅ | Rocketry-Kette, Craft-Kaskade, Energie-Regel, Space-Missionen |
| M5 Religion tief | ✅ | Solar Revolution, Religion-Upgrades, Unicorn-Kette, Adore vor Reset (TAP-light) |
| M6 Time | – | Leviathans, Time Crystals, Shatter, Chronospheres, Challenges |
| M7 Endgame | – | Seed-Runs, positive CS-Schleife, Paragon-Speedruns |

## Architektur (Kurzfassung)

```
Browser (Zuschauer)                    Chromium (Playwright, sichtbar)
   │  Cockpit-UI                            │  Kittens Game
   │  WebSocket /ws                         │  window.game  (JS-API)
   ▼                                        ▼
FastAPI-Server ──► PlayerRuntime ──► driver/ (reader.js-Snapshot, Klick-Actor)
   ▲                    │
   │                    ├─► state/  (Normalisierung, abgeleitete Kennzahlen)
   └── Events ◄─────────┼─► brain/  (Safety → Meta-Controller → Taktik → Executor)
       (JSONL-Log)      └─► narrator (deterministische Erzähl-Karten)
```

Kernprinzip: **das laufende Spiel ist das Modell** — der Agent liest alle Preise,
Raten und Effekte live über `window.game`, statt die Spielformeln zu duplizieren.
Details: [docs/architecture.md](docs/architecture.md), Entscheidungslogik:
[docs/brain.md](docs/brain.md), Spiel-API: [docs/game-api.md](docs/game-api.md).

## Daten

Jede Session schreibt nach `data/session-<Zeitstempel>/`:
- `events.jsonl` — alle Entscheidungen und Ereignisse (Timeline-Quelle)
- `saves/` — periodische Save-Exporte des Spiels (Backup)
