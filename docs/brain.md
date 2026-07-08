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
   (Kapazität × Bedarf/Kitten) muss über der Warnschwelle bleiben —
   bewusst worst-case (Kapazität sofort voll), auch wenn die echte
   Ankunftsrate bekannt ist (I-01 rechnet konservativ).
3. **Score:** 1.6 Basis + 0.4 Paragon-Grenzwert ab 68 Kitten + KittenValue
   (12.1): **ExpectedKittenArrivals** über die echte Ankunftsrate
   (`village.kittensPerSec`, #41) — Slots füllen sequenziell, Slot i
   arbeitet nur H − i/Rate; ohne Snapshot-Rate Fallback
   Sofort-Vollbelegung.

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
Zielmenge blockiert → Storage-Gate). λ berechnet sich seit #34 über den
**PFAD-Preisvektor** (`tactics.path_targets`): aktives Ziel (Rang 0), die
nächste Housing-Stufe (Rang 1, Kitten sind die Dauerressource des Pfads)
und alle offenen Meilensteine des Runs (`meta.MetaView.open_targets`) in
Listenreihenfolge, gekappt bei 12 Einträgen. Kombination als
**diskontiertes Maximum** `λᵢ = max_k(w_k·λᵢ^(k))` mit Rang-Gewicht
`w_k = 1/(1+k)` (`shadow.path_weight`): das Maximum, weil eine marginale
Einheit genau EIN sequenzielles Ziel bedient (eine Summe würde sie allen
gutschreiben); der Rang-Diskont, weil ETA-Diskontierung endogen wäre
(λ→Verhalten→ETA-Rückkopplung). Je Ziel rechnet `shadow._single_lambda`
die numerische Ableitung über die Engpass-ETA; Nicht-Zielressourcen erben
λ über die Craft-Kaskade (einmal über das kombinierte Maximum). Daraus
entstehen pro Kandidat `Cost_time`/`Benefit_time`/`NetValue` (10.2/10.3)
und die **Payback-Regel (10.4)**: reine Produktionskäufe, deren
Amortisation nach dem Run-Horizont läge, werden abgelehnt (Unlocks, Safety
und Meilenstein-Dependencies sind ausgenommen). Der Horizont ist seit #39
der **GEPLANTE Reset** (Spec 10.4/6.4): die Makroplan-Restzeit
(`run_plan["restzeitS"]`) fließt als `reset.evaluate["etaSeconds"]` in
`tactics.generate(run_horizon_s=…)` — nach unten auf
`HORIZON_PLANNED_MIN` gefloort (Anti-Deadlock), nach oben ungeklemmt
(lange Runs planen lang); ohne Projektion/Reset-Ziel bleibt
`shadow.run_horizon` (2×Spielzeit, [30 min, 4 h]) der Fallback.
Ohne λ-Daten greift überall die bisherige Heuristik (Sicherheitsnetz —
durch den Pfadvektor fast nie mehr aktiv). Die **Sparregel (10.3 DelayPenalty)** neutralisiert
zusätzlich den netValue-Bonus von Käufen, die das Sparziel verzögern —
sonst würde jeder Pfad-netValue am +Clamp die Penalty überstimmen.
Das Cockpit zeigt die **λ-Topliste** des Pfads im Economy-Tab
(`plan.lambdaTop`, Top 8 mit λ und λ̇).

### Echte Gebäudeeffekte (`tactics._rate_delta_from_effects`, Spec 13.1/13.2)

