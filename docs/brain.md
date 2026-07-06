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

### Engpass & Schattenpreise (`brain/shadow.py`, Spec 10.1–10.4)

Der Engpass ist die Ressource mit der größten Zeit-bis-leistbar am aktiven
Ziel (`eta = fehlend / netRate`; ∞ bei Rate ≤ 0 oder wenn das **Cap** die
Zielmenge blockiert → Storage-Gate). Darauf aufbauend berechnet
`shadow.shadow_prices` **echte Schattenpreise** λᵢ (Sekunden Zielzeit pro
Einheit, numerische Ableitung über die Engpass-ETA; Nicht-Zielressourcen
erben λ über die Craft-Kaskade). Daraus entstehen pro Kandidat
`Cost_time`/`Benefit_time`/`NetValue` (10.2/10.3) und die **Payback-Regel
(10.4)**: reine Produktionskäufe, deren Amortisation nach dem Run-Horizont
läge, werden abgelehnt (Unlocks, Safety und Meilenstein-Dependencies sind
ausgenommen). Ohne λ-Daten greift überall die bisherige Heuristik.

### Score-Komponenten (additiv, alle im Cockpit sichtbar)

| Komponente | Wert | Bedeutung |
|---|---|---|
| safety | 10.0 | Schutzaktion (Vorrang G-04) |
| milestone | 3.0 | Ziel direkt kaufen/erforschen |
| jobValue | 2.4–2.6 | freies Kitten → Job mit höchstem JobScore (12.2) |
| bottleneck | 1.8–2.0 | Engpass lösen (Refine, Engpass-Gebäude) |
| unlock | 1.4–1.9 | Forschung/Upgrades (Unlock-first, 13.3) |
| storage | 1.0–2.2 | Storage-Regel 11.3 A–D (Cap-Blockade, Carryover, Pufferverlust, Challenge) |
| housing | 1.6 | Hütte etc., nur bei sicherer Food-Lage (12.1) |
| capLoss | 1.5–1.6 | Jagd/Craft nahe Cap (11.4) |
| energyRelief | 1.0–1.5 | Verbraucher drosseln/reaktivieren nach Grenznutzen (16.4) |
| happiness | 1.2–1.8 | Festival / Amphitheater (Happiness = globaler Produktionsmultiplikator) |
| economy | 0.6 | generischer Ausbau |
| opportunity | −0.7 | Kauf verbraucht die für den Engpass reservierte Ressource (10.2) |
| WAIT | 0.01 | immer möglich, mit Grund + Weckbedingung (G-05) |

Zusätzlich tragen Kandidaten **Sekundenwert-Komponenten** (reine Anzeige,
nicht additiv): `costTime`/`benefitTime`/`netValue` (Schattenpreis-Rechnung;
netValue fließt normiert in den Score ein: 60 s ≙ 1 Punkt, Clamp ±1,2),
`jobScore`, `tradeValue`, `huntValue`, `praiseValue`, `csValue`,
`storageB`/`storageC`, `leaderValue`. Der Decision Inspector zeigt damit
die echten Zeit-Äquivalente jeder Entscheidung.

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

- **Handel (14.1, TradeValue-EV):** `TradeValue(race) = Σ P(o)·λ-Wert(o) −
  λ-Kosten` über die Ergebnisverteilung aus dem Snapshot (sells-Chancen,
  Saison-Deltas, Standing, +1 %/Trade Ship); gehandelt wird nur bei positivem
  EV. Batch = min(Gold/15, Catpower/50, Ware, 5) und Gold-Cap-Schutz bleiben;
  ohne Race-/λ-Daten greift die alte Engpass-Regel.
- **Kundschafter:** neuer Handelspartner = Optionswert (Unlock 1.6),
  sobald 1000 Catpower verfügbar sind.
- **Jagd (14.2):** Jagd als Trade mit Referenz-Beuteverteilung (Furs/Ivory/
  Unicorn je 100 Catpower): sofort bei Cap-Druck (60-s-Puffer) oder wenn der
  λ-Sofortnutzen den Batch-Vorteil übersteigt; sonst sammeln. Fallback: 85 %.
- **Praise (15.1, EV):** Praise, wenn der drohende Faith-Cap-Verlust
  (× λ_faith) den Wert des Haltens übersteigt; die Sparregel für anstehende
  Religion-Käufe bleibt vorrangig. Fallback: 95 %-Cap-Schwelle.
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
  Zusätzlich **Verbraucher-Drosselung**: der aktive Verbraucher mit dem
  kleinsten λ-Zielbeitrag je Energieeinheit wird deaktiviert
  (`toggle_building`, lebenswichtige Gebäude nie); Reaktivierung in
  Grenznutzen-Reihenfolge mit Hysterese gegen Flattern.
