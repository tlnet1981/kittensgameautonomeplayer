# Kittens Game — verifizierte JS-API-Zugriffe

Referenzversion: **1.5.0.2, Build Revision 3** (`nuclear-unicorn/kittensgame`,
Commit `ee819d5e`, geklont nach `gamefiles/`).

Diese Datei ist die Wartungsgrundlage: Wenn ein Spiel-Update den Agenten bricht,
zuerst hier prüfen, welche Zugriffe sich geändert haben. Alle Zugriffe laufen
über `window.game` (Alias `window.gamePage`), initialisiert in
`gamefiles/index.html` (`gamePage = game = new com.nuclearunicorn.game.ui.GamePage()`).

## Metadaten / Kalender

| Zugriff | Bedeutung | Quelle |
|---|---|---|
| `game.telemetry.version` | Spielversion, **ohne Punkte** (z. B. `"1502"`) | game.js Telemetry |
| `game.telemetry.buildRevision` | Build-Revision (z. B. `3`) | ui.js lädt build.version.json |
| `game.ticksPerSecond` | konstant 5 — Umrechnung „pro Tick" → „pro Sekunde" | game.js:1914 |
| `game.isPaused` | Spiel pausiert? | game.js:1917 |
| `game.calendar.year/season/day/cycle/cycleYear` | Spielzeit; season 0..3 (Frühling..Winter) | calendar.js |
| `game.calendar.getCurSeason().modifiers.catnip` | Saison-Modifikator Feldproduktion | calendar.js |
| `game.calendar.seasons[3].modifiers.catnip` | Winter-Modifikator (0.25) — Worst-Case-Food | calendar.js |
| `game.calendar.weather` | `"warm"`, `"cold"` oder null | calendar.js |

## Ressourcen

| Zugriff | Bedeutung |
|---|---|
| `game.resPool.resources` | Array; je `{name, title, value, maxValue, unlocked, craftable}` |
| `game.getResourcePerTick(name, true)` | Netto-Rate pro Tick inkl. Verbrauch/Konversionen (game.js:4069) |
| `game.resPool.get(name)` | Einzelne Ressource (auch `paragon`, `karma`, `burnedParagon`) |
| `game.resPool.energyProd / energyCons` | Energie-Saldo (resources.js:526) |
| `game.getEffect("catnipPerTickBase")` | Feld-Basisproduktion vor Saison-Modifier |

## Dorf / Jobs

| Zugriff | Bedeutung |
|---|---|
| `game.village.getKittens()` | Anzahl Kitten (village.js:473) |
| `game.village.maxKittens` | Housing-Kapazität (roh) |
| `game.village.getFreeKittens()` | unbeschäftigte Kitten (village.js:425) |
| `game.village.happiness` | Happiness-Faktor (1.0 = 100 %) |
| `game.village.jobs` | Array `{name, title, value, unlocked}` |
| `game.village.getResConsumption().catnip` | Catnip-Verbrauch der Population pro Tick (negativ) |
| `game.village.leader` | Leader-Kitten oder null |

## Gebäude / Forschung / Workshop

| Zugriff | Bedeutung |
|---|---|
| `game.bld.buildingsData` | Array `{name, val, on, unlocked}` |
| `game.bld.getBuildingExt(name).meta` | Metadaten inkl. Stage-Auflösung (`label`, `unlocked`) |
| `game.bld.getPrices(name)` | aktueller Preisvektor **inkl. Price-Ratio** (buildings.js:2375) |
| `game.science.techs` | Array `{name, label, researched, unlocked, prices}` (Preise fix) |
| `game.workshop.upgrades` | Array wie techs |
| `game.workshop.crafts` | Craft-Rezepte `{name, label, prices, unlocked}` |

## Sonstiges

| Zugriff | Bedeutung |
|---|---|
| `game.religion.faith / faithRatio` | Faith-Zustand (Details ab M5) |
| `game.tabs` | Tab-Liste `{tabId, visible}` — Grundlage für sichtbare Klick-Navigation |
| `game.save()` + `localStorage['com.nuclearunicorn.kittengame.savedata']` | Save-Export (LZString) |

## Bekannte Stolpersteine

- **Version ohne Punkte:** `telemetry.version` liefert `"1502"`, nicht `"1.5.0.2"` —
  Vergleich normalisieren (runtime.py `_check_version`).
- **Frisches Spiel:** vor dem ersten „Gather Catnip" ist `resources` leer und
  fast nichts `unlocked` — kein Fehler.
- **Stage-Gebäude** (Library→Data Center, Amphitheatre→Broadcast Tower):
  Label/Preise immer über `getBuildingExt(name).meta` bzw. `bld.getPrices(name)`
  auflösen, nie über die rohen `buildingsData`-Metadaten.