`driver/snapshot.js` exportiert je Gebäude das volle `effects`-Dict aus
`game.bld.buildingsData` (pro Einheit, stage-aware) plus eine
`pollution`-Sektion. `_building_rate_delta` übersetzt es in ein
mehrressourciges ΔRate inkl. Verbrauch: PerTickProd/Con/Base ×TPS
(catnipPerTickBase ×Saisonmodifikator), DemandRatio ×Bedarf, `<res>Ratio`
×beobachteter Rate, `coalRatioGlobal` nur beim ersten Exemplar (das Spiel
staffelt ihn nicht mit der Zahl), magnetoRatio/happiness/craftRatio als
dokumentierte Breitband-Näherungen. Steamworks/Magneto/Factory/Tradepost/
Mint/Brewery bekommen damit echte NetValues statt `economy 0.6`;
netto-negativer Nutzen (Steamworks-Kohle) läuft transparent in die
Payback-Ablehnung. **Pollution** kostet oberhalb der Spiel-Schwelle (5e8)
λ-bewertete Zielsekunden über verlangsamte Kitten-Ankünfte
(`_pollution_cost_time`, Komponente `pollutionCost`). Bewusst unbewertet:
tradeRatio/standingRatio (bereits in der Trade-EV 14.1), Festival-Effekte,
manuelle Craft-Nutzung des craftRatio. Ohne `effects` im Snapshot greift
die alte Beobachtungs-Heuristik (rate/count).

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
`storageB`/`storageC`, `leaderValue`, `pollutionCost`. Der Decision
Inspector zeigt damit die echten Zeit-Äquivalente jeder Entscheidung.

**Kaufregel (10.3):** ausgeführt wird der beste machbare Kandidat mit
Score > 0 — sonst WAIT. **Tie-Break (C.2):** bei Score-Gleichheit gewinnt
die lexikografisch kleinere Action-ID → deterministisch.

### Job-Marginalraten (12.2, #40)

JobScore und Soll-Allokation rechnen mit den BEOBACHTETEN effektiven
Pro-Kitten-Raten aus dem Spiel: snapshot.js exportiert je Job
`ratesPerKitten` (Nachbau von village.js `updateResourceProduction` für
ein marginales Skill-0-Kitten — verstärkte Happiness, Leader-Team-Boost —
multipliziert mit der calcResourcePerTick-Kette aus game.js: JobRatio-
Upgrades, Gebäude-/Religion-/Paragon-/Magneto-/Reaktor-Multiplikatoren,
Pollution, Solar Revolution, CMBR; Weather bewusst nicht — es wirkt im
Spiel VOR der Villager-Addition). `shadow.job_marginal_rates` behandelt
das Snapshot-Feld als autoritativ (auch leer); die statische Tabelle
`JOB_BASE_RATES × Happiness` ist nur noch Fallback ohne Snapshot-Daten.
Damit ist die Kitten-Beitrags-Subtraktion in `target_allocation` exakt
(vorher Phantom-Restrate: statische Basisraten von multiplikator-
behafteten Ist-Raten abgezogen).

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
- **Shatter-Engine (17.1–17.5, `brain/timecrystal.py`):** TC-Bilanz,
  RRValue/FurnaceValue steuern den Chronoforge-Ausbau; Shatter nach den
  Spec-Regeln A–D mit deterministischer Batch-Suche unter Heat-/Cap-
  Constraints und Cycle-Referenztabelle. Ohne λ-/Time-Daten greift die
  alte konservative Regel (RR ≥ 1, Heat-Spielraum, 5-TC-Reserve, Batch ≤ 5).
  Seit #43 sind die irreversiblen AUSGABE-Entscheidungen zustandsabhängig:
  `tc_opportunity_s` (max aus λ_TC am Ziel und λ-bewertetem Shatter-
  Jahresertrag der RR-Stufe) bepreist den TC-Einsatz in RRValue und
  Regel D; `paragon_value_s` = Δ`prestige.paragon_production_ratio`/
  (1+ratio) × Σλ·rate × Horizont ersetzt die 900-s-Konstante in Regel D.
  Die Konstanten `TC_VALUE_REF_S`/`PARAGON_VALUE_REF_S` sind nur noch
  Fallback ohne Daten. Bewusste Ausnahme: Regeln A/B behalten
  supplied-λ-sonst-Referenz — dort wäre λ_TC := Shatter-Ertrag
  selbstreferenziell (Regel A könnte nie feuern).
