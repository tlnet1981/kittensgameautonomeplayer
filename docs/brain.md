# Brain — Entscheidungslogik

Umsetzung der „Autonome Optimimale Spiel-Mechanik" in bewusst vereinfachter,
aber vollständig **erklärbarer** Form. Jede Vereinfachung gegenüber der Spec
ist hier dokumentiert.

## Steuerzyklus (`brain/loop.py`, Spec 3.2)

```
Snapshot lesen → Kennzahlen ableiten → Safety prüfen → Meilenstein bestimmen
→ Kandidaten erzeugen & bewerten → DecisionRecord veröffentlichen
→ genau eine Aktion/Charge ausführen (oder WAIT) → Wirkung beobachten
→ Meilenstein-Abschlüsse feiern → Intervall/Trigger → von vorn
```

Der Zyklus läuft alle `KGP_DECISION_INTERVAL` Sekunden (Default 1,5 s — als
Zuschauer gut verfolgbar). Pause/Step-Flags aus dem Cockpit werden am
Zyklusanfang ausgewertet.

## Safety (`brain/safety.py` + `state/derived.py`, Spec Kap. 7)

Die **Food-Invariante I-01** basiert auf der **Saisonprojektion**
(`derived.project_catnip`, Spec 7.2): Der Catnip-Bestand wird segmentweise
bis zum Ende des nächsten vollständigen Winters simuliert (1 Saison = 200 s;
Feld-Modifikatoren Frühling 1,5 / Sommer 1,0 / Herbst 1,0 / Winter 0,25).

- **kritisch**: projizierter Tiefpunkt < max(50, 30 s · Bedarf)
- **Warnstufe** (nur Housing-Sperre): Tiefpunkt < max(150, 120 s · Bedarf)
- ohne Kitten (Bedarf 0) nie kritisch — niemand kann verhungern

**Leitplanke statt Monopol** (Fix der Gather-Endlosschleife): Bei „kritisch"
liefert die Safety abgestufte Schutz-KANDIDATEN, die normal konkurrieren —
food-neutrale Fortschritte (Forschung!) laufen weiter:

| Schutzkandidat | Score | Bedingung |
|---|---|---|
| Farmer zuweisen / umschulen | 6.0 | kostenlos, wirkt sofort |
| Catnip-Feld bauen | 4.0 | **nur wenn** die Projektion nach dem Kauf (−Preis, +0,625/s·Saisonmod) nachweislich besser ist |
| Catnip sammeln | 1.2 | letzter Ausweg, ehrlich schwach |

Zusätzlich `foodRisk −3.0` auf alle Kandidaten mit Catnip-Preisen
(Gebäude, Refine, Trades mit Catnip-Ware) — die Kaufregel (Score > 0)
filtert sie in der Krise heraus.

Energie- (I-04) und Reset-Invarianten (I-02/TC-Schutz) siehe unten.

## Dynamisches Housing (`tactics._housing_eval`, Spec 12.1)

Keine hut-Meilensteine mehr — Housing wird nach Bedarf entschieden:
1. **Bedarfs-Gate:** nur bei voller Kapazität (`maxKittens == kittens`;
   0 == 0 → die erste Hütte entsteht dynamisch).
2. **Food-Gate:** Saisonprojektion inkl. Mehrlast der neuen Kitten
   (Kapazität × Bedarf/Kitten) muss über der Warnschwelle bleiben.
3. **Score:** 1.6 Basis + 0.4 Paragon-Grenzwert ab 68 Kitten.

