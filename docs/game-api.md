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

## Policies / Challenges

| Zugriff | Bedeutung |
|---|---|
| `game.science.policies` | Array `{name, label, researched, blocked, unlocked, blocks, prices}` (science.js:850) — `blocked` = exklusive Alternative zuerst erforscht, bis zum Reset gesperrt |
| `game.getEffect("policyFakeBought")` | Pacifism-Preisaufschlag: Effektivpreis = `val × 1.25^n` (PolicyBtnController.getPrices) |
| `game.science.getPolicy(name)` | einzelne Policy (science.js:2251) |
| `new classes.ui.PolicyBtnController(game)` + `fetchModel({id})` + `buyItem(model, {boughtByQueue: true})` | Policy-Kauf über die echte Spiel-Logik inkl. blocks-Propagation; `boughtByQueue` überspringt den Confirm-Dialog (science.js:2513) |
| `game.challenges.challenges` | Array `{name, label, researched, on, unlocked, active, pending}` (challenges.js:42) — `researched` = Erstabschluss, `on` = Abschlusszahl |
| `game.challenges.getChallenge(name)` / `anyChallengeActive()` / `getCountPending()` | Einzelzugriff/Statusabfragen (challenges.js:599-626) |
| `challenge.pending = true` | Vormerkung; `_resetInternal` wandelt pending → active (game.js:5136-5141). Achtung: der Challenge-BUTTON toggelt (challenges.js:885-891), Iron Will resettet sofort |
| `game.challenges.reserves.reservesExist()` | Reserven aus Challenge-Resets vorhanden? |
| Challenges-Tab | sichtbar erst mit Adjustment-Bureau-Perk (game.js:2680) |

## Sonstiges

| Zugriff | Bedeutung |
|---|---|
| `game.religion.faith / faithRatio` | Faith-Zustand (Details ab M5) |
| `game.tabs` | Tab-Liste `{tabId, visible}` — Grundlage für sichtbare Klick-Navigation |
| `game.save()` + `localStorage['com.nuclearunicorn.kittengame.savedata']` | Save-Export (LZString) |

## DOM-Selektoren (Actor, sichtbare Klicks)

| Selektor | Bedeutung |
|---|---|
| `a.tab.<TabId>` | Spiel-Tabs (`Bonfire`, `Village`, `Science`, `Workshop`, `Trade`, `Religion`, `Space`, `Time`, `Challenges`); aktiver Tab trägt zusätzlich `activeTab`; unsichtbare Tabs fehlen im DOM |
| `div.btn` | alle Aktions-Buttons; deaktivierte tragen `disabled` |
| `div.btn .btnTitle` | Button-Beschriftung (z. B. „Catnip field") — Matching per `startsWith` |

Der Actor injiziert die CSS-Klasse `kgp-glow` (Cyan-Leuchtrahmen) vor jedem
Klick — reine Show für den Zuschauer, keine Spielwirkung.

JS-API-Aufrufe des Actors (wo DOM-Klicks unpraktisch sind):
- Jobs: `game.village.getJob(name)`, `assignJob(job, amt)` (nur positive amt!),
  `unassignJob(kitten)` mit Kitten aus `game.village.sim.kittens`
- Jagd: `game.village.huntAll()` (Button „Send hunters" wird bevorzugt)
- Craft: `game.workshop.craft(name, amt)` (respektiert Craft Ratio)

## Bekannte Stolpersteine

- **Sprache:** Das Spiel wählt seine Sprache aus
  `localStorage["com.nuclearunicorn.kittengame.language"]`, sonst aus
  `navigator.language` (i18n.js:79-97). Auf deutschen Systemen wäre das Spiel
  deutsch und die fest verdrahteten englischen Button-Titel des Actors
  („Gather catnip" …) würden nicht matchen. Der Browser erzwingt deshalb
  `locale="en-US"` plus ein Init-Skript, das den localStorage-Schlüssel vor
  jedem Seitenstart auf `"en"` setzt (browser.py).
- **Spielstand:** liegt im localStorage → nur mit persistentem Browser-Profil
  (`launch_persistent_context`, `data/browser-profile/`) überlebt er
  Programm-Neustarts.

- **Version ohne Punkte:** `telemetry.version` liefert `"1502"`, nicht `"1.5.0.2"` —
  Vergleich normalisieren (runtime.py `_check_version`).
- **Frisches Spiel:** vor dem ersten „Gather Catnip" ist `resources` leer und
  fast nichts `unlocked` — kein Fehler.
- **Stage-Gebäude** (Library→Data Center, Amphitheatre→Broadcast Tower):
  Label/Preise immer über `getBuildingExt(name).meta` bzw. `bld.getPrices(name)`
  auflösen, nie über die rohen `buildingsData`-Metadaten.
