# Architektur

Bezugsdokumente: *[„Autonome Optimimale Spiel-Mechanik"](spielmechanik-spec.md)* (Spielmechanik-Spec)
und *„Cockpit Konzept"* (Cockpit-Spec). Dieses Projekt ist die bewusst
vereinfachte, private Umsetzung beider Spezifikationen — ohne Enterprise-Features,
aber funktional vollständig in Richtung „das komplette Spiel spielen".

## Komponenten und Datenfluss

```
┌─────────────┐  HTTP/WS   ┌──────────────────────────────────────────┐
│ Zuschauer-  │◄──────────►│ FastAPI-Server (player/server.py)        │
│ Browser     │            │  - statisches Cockpit (cockpit/)         │
│ (Cockpit)   │            │  - REST /api/control, /api/status        │
└─────────────┘            │  - WebSocket /ws (Event-Stream)          │
                           └───────────────┬──────────────────────────┘
                                           │
                           ┌───────────────▼──────────────────────────┐
                           │ PlayerRuntime (player/runtime.py)        │
                           │  Lebenszyklus, Agent-Zustände,           │
                           │  Telemetrie-Schleife, Save-Backups       │
                           └──┬──────────────┬───────────────┬────────┘
                              │              │               │
              ┌───────────────▼──┐  ┌────────▼─────┐  ┌──────▼───────┐
              │ driver/          │  │ state/       │  │ brain/ (M1+) │
              │ browser.py       │  │ derived.py   │  │ loop, safety,│
              │ reader.py        │  │ Kennzahlen   │  │ meta, tactics│
              │ snapshot.js      │  │              │  │ reset        │
              │ actor.py (M1)    │  └──────────────┘  └──────────────┘
              └───────┬──────────┘
                      │ Playwright (CDP)
              ┌───────▼──────────┐
              │ Chromium         │
              │ Kittens Game     │
              │ window.game      │
              └──────────────────┘
```

Events fließen über den **EventBus** (`player/events.py`) an alle
Cockpit-WebSockets und parallel ins JSONL-Log (`player/persistence.py`).
Das Frontend rendert ausschließlich **View-Models** (`player/viewmodels.py`)
— nie Engine-Interna (Cockpit-Spec 3.3).

## Zentrale Designentscheidungen

1. **Das laufende Spiel ist das Modell** (statt Formeln-Duplikation).
   `driver/snapshot.js` liest in einem einzigen `page.evaluate()` den kompletten
   Zustand: Ressourcen inkl. Netto-Raten (`game.getResourcePerTick`), Preise
   (`game.bld.getPrices` — inkl. Price-Ratio), Unlocks, Kalender, Energie usw.
   Prognosen (Fill-Time, Payback, ETA) rechnet `state/derived.py` aus den
   Live-Raten. Nur Bewertungsformeln aus Anhang D der Spielmechanik-Spec
   werden in Python implementiert.

2. **Sichtbare Ausführung.** Aktionen laufen als echte DOM-Klicks im sichtbaren
   Chromium (Tab wechseln → Button-Glow → Klick), damit das Zusehen Spaß macht.
   Schlägt ein Klick fehl, gibt es einen JS-API-Fallback, der im Cockpit als
   „degraded" markiert wird (Cockpit-Spec 26.3).

3. **Deterministisch erklärbar statt LLM.** Jede Entscheidung erzeugt einen
   `DecisionRecord` mit Kandidaten, Score-Komponenten und Ablehnungsgründen
   (Spielmechanik-Spec Kap. 23). Die Narration entsteht aus Templates und
   Schwellenwerten (Cockpit-Spec Kap. 18), nie aus freier Textgenerierung.

4. **Version Guard weich.** Die Spec fordert einen harten MODEL_MISMATCH-Stopp;
   für den Privatgebrauch gegen das Online-Spiel wird stattdessen gewarnt
   (Badge in der globalen Leiste) und konservativ weitergespielt. Getestet wird
   gegen die gepinnte Referenzversion 1.5.0.2 r3 (lokaler Clone).

## Agent-Zustände (Cockpit-Spec 26.1)

```
IDLE → STARTING → RUNNING ⇄ (PLANNING / EXECUTING / WAITING)
                     │  Pause             │ recoverable
                     ▼                    ▼
                  PAUSED               DEGRADED → (Recovery) → RUNNING
                     │ unsafe/fatal
                     ▼
                   ERROR → STOPPING → IDLE
```

## Steuerzyklus (Spielmechanik-Spec 3.2, ab M1)

```
1. Snapshot atomar lesen (reader)
2. Abgeleitete Kennzahlen berechnen (derived)
3. Sicherheitsinvarianten prüfen (safety)        → ggf. Schutzaktion
4. Phase / Run-Ziel bestimmen (meta)
5. Kandidaten erzeugen und bewerten (tactics)    → DecisionRecord
6. Genau eine Commit-Einheit ausführen (actor)
7. Wirkung beobachten, Abweichung prüfen
8. Bei Trigger sofort, sonst nach Intervall → 1
```

## Verzeichnis-Konventionen

- `data/session-*/` — Laufzeitdaten (im .gitignore)
- `gamefiles/` — lokaler Spiel-Clone für Dev/Tests (im .gitignore)
- `tests/fixtures/` — eingefrorene Snapshots für Brain-Unit-Tests