- **Chronosphere-Zielzahl (19.1, `brain/chrono.py`):** CSValue-Suche über
  n−2…n+3 (Carryover 1,5 %/CS, UO-Kosten über λ); gekauft wird nur bis zur
  optimalen Zahl, nicht mehr opportunistisch. RebuildDelay seit #43 als
  Engpass-ETA des Flotten-Wiederaufbaus aus beobachteten Raten
  (`_rebuild_eta_seconds`, Preisreihe wie `rebuild_cost_vector`);
  die 60-s-Konstante nur noch Fallback (`rebuildMode` transparent).
- **TC-Schutz-Gate (I-02 / 9.1):** Reset mit ≥ 3 Time Crystals wird ohne
  Anachronomancy blockiert.
- **Run-Typ-Wahl (8.2/8.3, `meta.determine_run_plan`):** alle **13
  Run-Typen** der Spec sind aktiv zulässig (Zulässigkeits-Gates bilden die
  9.2-Engine-Kaskade ab); je Typ drei Varianten (Minimal-/ausgeglichener/
  investitionsstarker Pfad) per EV-Projektion (`brain/simulate.py`);
  die Projektion lässt die **Population wachsen** (#36:
  `village.kittensPerSec` aus dem Snapshot, Housing-Kapazität als Grenze,
  Catnip-Mehrlast je Ankunft) — FIRST-/PARAGON-/PRICE_RATIO-Restzeiten
  sind damit zustandsabhängig statt eingefroren. Seit #38 sind ALLE
  Restzeiten projiziert: SEED = ETA der nächsten ganzen Carryover-Einheit
  (`chrono.seed_progress`), POSITIVE_CS = Verdienzeit der
  Wiederaufbaukosten, SHATTER-Ziel = Reserve + Heat-gedeckelter Batch
  (`meta._shatter_tc_target`), CHALLENGE = Zielprojektion
  (`challenge.completion_eta` — unbeobachtbar/unerreichbar → ehrlich ∞).
  Score vor der Progressionsfront = −Restzeit − Risikoterme (5.4-Proxys),
  nach der Front = E[ΔlnC/Δt] über den Endgame-Index C(S)
  (`brain/endgame.py`, Spec 6.3); Tie-Break lexikografisch (C.2).
  Die Gewinner-Restzeit (`run_plan["restzeitS"]`) ist zugleich der
  geplante-Reset-Horizont der Payback-Regel (#39).
  Makrophasen P0–P8 aus operationalen Austrittskriterien
  (`meta.determine_phase`).
- **Reset-Wert (20.1):** ResetValue = V(post) − V(continue) über die
  EV-Projektion am gleichen Realzeithorizont entscheidet den FIRST-Reset
  (Schwelle 35 bleibt notwendige Vorbedingung); Perk-Finanzierung bleibt
  harte Regel; beide V-Werte stehen im reason-Text. Seit #42 ist V(post)
  eine echte **Neustart-Kurzsimulation** (`reset._post_reset_paragon`:
  Carryover-Startkapital aus `chrono.carryover_vector`, Kitten wachsen
  mit der Ankunftsrate × Paragon-Bonus-Verhältnis — portiert aus
  prestige.js `getParagonProductionRatio` + game.js `getLimitedDR`);
  ohne beobachtete Ankunftsrate bleibt die lineare Rampe der Fallback
  (`vPostMode` macht den Pfad transparent).
- **Reset-Trigger je Run-Typ (20.2, #42):** RELIGION_RUN (TAP-Punkt via
  `transcend_value["worth"]`), UNICORN_RUN (Ziggurat + voller
  2500er-Opfer-Batch), SEED_RUN (Seed-Basis via
  `seed_progress["basisReached"]`) und POSITIVE_CS_RUN
  (`positive_cs_check`-Dominanz, ohne Paragon-Mindestgewinn) haben
  eigene, ResetValue-geprüfte Zweige VOR dem Perk-Catch-all in
  `reset.evaluate` — sie erreichen ihre Reset-Transaktion.
- **Leader (12.3):** Trait/Job-Paar per λ-Bewertung der Trait-Boni
  (`set_leader` via Census); Wechsel nur über 120-s-Gewinnschwelle.
- **Paragon-Speedrun (20.4):** Reset, wenn die marginale Paragonrate
  (5-min-Fenster) unter 50 % der Ø-Rate des Runs fällt; Mindestlaufzeit
  20 min, Mindestgewinn 10 Paragon.
- **TAP vollständig (15.2, `brain/religion.py`):** transcend_value rechnet
  die Epiphany-/Worship-Bilanz (Formeln aus religion.js); `tap_plan` liefert
  die geordneten Schritte Transcend→Adore→Praise, ausgeführt in der
  Pre-Reset-Transaktion. Alicorn→TC- und Tears→BLS-Konvertierung nach
  Grenzwertregel (15.4), Pacts über PactValue mit Upkeep/Debt/Siphoning
  (15.5) — alles irreversible Aktionen mit Commit-Grenze.
- **Pre-Reset-Transaktion (20.3):** `reset.execute_reset` folgt der vollen
  12-Schritt-Sequenz (Save-Export, Challenge-Verifikation, permanente
  Käufe, TAP, Konvertierungen, CS-/Cryo-Zielstand, Restwert-Crafts,
  Post-Reset-Projektion, harte Assertions, applyPending + Reset,
  Validierung); jeder Schritt einzeln als `reset.step`-Event geloggt.
- **Policies (13.4, `brain/policy.py`):** Bewertung über λ/Horizont mit
  I-07-Alternativenprüfung, 13.4-Startkandidaten als Suchraum-Prior;
  Kauf über die PolicyBtnController-API als irreversible Transaktion.
  Seit #37 deckt `POLICY_EFFECTS` alle 66 Policies der Referenzversion
  ab (Übersetzungs-Konventionen im Modul-Docstring; ehrlich nicht
  übersetzbare Effekte als `unratable` mit Wert 0 — die I-07-Prüfung
  entscheidet, kein stiller Ausschluss). Exklusive Zweige werden über
  den Restplan bewertet: `branch_value` = eigener Wert + unlocks-
  Nachfolger (BFS ≤ 3, je blocks-Gruppe das Maximum, harmonischer
  Diskont 1/(1+Tiefe)); i07_check/best_policy vergleichen Zweigwerte,
  der Horizont kommt aus `run_plan["restzeitS"]` (meta), falls endlich.
- **Challenges (18, `brain/challenge.py`):** Katalog aus challenges.js,
  ChallengeValue-Auswahl (18.2), CHALLENGE_RUN; Reset nur, wenn das Spiel
  die Challenge als erfüllt markiert (18.4). Seit #38 ist der
  ChallengeValue zustandsabhängig: Completion über die Zielprojektion
  (`completion_eta` je Challenge-Ziel), Belohnung über `reward_seconds`
  (Produktionszeit-Äquivalent übersetzbarer Effekte); die
  Referenzschätzungen sind NUR noch Fallback, wenn die Zielobjekte im
  Snapshot komplett fehlen — beobachtbar-unerreichbar zählt ehrlich 0.

## Governance-Kern (Spec G-02/G-06/G-10, Kap. 21–23)

- **AgentMode:** ACTIVE / MODEL_MISMATCH / SAFE_STOP. Versionsprüfung läuft
  periodisch. **Betreiberentscheidung (bewusste G-02-Abweichung):** Eine
  reine VERSIONSabweichung wird standardmäßig nur gemeldet (Badge +
  `model.version_mismatch`-Event), der Agent spielt weiter — der harte
  Stopp (nur READ_ONLY + Verbraucher-Abschalten, Reset gesperrt, Freigabe
  via `acknowledge_mismatch`) gilt erst mit `KGP_VERSION_GUARD_HARD=1`.
  Der Prognose-Streak-Stopp (nächster Punkt) bleibt davon unberührt
  immer hart — er zeigt echte Modellabweichung im Betrieb.
- **Prognose-Abgleich (G-10):** Aktionen tragen ein `predicted`-Dict;
  nach Ausführung wird die beobachtete Änderung mit Toleranz verglichen
  (`loop.check_prediction`), drei harte Abweichungen in Folge führen in
  MODEL_MISMATCH.
- **Ereignisgetriebenes Replanning (21):** `brain/scheduler.py` berechnet
  die nächste Weckzeit (Saison, ½-Cap, 10 %-ETA, 30-s-Kontrollpunkt);
  harte Trigger werden per Vorzyklus-Signatur klassifiziert; irreversible
  Aktionen laufen durch die Commit-Grenze (`loop.commit_guard`: Re-Read +
  Precondition unmittelbar vor Ausführung).
- **Deadlock (22.3):** kein positiver Kandidat + keine endliche
  Weckbedingung ⇒ Horizont ×2, dann Suchraum lockern, dann
  Frontier-Meldung — Sicherheitsinvarianten werden nie gelockert.

## Bewusste Näherungen gegenüber der Spec (Stand Spec-Vollausbau)

Alle 33 Zeilen des Spec-Audits sind umgesetzt ([spec-gaps.md](spec-gaps.md)).
Was bleibt, sind dokumentierte Näherungen — im Code jeweils als
REFERENZSCHÄTZUNG gekennzeichnet:

| Spec | Hier | Warum |
|---|---|---|
| Stochastische Vorwärtssimulation (Kap. 5) | deterministische **EV-Projektion** (`brain/simulate.py`) mit wachsender Population (#36); Zufallsaktionen als Erwartungswerte; Wachstumsstopp bei Hunger nicht modelliert (food_fatal deckt die Katastrophe) | transparent, deterministisch, testbar |
| Schattenpreise λᵢ (10.2) | numerische Ableitung über die Engpass-ETA je Pfadziel + Craft-Kaskade, kombiniert als rang-diskontiertes Maximum (`brain/shadow.py`, #34) | exakte ∂ETA/∂Rᵢ über den vollen Abhängigkeitsgraphen wäre Modellduplikat; ETA-Diskont wäre endogen |
| Gebäude-Ratio-Effekte (13.1) | Ratio × beobachtete Netto-Rate; magnetoRatio/happiness/craftRatio als Breitband-Näherung über die Ressourcenliste (#35) | die echte Basis-Produktion je Ressource ist im Snapshot nicht isolierbar; Näherung am Wert dokumentiert |
| CVaR-Risikoterme (5.4) | deterministische Proxys: P(fatal) = Food-Invariante im Horizont, Verlustterm ETA-basiert | echtes CVaR bräuchte Ergebnisverteilungen |
| Referenzkonstanten (TC-/Necrocorn-Zeitwerte, Endgame-bᵢ, einzelne Policy-/Trait-Effekte; Challenge-Referenzen seit #38 nur noch Fallback ohne Snapshot-Zielobjekte) | dokumentierte Schätz-/Normierungswerte mit gamefiles-Fundstelle am Wert | beeinflussen Prioritäten, nicht die Korrektheit der Gates; bei Prognose-Abweichung im Betrieb durch gemessene Raten ersetzen |
| Late-Game-Live-Nachweis (Pacts, Leviathans, Relic, Void, Challenges) | gegen gamefiles-Formeln + synthetische Fixtures getestet | Live-Validierung braucht fortgeschrittene Spielstände; der Governance-Kern (Prognose-Abgleich, MODEL_MISMATCH) fängt Abweichungen ab |

**Erweitern:** Neue Spielschicht = (1) Snapshot-Sektion in `driver/snapshot.js`,
(2) ggf. neue Ziel-Art in `tactics._target_prices/_target_obj/_milestone_candidate`,
(3) Kandidaten-Funktion mit Score-Komponenten, (4) Meilensteine in `meta.py`,
(5) Tests auf Snapshot-Fixtures. Das Cockpit zeigt alles automatisch über
DecisionRecords an.