Generalprinzip: Bau-**Meilensteine** gibt es nur noch für Gate-Gebäude
(Library, Workshop, Mine, Smelter, Tradepost, Temple, Ziggurat, Steamworks,
Oil Well, Magneto); alle Pacing-Gebäude (Housing, Storage, Amphitheater,
Pasture, Academies, Felder ab #10) kommen aus der Bedarfslogik.
Vollständiger Dynamik-Abgleich mit der Spec: [spec-gaps.md](spec-gaps.md).

## Meta-Controller (`brain/meta.py`, Spec Kap. 8/9)

M1: Run-Typ `FIRST_RUN`, Phase P0, feste Meilensteinliste
(Felder → Holz → Hütte → Bibliothek → Calendar → Agriculture → … → Currency).
Die Liste ist **Suchraum, keine Zwangsjacke**: Sie liefert nur das aktive Ziel
(= Engpassquelle); alles Opportunistische (Jobs, Jagd, Crafts, Upgrades,
billige Gebäude) läuft parallel übers Scoring.

Besonderheit `wood_first`: Holz existiert anfangs nur über „Refine catnip".
Der Meilenstein hat ein *Ressourcen-Ziel* (10 Holz), weil Hütte/Bibliothek
im Spiel erst ab wenigen Holz **sichtbar** werden — vorher gäbe es keine
Preise und damit keinen Engpass (im Live-Test gefundener Deadlock).

## Taktik (`brain/tactics.py`, Spec Kap. 10–12)

### Engpass (Schattenpreis-light, Spec 10.1/10.2)

Statt exakter Schattenpreise: Der Engpass ist die Ressource mit der größten
Zeit-bis-leistbar am aktiven Ziel (`eta = fehlend / netRate`; ∞ bei Rate ≤ 0
oder wenn das **Cap** die Zielmenge blockiert → Storage-Gate).

### Score-Komponenten (additiv, alle im Cockpit sichtbar)

| Komponente | Wert | Bedeutung |
|---|---|---|
| safety | 10.0 | Schutzaktion (Vorrang G-04) |
| milestone | 3.0 | Ziel direkt kaufen/erforschen |
| jobValue | 2.4–2.6 | freies Kitten → Engpass-Job (12.2 vereinfacht) |
| bottleneck | 1.8–2.0 | Engpass lösen (Refine, Engpass-Gebäude) |
| unlock | 1.4–1.9 | Forschung/Upgrades (Unlock-first, 13.3) |
| storage | 1.0–2.2 | Storage-Regel 11.3 A (nur bei Cap-Blockade!) |
| housing | 1.6 | Hütte etc., nur bei sicherer Food-Lage (12.1) |
| capLoss | 1.5–1.6 | Jagd/Craft nahe Cap (11.4) |
| happiness | 1.2–1.8 | Festival / Amphitheater (Happiness = globaler Produktionsmultiplikator) |
| economy | 0.6 | generischer Ausbau |
| opportunity | −0.7 | Kauf verbraucht die für den Engpass reservierte Ressource (10.2) |
| WAIT | 0.01 | immer möglich, mit Grund + Weckbedingung (G-05) |

**Kaufregel (10.3):** ausgeführt wird der beste machbare Kandidat mit
Score > 0 — sonst WAIT. **Tie-Break (C.2):** bei Score-Gleichheit gewinnt
die lexikografisch kleinere Action-ID → deterministisch.

### Konversions-Reservierung (Deadlock-Schutz)

Ist der Engpass nur über eine Konversion erreichbar (früh: Wood nur über
Refine, solange keine Woodcutter existieren), wird die Input-Ressource
(Catnip) „reserviert": generische Käufe, die sie verbrauchen, bekommen die
`opportunity`-Strafe und fallen unter 0. Beide Deadlocks aus dem Live-Test
sind als Regressionstests festgehalten (`tests/test_tactics.py`).

## M2-Erweiterungen: Handel, Religion-Basis, Festivals

- **Handel (14.1, TradeValue-light):** Eine Rasse wird nur bespielt, wenn sie
  den aktuellen Engpass liefert; Batch = min(Gold/15, Catpower/50, Ware, 5).
  Zusätzlich Gold-Cap-Schutz (Gold am Cap = verschenkter Handelsspielraum).
  Volle EV-Rechnung mit Saison/Standing folgt bei Bedarf in P1+.
- **Kundschafter:** neuer Handelspartner = Optionswert (Unlock 1.6),
  sobald 1000 Catpower verfügbar sind.
- **Praise (15.1):** Faith ≥ 95 % Cap → Praise (Cap-Verlust-Regel);
  vor Solar Revolution gibt es keinen Grund, Faith zu horten.
- **Festival (12.x):** ab Drama & bezahlbar (1500 Catpower / 5000 Culture /
  2500 Parchment, im Spiel fix verdrahtet); +30 % Happiness auf alles.

## Narration (`player/narrator.py`, Cockpit-Spec Kap. 18)

Deterministisch aus Templates: Erstereignis-Karten (erste Jagd, erster Handel,
erstes Festival, erstes Gebet, erstes Handwerk), Forschungs-Karten,
Meilenstein-Karten und Engpasswechsel (P3). Kein LLM, keine freie Textform.

## DecisionRecord (`brain/records.py`, Spec Kap. 23)

Jede Entscheidung enthält: Trigger, Phase/Run/Ziel, Engpass, **alle**
Kandidaten mit Score-Zerlegung und Ablehnungsgrund, Gewinner,
Ausführungsergebnis und beobachteten Effekt. Das ist die Datenquelle des
Decision Inspectors und des JSONL-Logs (Reproduzierbarkeit).

## M4–M7: Space, Time, Endgame

- **Craft-Kaskade (11.2 light):** Braucht ein Ziel Blueprints, steigt die
  Kaskade rekursiv ab (Parchment → Manuscript → Compendium → Blueprint) und
  craftet pro Zyklus die tiefste machbare Stufe.
- **Energie (16.4 / I-04):** Bei Energie-Defizit bekommen Erzeuger
  (Steamworks, Magneto, Solar Farm, Hydro, Reactor) Vorrang-Score 2.0.
- **Space:** Missionen sind Meilenstein-Ziele (Orbital Launch → Mond);
  Planeten-Gebäude generische Kandidaten mit Engpass-Kopplung
  (Lunar Outpost → Unobtainium usw.).
- **Time (17.x, Basisausbaustufe):** Chronoforge-Ausbau (Resource Retrieval
  priorisiert), Cryochambers; konservative Shatter-Regel: nur mit RR ≥ 1,
  Heat-Spielraum und 5-TC-Reserve, Batch ≤ 5.
- **TC-Schutz-Gate (I-02 / 9.1):** Reset mit ≥ 3 Time Crystals wird ohne
  Anachronomancy blockiert.
- **Run-Typen (8.2):** FIRST_RUN → PRICE_RATIO_RUN (Metaphysics-Kette
  Engineering…Renaissance + Chronomancy/Astromancy/Anachronomancy) →
  PARAGON_RUN.
- **Paragon-Speedrun (20.4):** Reset, wenn die marginale Paragonrate
  (5-min-Fenster) unter 50 % der Ø-Rate des Runs fällt; Mindestlaufzeit
  20 min, Mindestgewinn 10 Paragon.
- **TAP-light (15.2):** Vor jedem Reset wird Adore ausgeführt, wenn
  Apocrypha aktiv ist (Worship → permanente Epiphany). Transcend ist noch
  nicht automatisiert (Epiphany-Verlustrechnung).

## Bewusste Vereinfachungen gegenüber der Spec (Stand M7)

| Spec | Hier | Warum |
|---|---|---|
| Stochastische Vorwärtssimulation (Kap. 5) | Live-Raten + Formeln Anhang D | Spiel = Modell; transparent & robust |
| Exakte Schattenpreise λᵢ (10.2) | Engpass-ETA + Komponenten-Gewichte | deterministisch, im Cockpit erklärbar |
| MacroPlan ×3 Varianten (8.3) | ein Meilensteinpfad + Opportunismus | genügt bis P2; Erweiterungspunkt meta.py |
| Model-Mismatch-Stop (22.2) | Warnung + DEGRADED | privater Betrieb gegen Online-Spiel |
| Challenges (Kap. 18) | nicht automatisiert | irreversibel + regeländernd; Aktions-/Gate-Gerüst vorhanden |
| Policies (13.4) | nicht automatisiert | exklusiv-irreversibel; Panel-Scoping im Actor bereit |
| Pacts/Necrocorns (15.5), volle Shatter-Engine (17), Seed-/CS-Loops (19) | Grundbausteine (Leviathan-Handel, Shatter-Basis, Chronosphere-Kauf, Cryochambers) | exakte Endgame-Bilanzen wären eigene Modellierungsprojekte — Architektur (Ziel-Arten, Kandidaten, Gates) nimmt sie auf |

**Erweitern:** Neue Spielschicht = (1) Snapshot-Sektion in `driver/snapshot.js`,
(2) ggf. neue Ziel-Art in `tactics._target_prices/_target_obj/_milestone_candidate`,
(3) Kandidaten-Funktion mit Score-Komponenten, (4) Meilensteine in `meta.py`,
(5) Tests auf Snapshot-Fixtures. Das Cockpit zeigt alles automatisch über
DecisionRecords an.