- **Space:** Missionen sind Meilenstein-Ziele (Orbital Launch → Mond);
  Planeten-Gebäude generische Kandidaten mit Engpass-Kopplung
  (Lunar Outpost → Unobtainium usw.).
- **Time (17.x, Basisausbaustufe):** Chronoforge-Ausbau (Resource Retrieval
  priorisiert), Cryochambers; konservative Shatter-Regel: nur mit RR ≥ 1,
  Heat-Spielraum und 5-TC-Reserve, Batch ≤ 5.
- **Chronosphere-Zielzahl (19.1, `brain/chrono.py`):** CSValue-Suche über
  n−2…n+3 (Carryover 1,5 %/CS, UO-Kosten über λ); gekauft wird nur bis zur
  optimalen Zahl, nicht mehr opportunistisch.
- **TC-Schutz-Gate (I-02 / 9.1):** Reset mit ≥ 3 Time Crystals wird ohne
  Anachronomancy blockiert.
- **Run-Typ-Wahl (8.3, `meta.determine_run_plan`):** zulässige Run-Typen
  (FIRST/PRICE_RATIO/PARAGON) × drei Varianten (Minimal-/ausgeglichener/
  investitionsstarker Pfad) werden per EV-Projektion (`brain/simulate.py`)
  simuliert; Score = −Restzeit zum Run-Ziel, Tie-Break lexikografisch (C.2).
  Die 13 Run-Typen aus Spec 8.2 sind als Konstanten angelegt; zulässig sind
  bislang drei.
- **Reset-Wert (20.1):** ResetValue = V(post) − V(continue) über die
  EV-Projektion am gleichen Realzeithorizont entscheidet den FIRST-Reset
  (Schwelle 35 bleibt notwendige Vorbedingung); Perk-Finanzierung bleibt
  harte Regel; beide V-Werte stehen im reason-Text.
- **Leader (12.3):** Trait/Job-Paar per λ-Bewertung der Trait-Boni
  (`set_leader` via Census); Wechsel nur über 120-s-Gewinnschwelle.
- **Paragon-Speedrun (20.4):** Reset, wenn die marginale Paragonrate
  (5-min-Fenster) unter 50 % der Ø-Rate des Runs fällt; Mindestlaufzeit
  20 min, Mindestgewinn 10 Paragon.
- **TAP-light (15.2):** Vor jedem Reset wird Adore ausgeführt, wenn
  Apocrypha aktiv ist (Worship → permanente Epiphany). Transcend ist noch
  nicht automatisiert (Epiphany-Verlustrechnung).

## Bewusste Vereinfachungen gegenüber der Spec (Stand Schattenpreis-Ausbau)

| Spec | Hier | Warum |
|---|---|---|
| Stochastische Vorwärtssimulation (Kap. 5) | deterministische **EV-Projektion** (`brain/simulate.py`) für Makro-Entscheidungen; Taktik weiter auf Live-Raten | Erwartungswerte statt Monte-Carlo: transparent, deterministisch, testbar |
| Schattenpreise λᵢ (10.2) | numerische Ableitung über die Engpass-ETA + Craft-Kaskade (`brain/shadow.py`) | exakte ∂ETA/∂Rᵢ über den vollen Abhängigkeitsgraphen wäre Modellduplikat; Näherungen im Modul dokumentiert |
| Model-Mismatch-Stop (22.2) | Warnung + DEGRADED | privater Betrieb gegen Online-Spiel |
| Challenges (Kap. 18) | nicht automatisiert | irreversibel + regeländernd; Aktions-/Gate-Gerüst vorhanden |
| Policies (13.4) | nicht automatisiert | exklusiv-irreversibel; Panel-Scoping im Actor bereit |
| Pacts/Necrocorns (15.5), volle Shatter-Engine (17), Seed-/CS-Loops (19.2+) | Grundbausteine (Leviathan-Handel, Shatter-Basis, CS-Zielzahl-Suche, Cryochambers) | exakte Endgame-Bilanzen wären eigene Modellierungsprojekte — Architektur (Ziel-Arten, Kandidaten, Gates) nimmt sie auf |

**Erweitern:** Neue Spielschicht = (1) Snapshot-Sektion in `driver/snapshot.js`,
(2) ggf. neue Ziel-Art in `tactics._target_prices/_target_obj/_milestone_candidate`,
(3) Kandidaten-Funktion mit Score-Komponenten, (4) Meilensteine in `meta.py`,
(5) Tests auf Snapshot-Fixtures. Das Cockpit zeigt alles automatisch über
DecisionRecords an.
