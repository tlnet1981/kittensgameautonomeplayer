# Autonome Optimimale Spiel-Mechanik

> Konvertiert aus „Autonome_Optimimale_SpielMechanik.docx".
>
> **End-to-End-Systemspezifikation für einen vollständig autonomen Optimal-Play-Agenten für Kittens Game**
>
> **Finale Architekturentscheidung:** Kein Mensch im Steuerkreis. Kein LLM. Der Agent ist version-gebunden, modellbasiert, hierarchisch planend, stochastisch prognostizierend und deterministisch in seiner Aktionsauswahl.
>
> Spezifikationsstand: 6. Juli 2026
> Zielversion: Kittens Game 1.5.0.2, Build Revision 3
> Status: Finales fachliches Konzept

## Dokumentensteuerung

| Merkmal | Festlegung |
|---|---|
| Dokumenttitel | Autonome Optimimale Spiel-Mechanik |
| Systemzweck | Vollständig autonomes Spielen von Kittens Game mit maximaler langfristiger Progression pro realer Zeit. |
| Steuerungsmodell | Hierarchischer modellbasierter Optimierungsagent mit deterministischer Policy über einem stochastischen Spielprozess. |
| Laufzeit-KI | Kein LLM und keine sprachbasierte Entscheidungsinstanz. |
| Referenzversion | Kittens Game 1.5.0.2; Build Revision 3. |
| Ausführungsmodus | Autonom, ereignisgetrieben, mit kontinuierlichem Replanning. |
| Normativer Status | MUSS/DARF NICHT-Regeln sind verbindlich; Implementierungsdetails sind daraus abzuleiten. |

## Inhaltsübersicht

1. Zweck, Scope und Optimierungsdefinition
2. Normative Grundentscheidungen
3. Gesamtarchitektur und Datenfluss
4. Vollständiges Zustands- und Datenmodell
5. Kanonisches Spielmodell und Prognose
6. Zielfunktion und Wertmodell
7. Sicherheits- und Zulässigkeitslogik
8. Strategischer Meta-Controller
9. Progressionsfront und Makrophasen
10. Taktischer Optimierer
11. Ressourcen-, Craft- und Storage-Logik
12. Bevölkerung, Jobs und Leader
13. Gebäude, Upgrades, Forschung und Policies
14. Handel, Jagd und Zufallsereignisse
15. Religion, Unicorns, Pacts und Transcendence
16. Space, Antimatter und Energie
17. Time Crystals, Relics, Shattering und Heat
18. Challenges
19. Chronospheres, Void und Reset-Loops
20. Reset-Entscheidung und Reset-Transaktion
21. Ereignisscheduler und Replanning
22. Aktionsausführung, Transaktionen und Fehlerbehandlung
23. Protokollierung, Erklärbarkeit und Reproduzierbarkeit
24. Verifikation und Abnahmekriterien

Anhänge: Datenverträge, Formeln, Entscheidungsreferenz und Quellenbasis

## 1. Zweck, Scope und Optimierungsdefinition

### 1.1 Systemzweck

Das System übernimmt die vollständige Steuerung eines Kittens-Game-Spielstands. Es liest den vollständigen Zustand, prognostiziert die Folgen verfügbarer Aktionen, wählt die global zweckmäßigste Strategie, führt die notwendigen Teilaktionen aus und bewertet den Zustand nach jedem relevanten Ereignis neu.

Der Systemzweck ist nicht das Nachspielen einer festen Community-Build-Order. Der Systemzweck ist die autonome Ermittlung und Ausführung der bestbewerteten Policy für den jeweils aktuellen Zustand.

### 1.2 Verbindlicher Scope

- Versionsgebundene Unterstützung der Referenzversion 1.5.0.2 einschließlich Stasis Pod, Frescoes, Alicornmancy, Pact of Arcane, Pact of Chronicler und des aktuellen Unicorn-Tears-Challenge-Rewards.
- Vollständige Abdeckung aller Ressourcen, Gebäude, Upgrades, Forschung, Policies, Religion, Space, Time, Void, Challenges, Reset- und Carryover-Systeme.
- Autonome Auswahl von Makrostrategie, Run-Typ, Zwischenzielen, Käufen, Jobverteilung, Trades, Crafts, Faith-Aktionen, Shatters und Resets.
- Behandlung stochastischer Ereignisse über exakte Wahrscheinlichkeitsmodelle und Erwartungswertplanung.
- Keine Abhängigkeit von Nutzerinteraktion, Textinterpretation, Community-Livewissen oder externen Sprachmodellen.

### 1.3 Definition von optimalem Spielen

> **Verbindliche Zielfunktion:** Bis zum Erreichen der endlichen Progressionsfront minimiert das System die erwartete reale Zeit bis zur vollständigen Erfüllung aller einmaligen Progressionsmeilensteine. Nach Erreichen dieser Front maximiert es die langfristige logarithmische Wachstumsrate der persistenten Endgame-Fähigkeit.

Die endliche Progressionsfront F umfasst alle einmaligen Forschungs-, Upgrade-, Metaphysics-, Space-, Religion-, Time-, Void- und Challenge-Freischaltungen sowie jeden erstmaligen Challenge-Abschluss. Wiederholbare Challenge-Stufen und unbeschränkt skalierbare Ressourcen gehören nicht zu F.

```
Vor F:   π* = arg minπ  Eπ[T(F | S0)]
Nach F:  π* = arg maxπ  lim inf(T→∞) [ ln C(S_T) − ln C(S_0) ] / T
```

C(S) ist der Endgame-Fähigkeitsindex. Er wird als geometrisches Mittel der normalisierten persistenten Wachstumsraten definiert: Paragon/Burnt-Paragon-Wirkung, Epiphany- und Transcendence-Wirkung, Time-Crystal-Nettoertrag, Relic-Ertrag, Antimatter-Ertrag, Void-Ertrag und positive Chronosphere-Carryover-Leistung. Das geometrische Mittel verhindert, dass das System eine einzelne Ressource maximiert und andere für den Endgame-Kreislauf notwendige Dimensionen vernachlässigt.

```
C(S) = ( Π_i max(ε, r_i / b_i) )^(1/n)
```

r_i bezeichnet die prognostizierte nachhaltige Rate der Dimension i; b_i ist die feste Referenzrate der jeweiligen Dimension; ε verhindert Nullwerte. Die Referenzraten sind reine Normierungsgrößen und beeinflussen bei geometrischem Mittel nur die Skalierung, nicht die Rangfolge proportionaler Zustände.

### 1.4 Determinismus

Die Spielumgebung enthält Zufall. Die Policy ist dennoch deterministisch: Bei identischem Zustand, identischem Modellstand und identischer Versionskennung wählt das System dieselbe Aktion. Zufällige Folgezustände führen anschließend zu einer erneuten deterministischen Bewertung.

```
A_t = arg max_a  E[V(S_{t+1:t+H}) | S_t, a]
```

## 2. Normative Grundentscheidungen

| ID | Verbindliche Entscheidung |
|---|---|
| G-01 | Der Agent enthält kein LLM und keine freie natürlichsprachliche Entscheidungslogik. |
| G-02 | Die Spielversion MUSS vor Start gegen die Referenzversion geprüft werden. Bei Abweichung DARF der Agent keine irreversible Aktion ausführen. |
| G-03 | Alle numerischen Spielmechaniken werden aus dem kanonischen Modell der Zielversion geladen; Community-Heuristiken dienen ausschließlich als initiale Suchraumreduktion. |
| G-04 | Sicherheitsinvarianten haben Vorrang vor Nutzenoptimierung. |
| G-05 | Das System MUSS Warten als reguläre Aktion berücksichtigen. |
| G-06 | Jede irreversible Aktion wird vor Ausführung vollständig simuliert und transaktional geprüft. |
| G-07 | Makroentscheidungen werden mit einem rollierenden Planungshorizont und Terminalwert getroffen. |
| G-08 | Mikroentscheidungen werden durch exakte Engpass-, Schattenpreis- und Payback-Berechnung getroffen. |
| G-09 | Ein Reset ist eine geplante Transaktion und niemals eine lokale Einzelaktion. |
| G-10 | Abweichungen zwischen prognostiziertem und beobachtetem Zustand lösen einen Model-Mismatch-Stop aus. |

## 3. Gesamtarchitektur und Datenfluss

```
Spielzustand / Save / Runtime-API
        │
        ▼
[1] Version Guard & State Extractor
        │
        ▼
[2] State Normalizer & Derived Metrics
        │
        ▼
[3] Safety / Constraint Engine
        │
        ▼
[4] Strategic Meta-Controller
        │
        ▼
[5] Macro Plan Generator
        │
        ▼
[6] Stochastic Forward Simulator
        │
        ▼
[7] Tactical Optimizer
        │
        ▼
[8] Transactional Action Executor
        │
        ▼
[9] Observation, Audit, Replanning
```

### 3.1 Komponentenverantwortung

| Komponente | Eingabe | Ausgabe | Verantwortung |
|---|---|---|---|
| Version Guard | Runtime-Version, Build-Revision | Freigabe oder Stop | Verhindert Modellbetrieb gegen unbekannte Mechanik. |
| State Extractor | Spielobjekte/Save | RawState | Liest alle spielrelevanten Felder atomar. |
| Normalizer | RawState | CanonicalState | Einheiten, Modifier, Netto-Raten, Caps, Unlocks. |
| Constraint Engine | CanonicalState | AdmissibleActionSet | Entfernt unzulässige oder verlustreiche Aktionen. |
| Meta-Controller | CanonicalState, MilestoneGraph | MacroObjective | Wählt den nächsten strategischen Fortschrittsblock. |
| Macro Planner | MacroObjective | PlanCandidates | Erzeugt vollständige Run- und Reset-Pläne. |
| Simulator | State, PlanCandidates | OutcomeDistributions | Prognostiziert deterministische und zufällige Folgen. |
| Tactical Optimizer | Plan, aktuelle Engpässe | ActionSchedule | Jobs, Käufe, Crafts, Trades, Aktivierungen. |
| Executor | ActionSchedule | ExecutionResult | Transaktionale und idempotente Ausführung. |
| Auditor | Prediction, Observation | Trace, Mismatch | Reproduzierbarkeit und Modellvalidierung. |

### 3.2 Steuerzyklus

```
LOOP:
  1. Zustand atomar erfassen.
  2. Version und Modellkonsistenz prüfen.
  3. Abgeleitete Kennzahlen berechnen.
  4. Sicherheitsinvarianten prüfen.
  5. Fortschrittsfront und strategisches Ziel bestimmen.
  6. Makropläne erzeugen und simulieren.
  7. Besten Plan nach Zielfunktion wählen.
  8. Taktische Aktionen bis zum nächsten Replanning-Trigger planen.
  9. Genau eine irreversible oder eine sichere Aktionscharge ausführen.
 10. Ergebnis beobachten und Prognoseabweichung prüfen.
 11. Bei Trigger oder Abweichung zu Schritt 1 zurückkehren.
```

## 4. Vollständiges Zustands- und Datenmodell

### 4.1 CanonicalState

```
CanonicalState
├─ identity: version, build, save_id, timestamp
├─ calendar: year, season, day, cycle, festival, flux, heat
├─ resources: Map<ResourceId, ResourceState>
├─ population: PopulationState
├─ jobs: Map<JobId, JobState>
├─ leader: LeaderState
├─ buildings: Map<BuildingId, BuildingState>
├─ upgrades: Map<UpgradeId, UnlockState>
├─ science: ResearchState
├─ policies: PolicyState
├─ religion: ReligionState
├─ unicorn: UnicornState
├─ pacts: PactState
├─ diplomacy: DiplomacyState
├─ space: SpaceState
├─ time: TimeState
├─ void: VoidState
├─ challenges: ChallengeState
├─ prestige: PrestigeState
├─ energy: EnergyState
├─ pollution: PollutionState
├─ automation: AutomationState
├─ reset: ResetProjection
└─ derived: DerivedMetrics
```

### 4.2 ResourceState

| Feld | Typ/Einheit | Bedeutung |
|---|---|---|
| id | Enum | Stabile Ressourcenkennung. |
| amount | double | Aktueller Bestand. |
| capacity | double | Aktuelle Obergrenze. |
| gross_rate | Einheiten/s | Produktion vor Verbrauch. |
| consumption_rate | Einheiten/s | Laufender Verbrauch. |
| net_rate | Einheiten/s | gross_rate minus consumption_rate. |
| season_rates | 4 × Einheiten/s | Prognose je Saison. |
| cycle_rates | Map | Prognose je Cycle. |
| fill_time | s | Zeit bis Cap. |
| depletion_time | s | Zeit bis Null. |
| carryover_class | Enum | Verlust, geschützt, proportional, vollständig. |
| craft_inputs/outputs | Graph edges | Rezeptbeziehungen. |
| shadow_price | s/Einheit | Marginale Zielzeitverkürzung. |
| criticality | 0..1 | Normierte Engpassrelevanz. |

### 4.3 PopulationState

- current_kittens, housing_capacity, free_housing, arrival_rate und arrival_eta.
- Worst-Case-Catnipbedarf der gesamten Population einschließlich Challenge-, Happiness- und Policy-Modifikatoren.
- Jobverteilung, individuelle Skills, Leader-Trait, Leader-Job und Promotionsstatus.
- Erwartetes Reset-Paragon, Cryochamber-/Stasis-Pod-Zuordnung und übertragbare Kitten.
- Happiness, Unhappiness und effektiver Produktionsfaktor.

### 4.4 Action

```
Action
├─ action_id
├─ type
├─ target_id
├─ quantity
├─ preconditions
├─ immediate_cost_vector
├─ continuous_effect_delta
├─ unlock_delta
├─ irreversible_flags
├─ rng_distribution
├─ expected_duration
├─ execution_atomicity
├─ rollback_possible
└─ postcondition_assertions
```

### 4.5 MacroPlan

```
MacroPlan
├─ objective_id
├─ entry_conditions
├─ ordered_milestones
├─ target_run_type
├─ target_reset_condition
├─ mandatory_constraints
├─ tactical_policy_profile
├─ expected_duration_distribution
├─ expected_persistent_gain
├─ expected_frontier_gain
├─ terminal_state_distribution
└─ abort/replan_conditions
```

## 5. Kanonisches Spielmodell und Prognose

### 5.1 Versionsbindung

Das kanonische Modell ist an Kittens Game 1.5.0.2 und Build Revision 3 gebunden. Die Zielversion wird aus den Runtime-Metadaten gelesen. Eine unbekannte Version setzt den Agenten in MODEL_MISMATCH. In diesem Zustand sind ausschließlich exportierende, lesende und sicher deaktivierende Aktionen zulässig.

### 5.2 Zustandsübergang

```
S(t + Δt) = F(S(t), A[t,t+Δt], E[t,t+Δt], Δt)
```

F ist das exakte Spielmodell. A enthält diskrete Aktionen und aktive Dauerzustände. E enthält Zufallsereignisse. Kontinuierliche Produktion wird zwischen diskreten Ereignissen stückweise integriert.

### 5.3 Ereigniswarteschlange

- Saisonwechsel, Tageswechsel und Cycle-Wechsel.
- Ressourcen-Cap oder Ressourcen-Depletion.
- Kitten-Ankunft.
- Festivalende und Tempus-Fugit-Ende.
- Heat-Grenze oder vollständiger Heat-Abbau.
- Fertigstellung eines Sparziels.
- Freischaltung einer Aktion.
- Zufallsereignis mit modellierter Hazard Rate.
- Geplanter Kontrollpunkt des MPC-Horizonts.

### 5.4 Zufallsmodell

Für jede stochastische Aktion enthält das Modell eine vollständige Ergebnisverteilung. Die Verteilung stammt aus der Referenzimplementierung. Monte-Carlo-Sampling dient nur der numerischen Auswertung komplexer Sequenzen; die zugrunde liegenden Wahrscheinlichkeiten werden nicht durch ein Sprachmodell geschätzt.

```
Q(S,a) = E[V(S′) | S,a] − λ · CVaR_α(loss)
```

Vor der endlichen Progressionsfront gilt λ nur für irreversible Fehlschläge und Reset-Verluste. Bei wiederholbaren ökonomischen Aktionen wird risiko-neutral nach Erwartungswert optimiert, sofern kein harter Deadline- oder Sicherheitsconstraint betroffen ist.

## 6. Zielfunktion und Wertmodell

### 6.1 Fortschrittsfront

Der MilestoneGraph enthält alle einmaligen Progressionsobjekte. Ein Meilenstein gilt erst als erfüllt, wenn die Mechanik nicht nur freigeschaltet, sondern operational nutzbar ist. Beispiel: Eine Relic Station ist erst operational, wenn die erforderliche Antimatter-Kapazität und Energieversorgung vorhanden ist.

| Meilensteinklasse | Erfüllungskriterium |
|---|---|
| Research/Workshop | Erworben und alle unmittelbaren Pflichtabhängigkeiten erfüllt. |
| Metaphysics | Erworben; notwendige Paragonreserve für den Folgepfad nicht verletzt. |
| Religion | Freigeschaltet und zugehöriger Produktionskreislauf funktionsfähig. |
| Space | Mission/Objekt freigeschaltet und Mindestversorgung für Nutzung vorhanden. |
| Time/Relic | Positiver oder strategisch notwendiger Ressourcenfluss nachgewiesen. |
| Challenge | Erstabschluss registriert. |
| Chronosphere | Positive Carryover-Schleife oder definierter Seed-Meilenstein nachgewiesen. |

### 6.2 Planbewertung vor F

```
Score(plan) = −E[T_F | plan] − κ·P(fatal failure) − μ·E[irreversible loss]
```

Der Plan mit der kleinsten erwarteten Restzeit bis F gewinnt. Zwischen Plänen mit statistisch nicht unterscheidbarer Restzeit entscheidet in dieser Reihenfolge: geringere irreversible Verluste, geringere Varianz, geringere Aktionszahl, lexikografisch kleinere Action-ID. Damit bleibt die Policy deterministisch.

### 6.3 Planbewertung nach F

```
Score(plan) = E[Δ ln C / Δt] − κ·CVaR_0.05(loss_rate)
```

Der Endgame-Fähigkeitsindex C besteht aus den nachhaltigen, nach Reset reproduzierbaren oder persistenten Raten der zentralen Endgame-Kreisläufe. Nur Raten unter stabilen Energie-, Food-, Heat- und Carryover-Bedingungen zählen.

### 6.4 Planungshorizont

Der Agent verwendet hierarchisches Model Predictive Control. Der Makrohorizont endet am nächsten dauerhaften Milestone oder Reset und reicht mindestens über einen vollständigen Run. Der taktische Horizont endet am nächsten diskreten Replanning-Ereignis. Terminalwerte approximieren die Restzeit bis F beziehungsweise die Endgame-Wachstumsrate.

## 7. Sicherheits- und Zulässigkeitslogik

### 7.1 Harte Invarianten

| Invariant | Regel |
|---|---|
| I-01 Food | Die prognostizierte Catnip-Reserve DARF vor dem nächsten sicheren Eingriffspunkt nicht auf Null fallen. |
| I-02 Reset-Schutz | Geschützte persistente Ressourcen und Challenge-Erfolg MÜSSEN vor Reset verifiziert sein. |
| I-03 Version | Bei Versions- oder Modellabweichung sind irreversible Aktionen gesperrt. |
| I-04 Energie | Für Antimatter-, Relic- und dauerhafte Space-Produktion MUSS der relevante Energiezustand positiv sein. |
| I-05 Heat | Shattering DARF das geplante Heat-Limit nicht unkontrolliert überschreiten. |
| I-06 Cap | Ein kritischer Ressourcen-Cap DARF nur erreicht werden, wenn der Cap-Verlust im Plan bewertet und akzeptiert ist. |
| I-07 Policy | Eine exklusive Policy DARF nur gewählt werden, wenn alle ausgeschlossenen Alternativen im Planwert berücksichtigt wurden. |
| I-08 Transaktion | Kosten, Precondition und Postcondition einer Aktion MÜSSEN atomar zusammenpassen. |

### 7.2 Food-Sicherheitsmodell

```
ReserveTime_food = CatnipAmount / max(ε, −WorstCaseNetCatnip)
```

WorstCaseNetCatnip ist das Minimum über alle bis zum nächsten Replanning erwartbaren Saison-/Cycle-/Challenge-Zustände. Housing und Jobentzug von Farmern sind unzulässig, wenn die ReserveTime unter den Sicherungshorizont fällt.

```
Sicherungshorizont = max(
    Zeit bis zum nächsten geplanten Eingriff,
    Zeit bis zum nächsten Saisonwechsel,
    Zeit bis zur nächsten Kitten-Ankunft,
    2 × Modell-Latenz
) + Sicherheitsmarge
```

### 7.3 Energie-Zulässigkeit

Der Agent unterscheidet harte und weiche Energieanforderungen. Harte Anforderungen bestehen für Mechaniken, deren Output bei Defizit vollständig oder wesentlich ausfällt. Weiche Defizite sind ausschließlich in kurzen, simulierten Runs zulässig, wenn der gesamte Plan trotz Defizit eine kleinere Restzeit bis zum Ziel besitzt.

### 7.4 Irreversible Aktionen

- Reset, Metaphysics-Kauf, Challenge-Aktivierung, exklusive Policy-Wahl, Transcend, Adore, Alicorn-Konvertierung, Tear-Refinement, Pact-Kauf und große Time-Crystal-Shatter-Batches gelten als irreversibel.
- Vor einer irreversiblen Aktion MUSS der Simulator die vollständige Transaktion bis zum nächsten stabilen Zustand bewerten.
- Der Executor MUSS unmittelbar vor der Aktion den Zustand erneut lesen und sämtliche Precondition-Hashes vergleichen.

## 8. Strategischer Meta-Controller

### 8.1 Aufgabe

Der Meta-Controller wählt selbstständig den nächsten Run-Typ und das nächste dauerhafte Ziel. Er erhält keine Zielvorgabe von einem Menschen. Er bewertet alle aktuell zulässigen Makropläne nach der Zielfunktion aus Abschnitt 6.

### 8.2 Makroplan-Kandidaten

| Run-Typ | Primärer Zweck |
|---|---|
| FIRST_RUN | Erster sinnvoller Paragon-Reset und Apocrypha-Basis. |
| PRICE_RATIO_RUN | Kauf des nächsten Price-Ratio-Metaphysics. |
| CORE_META_RUN | Anachronomancy, Megalomania, Numerology/Numeromancy und weitere Pfad-Metas. |
| RELIGION_RUN | Transcendence-Tier, Epiphany und Solar-Revolution-Skalierung. |
| UNICORN_RUN | Unicorn-, Tear-, Alicorn- und Black-Liquid-Sorrow-Infrastruktur. |
| CHALLENGE_RUN | Erstabschluss oder wirtschaftlich dominierende Wiederholung. |
| LEVIATHAN_RUN | Time-Crystal- und frühe Relic-Gewinnung über Leviathans. |
| RELIC_STATION_RUN | Antimatter- und Relic-Station-Infrastruktur. |
| SHATTER_RUN | Aufbau oder Nutzung einer profitablen Resource-Retrieval-Engine. |
| PARAGON_RUN | Maximierung des erwarteten Paragon-Ertrags pro Realzeit. |
| SEED_RUN | Antimatter-, Void-, Storage- und Cryptotheology-Seed. |
| POSITIVE_CS_RUN | Positive Chronosphere-Carryover-Schleife. |
| MATURE_ENDGAME_RUN | Maximierung der langfristigen persistenten Wachstumsrate. |

### 8.3 Auswahlalgorithmus

```
1. Erzeuge für jeden zulässigen Run-Typ einen vollständigen MacroPlan.
2. Setze Zielmeilensteine aus dem MilestoneGraph ein.
3. Erzeuge für jeden Plan mindestens drei taktische Varianten:
   a) schneller Minimalpfad,
   b) ausgeglichener Pfad,
   c) investitionsstarker Pfad.
4. Simuliere jede Variante bis Reset oder Milestone.
5. Schätze Terminalwert und Restzeit bis F.
6. Verwirf Pläne mit verletzten Invarianten.
7. Wähle den Plan mit maximalem Score.
8. Fixiere den Plan nur bis zum nächsten Replanning-Trigger.
```

### 8.4 Optionswert

Ein Unlock erhält keinen pauschalen Bonus. Sein Optionswert ist die durch ihn verursachte Verringerung der erwarteten Restzeit bis F. Damit werden neue Mechaniken nur dann priorisiert, wenn sie den tatsächlichen Gesamtpfad beschleunigen.

```
OptionValue(m) = E[T_F | without m] − E[T_F | with m]
```

## 9. Progressionsfront und Makrophasen

Die folgenden Phasen bilden keine starre Build-Order. Sie definieren den zulässigen und bevorzugten Suchraum. Der Meta-Controller darf Meilensteine innerhalb einer Phase umordnen, sobald die Simulation eine geringere Restzeit nachweist. Er darf keine spätere Phase als operational markieren, solange deren Eintrittskriterien nicht erfüllt sind.

| Phase | Bezeichnung | Operationales Austrittskriterium |
|---|---|---|
| P0 | Erstwirtschaft | Stabile Food-/Wood-/Mineral-/Science-Kette; Workshops; Concrete Huts; Apocrypha; erster Reset wirtschaftlich. |
| P1 | Price-Ratio | Diplomacy, Enlightenment, Golden Ratio, Divine Proportion, Vitruvian Feline, Renaissance. |
| P2 | Core Meta & Space | Metaphysics-Pfad, stabile Space-/UO-Produktion, Anachronomancy vor TC-Reset. |
| P3 | Religion & Unicorn | Solar Revolution, TAP-Kreislauf, Unicorn-/Alicorn-/Black-Pyramid-Basis. |
| P4 | Leviathan TC | Leviathan-Kontakt, Elder Energy, positive TC-Erwartung aus UO-Trades. |
| P5 | Relic & Shatter | 5.000 AM-Cap für Relic Stations; RR-/Furnace-Aufbau; positive TC/Shatter-Bilanz. |
| P6 | Challenge & Paragon Scale | Erstabschlüsse und Paragonbasis für Storage-/Endgame-Pfade. |
| P7 | Seed & Positive CS | AM/Void/Cryptotheology-Seed; positive Chronosphere-Rekonstruktion. |
| P8 | Mature Endgame | Endliche Front vollständig; maximierte nachhaltige persistente Wachstumsrate. |

### 9.1 Festgelegte frühe Metaphysics-Reihenfolge

```
Diplomacy
→ Enlightenment
→ Golden Ratio
→ Divine Proportion
→ Vitruvian Feline
→ Renaissance
```

Chronomancy und Astromancy werden vor dem jeweils nächsten Price-Ratio-Ziel eingeschoben, sobald ihre simulierte Zeitersparnis durch Starcharts und Events größer ist als der Produktionsverlust des ausgegebenen Paragons. Anachronomancy wird zwingend vor jedem Reset mit relevantem Time-Crystal-Bestand erworben.

### 9.2 Festgelegte Engine-Reihenfolge

```
Alicorn-/Leviathan-Time-Crystal-Quelle
→ Relic Stations mit vollständiger Antimatter-Wirkung
→ Resource-Retrieval-Shatter-Engine
→ Paragon-/Storage-Skalierung
→ Antimatter-/Void-Seed
→ positive Chronosphere-Schleife
→ Mature Endgame
```

## 10. Taktischer Optimierer

### 10.1 Engpassanalyse

```
ETA(goal) = max_i ETA_i(goal)
```

ETA_i wird rekursiv über Ressourcen-, Craft-, Unlock- und Storage-Abhängigkeiten berechnet. Der primäre Engpass ist die Ressource oder Bedingung mit dem größten kritischen Pfadanteil. Sekundäre Engpässe werden mitgeführt, um Verschiebungen nach einem Kauf vorherzusehen.

### 10.2 Schattenpreise

```
λ_i = −∂ ETA(goal) / ∂ R_i
```

Der Schattenpreis λ_i gibt an, wie viele Sekunden Zielzeit eine zusätzliche Einheit der Ressource spart. Kosten und Produktionsgewinne werden in Zielzeitäquivalente umgerechnet.

```
Cost_time(a) = Σ_i λ_i · Cost_i(a)
Benefit_time(a,H) = Σ_i λ_i · ΔRate_i(a) · H + UnlockTimeSaving(a)
```

### 10.3 Kaufregel

```
NetValue(a) = Benefit_time(a,H) − Cost_time(a) − RiskPenalty(a) − DelayPenalty(a)
```

Der Agent kauft die zulässige Aktion mit dem höchsten positiven NetValue. Ist kein NetValue positiv, führt er WAIT bis zum frühesten Ereignis aus, das die Rangfolge verändern kann.

### 10.4 Payback

```
Payback(a) = Cost_time(a) / max(ε, MarginalTimeSavingRate(a))
```

Produktionsinvestitionen sind nur zulässig, wenn ihr Payback vor dem geplanten Reset oder Milestone liegt. Unlocks, Safety-Aktionen und zwingende Dependencies werden nicht durch die Payback-Regel gesperrt.

### 10.5 Aktionscharge

Gleichartige reversible Aktionen dürfen als Charge ausgeführt werden, wenn zwischen den Einzelschritten kein Replanning-Trigger liegt. Housing, exponentiell verteuerte Gebäude, Policies, Religion, Time und Reset werden einzeln ausgeführt und nach jedem Schritt neu bewertet.

## 11. Ressourcen-, Craft- und Storage-Logik

### 11.1 Ressourcenpriorität

Ressourcen werden niemals anhand einer statischen Liste priorisiert. Die Priorität entspricht dem Schattenpreis im aktuellen Critical Path. Ressourcen mit λ = 0 dürfen am Cap stehen. Ressourcen mit hohem λ dürfen nicht ungenutzt cappen.

### 11.2 Craft-Graph

Alle Craft-Rezepte bilden einen gerichteten Hypergraphen. Die effektiven Kosten eines Craftprodukts umfassen rekursiv seine Inputs, Craft Ratio, verfügbare Nebenprodukte und die alternative Verwendung der Inputs.

```
EffectiveCost(craft) = Σ_j Input_j / CraftYield + OpportunityCost(inputs)
```

Crafts werden in der kleinsten Charge ausgeführt, die das nächste Gate erreicht oder einen kritischen Cap-Verlust verhindert. Überproduktion ist nur zulässig, wenn das Craftprodukt besseren Carryover, höheren Storage-Wert oder einen niedrigeren zukünftigen Schattenpreis besitzt.

### 11.3 Storage

```
Storage wird gebaut, wenn mindestens eine Bedingung erfüllt ist:
  A. Die Kosten eines Critical-Path-Objekts überschreiten das aktuelle Cap.
  B. Der zusätzliche Carryover-Wert übersteigt die Baukosten.
  C. Der zusätzliche Offline-/Batch-Puffer verhindert bewerteten Cap-Verlust.
  D. Eine Challenge- oder Cryo-Bedingung verlangt das Cap.
Andernfalls ist Storage unzulässig.
```

### 11.4 Cap-Management

Für jede Ressource wird der nächste Cap-Zeitpunkt prognostiziert. Vor dem Cap wählt der Agent in dieser Reihenfolge: Critical-Path-Ausgabe, werterhaltender Craft, profitabler Trade, notwendiger Storage, akzeptierter Verlust. Die Reihenfolge wird durch NetValue bestätigt; sie ist keine blinde Prioritätsliste.

## 12. Bevölkerung, Jobs und Leader

### 12.1 Housing

```
KittenValue = ProductionValue_until_reset + ParagonMarginalValue + MilestoneValue
HousingValue = ExpectedKittenArrivals · KittenValue − Cost_time(housing)
```

Housing wird nur gebaut, wenn Food-Invariant erfüllt ist, mindestens ein zusätzliches Kitten vor Reset beziehungsweise Milestone eintrifft und HousingValue positiv ist. Unbenutzte Housing-Kapazität ohne rechtzeitige Kitten-Ankunft besitzt keinen Produktionswert.

### 12.2 Jobzuweisung

```
1. Berechne Mindestfarmer für Food-Invariant.
2. Reserviere zwingende Jobs für aktive Dependencies.
3. Berechne für jeden Job den marginalen Zielzeitgewinn pro Kitten.
4. Weise das nächste freie Kitten dem höchsten positiven Grenzwert zu.
5. Aktualisiere Produktionsraten und Schattenpreise.
6. Wiederhole bis alle Kitten zugewiesen sind.
7. Bei nicht-konvexen Schwellen teste zusätzlich lokale Tauschoperationen.
```

```
JobScore(j) = Σ_i λ_i · MarginalRate_i(j)
```

### 12.3 Leader

Der Leader wird dem Job/Trait-Paar mit der größten prognostizierten Zielzeitverkürzung zugeordnet. Ein Wechsel wird nur ausgeführt, wenn der Vorteil die Wechsel- und Interaktionskosten bis zum nächsten Replanning übersteigt.

### 12.4 Frühspiel-Ressourcenrotation

In P0 und P1 setzt der Optimierer eine fokussierte Jobrotation als Suchraumprior ein: Food stabilisieren, Wood-Infrastruktur, Mineral-/Metall-Infrastruktur, Science-/Culture-Gate. Die Rotation wird sofort verlassen, sobald die exakte Engpassanalyse eine andere Zuweisung besser bewertet.

## 13. Gebäude, Upgrades, Forschung und Policies

### 13.1 Gebäude

Für jedes Gebäude werden der nächste exponentielle Preis, alle direkten und indirekten Modifier, Energie- und Pollution-Folgen, Storage-Effekte, Unlocks und die verbleibende Aktivzeit im Run berechnet. Das System bewertet einzelne nächste Exemplare, nicht pauschal Gebäudeklassen.

### 13.2 Workshops und Factories

Workshops erhalten in P0/P1 einen Suchprioritätsbonus, weil Craft Ratio viele Critical Paths gleichzeitig verkürzt. Dieser Bonus ist ausschließlich eine Branch-and-Bound-Heuristik; die endgültige Entscheidung erfolgt über NetValue. Factories werden anhand Craft-, Engineer-, Production- und Pollution-Wirkung bewertet.

### 13.3 Forschung und Upgrades

```
Priorisierung:
  1. Zwingende Dependency des aktuellen Makroplans.
  2. Freischaltung einer neuen Progressionsschicht.
  3. Globaler Multiplikator mit positivem Horizon-Nutzen.
  4. Konkretes Storage-/Energy-/Craft-Gate.
  5. Automatisierung mit positiver Laufzeitwirkung.
  6. Sonstiger Inhalt.
```

Ein Objekt der Stufe 6 wird nur erworben, wenn kein höherwertiges Sparziel verzögert wird.

### 13.4 Policies

Policies werden als exklusive, teilweise irreversible Modifierpakete simuliert. Der Agent bewertet jede zulässige Policy-Kombination über den vollständigen Restplan. Statische Defaults werden nur zur Suchraumreduktion verwendet.

| Kontext | Bevorzugter Startkandidat für die Simulation |
|---|---|
| Früher Reset | Tradition, Monarchy, Diplomacy, Epicureanism, Zebra Appeasement. |
| Housing-/Paragon-Run | Fascism/Carnivale/Arrival- und Housing-orientierte Kombination. |
| Handels-/Titanium-Run | Diplomacy, Liberalism, Zebra Appeasement, Outer Space Treaty. |
| Industrie | Communism und Full Industrialization bei beherrschter Pollution. |
| Unobtainium | Cosmological Libertarianism. |
| Faith | Order-of-the-Stars-orientierter Pfad. |
| Pacts | Necrocracy/Radical Xenophobia entsprechend simuliertem Pact-Wert. |

## 14. Handel, Jagd und Zufallsereignisse

### 14.1 Handel

```
TradeValue(race) = Σ_o P(o|race,state) · Value(o) − Value(costs)
```

Value(o) wird über Schattenpreise und Milestone-Wirkung berechnet. Saison-, Standing-, Ship-, Policy-, Festival- und Leader-Effekte sind Teil der Ergebnisverteilung. Der Agent tradet nur, wenn TradeValue positiv und kein höherwertiger Catpower-/Gold-Verwendungszweck verdrängt wird.

### 14.2 Jagd

Jagd wird wie ein Trade mit bekannter Ergebnisverteilung behandelt. Catpower wird bis zum profitablen Batch gesammelt, sofern kein Cap-Verlust entsteht. Der Agent jagt sofort, wenn der erwartete Wert der Jagd größer als der Wert des Wartens bis zum nächsten Batch ist.

### 14.3 Astronomical Events und seltene Ereignisse

Ereignisse werden über Hazard Rates modelliert. Der Agent plant nicht mit dem sicheren Eintreten eines zufälligen Ereignisses vor einer Deadline. Er verwendet Quantilprognosen, wenn das Ereignis einen Critical Path blockiert, und Erwartungswerte für wiederholbare Produktion.

### 14.4 Leviathans

Leviathan-Verfügbarkeit ist ein stochastischer Zustandsfaktor. Der Makroplan enthält sowohl den Pfad bei Erscheinen als auch den Fallback-Pfad ohne Erscheinen. Unobtainium wird nur in dem Umfang vorgehalten, dessen erwarteter Leviathan-Trade-Wert den alternativen Bau- und Storage-Wert übersteigt.

## 15. Religion, Unicorns, Pacts und Transcendence

### 15.1 Faith und Solar Revolution

Nach Freischaltung von Solar Revolution wird Faith als globaler Produktionsmultiplikator in alle Schattenpreise eingerechnet. Praise wird ausgeführt, wenn dadurch der integrierte Produktionsgewinn bis zum nächsten Adore/Reset größer ist als der Wert des Haltens der Faith.

### 15.2 TAP-Transaktion

```
TAP = Transcend → Adore → Praise
Zulässig, wenn:
  - das neue Transcendence Tier erreichbar ist,
  - die nach TAP verbleibende Epiphany-/Worship-Struktur den Restplan verbessert,
  - die prognostizierte Wiederanlaufzeit die Milestone-Zeit nicht verschlechtert.
```

Vor einem langen oder strategischen Reset wird TAP vollständig simuliert und bei positivem Reset-Wert ausgeführt.

### 15.3 Unicorn-/Alicorn-Kette

Unicorn-Gebäude werden über den marginalen erwarteten Unicorn-, Tear-, Alicorn-, Time-Crystal- und Black-Pyramid-Wert bewertet. Die Kette wird erst als Makroplan zugelassen, wenn Price-Ratio-Metas, Anachronomancy-Schutz und die notwendigen Religion-Dependencies vorhanden oder im selben Plan erreichbar sind.

```
UnicornActionValue = ΔE[TC + Relic + BLS + ChallengeValue] − Cost_time
```

### 15.4 Alicorn-Konvertierung

Alicorns werden genau dann in Time Crystals konvertiert, wenn der erwartete Grenzwert der Time Crystals größer ist als der erwartete Grenzwert der verbleibenden Alicorn-/Corruption-Produktion und der TC-Bestand den nächsten Reset überlebt.

### 15.5 Pacts und Necrocorn Debt

```
PactValue = ΔBlackPyramidUtility − DebtCost − UpkeepCost − AlternativeNecrocornValue
```

Ein Pact wird ausschließlich bei positivem PactValue erworben. Siphoning wird aktiviert, wenn die Verringerung der diskontierten Schuldkosten größer ist als der unmittelbare Nutzen freier Necrocorns. Pact of Arcane und Pact of Chronicler werden nach derselben Regel behandelt; es existiert kein automatischer Kauf.

## 16. Space, Antimatter und Energie

### 16.1 Space-Abhängigkeitskette

```
Rocketry
→ Moon / Lunar Outposts / Moon Bases
→ Dune / Piscine
→ Helios / Sunlifters / Antimatter
→ T-Minus / Cryostations
→ Kairo / Space Beacons / Relic-Infrastruktur
```

### 16.2 Space-Gebäude

Space-Gebäude werden über Öl-, Titanium-, Uranium-, Energie- und Storage-Schattenpreise bewertet. Ein Building mit positiver Rohproduktion kann negativen Gesamtwert besitzen, wenn sein Energieverbrauch die effektive Produktion anderer Critical-Path-Gebäude reduziert.

### 16.3 Antimatter

Antimatter-Produktion wird nur unter dem tatsächlich prognostizierten Energiezustand bewertet. Für Relic Stations gilt die vollständige Wirksamkeit erst ab dem erforderlichen Antimatter-Cap. Der Agent baut den Cap als zusammenhängenden Makroplan; halbfertige Cap-Investitionen ohne zeitnahen Unlockwert werden vermieden.

### 16.4 Energieoptimierung

```
1. Berechne Energie in jedem relevanten Saison-/Cycle-Zustand.
2. Bestimme die marginale Output-Einbuße aller Verbraucher bei Defizit.
3. Deaktiviere Verbraucher mit dem kleinsten Zielbeitrag, bis harte Anforderungen erfüllt sind.
4. Bewerte zusätzliche Energieerzeuger gegen alternative Investments.
5. Aktiviere Verbraucher in absteigender Grenznutzenreihenfolge.
```

## 17. Time Crystals, Relics, Shattering und Heat

### 17.1 Time-Crystal-Bilanz

```
TC_net = TC_from_Alicorns + TC_from_Trades + TC_other − TC_shattered − TC_invested
```

Eine Shatter-Engine ist profitabel, wenn der durch Resource Retrieval, Cycle-Positionierung und Folge-Trades erzeugte erwartete TC-Rückfluss größer als der eingesetzte TC ist und alle Heat- sowie Carryover-Kosten berücksichtigt sind.

### 17.2 Resource Retrieval

```
RRValue(k+1) = E[MarginalResourcesPerShatter] · ExpectedFutureShatters − TCPrice(k+1)·λ_TC
```

Das nächste RR wird erworben, wenn RRValue positiv und größer als der Wert eines zusätzlichen Chrono Furnace, Relic-Multiplikators oder UO-Investments ist.

### 17.3 Chrono Furnaces und Heat

```
FurnaceValue = AvoidedIdleTime_due_to_heat + AdditionalBatchValue − Cost_time
```

Furnaces werden gebaut, wenn Heat die optimale Shatter-Batchgröße oder die Cycle-Navigation begrenzt. Heat wird als dynamischer Constraint im Event-Simulator geführt.

### 17.4 Relic Stations

Relic Stations werden operational eingesetzt, sobald ihre AM- und Energiebedingungen erfüllt sind und ihre nachhaltige Relic-Rate den opportunitätsbereinigten Leviathan-Relic-Ertrag übersteigt. Black Nexus, Black Core, Black Pyramid, Entanglement Stations und Hashrate werden als Multiplikatorgraph modelliert.

### 17.5 Shatter-Aktionsregel

```
Shatter ist zulässig, wenn mindestens eine Bedingung gilt:
  A. Erwarteter gesamter Rückfluss > 1 TC-Äquivalent.
  B. Der Shatter positioniert einen Cycle/Festival-Zustand mit höherem Gesamtplanwert.
  C. Eine Challenge verlangt den Zeitsprung.
  D. Paragon aus Jahren besitzt höheren Wert als der TC-Verbrauch.
```

Die Batchgröße maximiert den Planwert unter Heat-, Cycle- und Cap-Constraints.

## 18. Challenges

### 18.1 Challenge-Katalog

Jede Challenge besitzt ein formales Profil aus Einschränkungen, Zielbedingung, Erstbelohnung, Wiederholungsbelohnung, geschätzter Completion-Time-Verteilung und Synergien/Antisynergien mit anderen Challenges.

### 18.2 Auswahlregel

```
ChallengeValue(c) = ReductionInExpectedT_F(c) / ExpectedCompletionTime(c)
```

Vor der endlichen Front wird die Challenge mit der größten Reduktion der erwarteten Restzeit gewählt, sofern ihre Zielbedingung mit vorgegebener Erfolgswahrscheinlichkeit erreichbar ist. Nach der endlichen Front wird eine Wiederholung nur gewählt, wenn ihr marginaler Reward die Endgame-Wachstumsrate stärker erhöht als der beste Nicht-Challenge-Plan.

### 18.3 Kombinationen

Challenge-Kombinationen werden nicht über statische Verbotslisten entschieden. Der Planner simuliert kombinierte Einschränkungen. Eine Kombination ist unzulässig, wenn ihre erwartete Restzeit größer als die Summe separater Abschlüsse ist oder wenn die Erfolgswahrscheinlichkeit unter die festgelegte Grenze fällt.

```
P(success before abort horizon) ≥ 0.99
```

### 18.4 Challenge-Reset

Der Reset-Executor prüft unmittelbar vor Reset, dass die Challenge-Zielbedingung im tatsächlichen Zustand erfüllt und vom Spiel als erfüllbar markiert ist. Eine nur prognostizierte Erfüllung reicht nicht aus.

## 19. Chronospheres, Void und Reset-Loops

### 19.1 Chronosphere-Wert

```
CSValue(n+1) = CarryoverGain + VoidGain + ResetTimeSaving − UOCost − RebuildDelay
```

Die optimale Chronosphere-Zahl ist zustandsabhängig und wird für jeden Run explizit gesucht. Der Planner prüft mindestens die lokal benachbarten Zahlen n−2 bis n+3 sowie strukturelle Kandidaten für Speedrun, Void-Run und positive Reset-Schleife.

### 19.2 Positive Reset-Bedingung

Eine positive Chronosphere-Schleife liegt vor, wenn der nach Reset übertragene kritische Ressourcenvektor nach Abzug aller Wiederaufbaukosten den Ausgangsvektor strikt dominiert oder den Endgame-Fähigkeitsindex pro Realzeit erhöht.

```
R_after_reset − R_rebuild  ≻  R_before_reset
```

Das Symbol ≻ bezeichnet Dominanz in allen für den aktiven Loop kritischen Ressourcen und strikte Verbesserung in mindestens einer Dimension. Wenn keine Vektordominanz besteht, entscheidet der simulierte Endgame-Score.

### 19.3 Void

Void-Gewinn und Void-Strukturen werden anhand ihres Beitrags zu Storage, Chronosphere-Skalierung, Cryo-Mechanik und Restzeit bis F bewertet. Void-Farming ist ein eigener MacroPlan und wird nicht beiläufig in einen Paragon-Speedrun eingebaut, sofern die Gesamtsimulation keine Dominanz nachweist.

### 19.4 Positive-Reset-Ablauf

```
Reset
→ minimale Produktionsbasis
→ Science-/Workshop-Critical-Path
→ Space und UO
→ Zielzahl Chronospheres wiederherstellen
→ Carryover-Überschuss realisieren
→ permanente Aktionen / TAP
→ erneuter Reset, sobald marginales Weiterlaufen schlechter wird
```

## 20. Reset-Entscheidung und Reset-Transaktion

### 20.1 Reset-Wert

```
ResetValue = V(ExpectedPostResetState) − V(ContinueState at equal wall time)
```

Reset wird ausgeführt, wenn ResetValue positiv, alle Invarianten erfüllt und kein in kürzerer Zeit erreichbarer permanenter Milestone einen höheren Wert besitzt.

### 20.2 Reset-Kandidaten

- Erster sinnvoller Paragon-Reset.
- Finanzierung des nächsten Metaphysics-Ziels.
- Abschluss einer Challenge.
- Paragon-Run mit fallender marginaler Paragonrate.
- Religion-Run nach optimalem TAP-Punkt.
- Seed-Run nach Erreichen der Zielbasis.
- Positive Chronosphere-Schleife.
- Mature-Endgame-Loop mit maximalem ΔlnC/Δt.

### 20.3 Pre-Reset-Transaktion

```
PRE_RESET_TRANSACTION:
  1. Atomaren Zustand und Save-Export erzeugen.
  2. Challenge-Erfüllung verifizieren.
  3. Geplante permanente Käufe durchführen.
  4. Paragon-/Burnt-Paragon-Plan verifizieren.
  5. TAP vollständig simulieren und bei positivem Wert ausführen.
  6. Unicorns, Tears und Alicorns nach Grenzwertregel konvertieren.
  7. Chronospheres, Cryochambers und Stasis Pods auf Zielstand bringen.
  8. Nicht übertragbare Ressourcen mit positivem Restwert ausgeben.
  9. Post-Reset-Projektion erneut berechnen.
 10. Alle Assertions prüfen.
 11. Reset atomar ausführen.
 12. Post-Reset-Zustand validieren und Rekonstruktionsplan starten.
```

### 20.4 Paragon-Speedrun-Reset

```
MarginalParagonRate = ExpectedAdditionalParagon / ExpectedAdditionalTime
```

Der Run endet, sobald die marginale Paragonrate unter die prognostizierte Durchschnittsrate eines neuen Runs fällt. Die optimale Chronosphere-Zahl, Faith-Transaktion und Ausbauintensität werden pro Savezustand simuliert; historische Communitywerte sind keine festen Schwellen.

## 21. Ereignisscheduler und Replanning

### 21.1 Harte Replanning-Trigger

- Versions- oder Modellabweichung.
- Verletzung oder drohende Verletzung einer Sicherheitsinvariante.
- Neues Research, Upgrade, Policy, Gebäude, Mission oder Challenge-Ziel verfügbar.
- Ressource erreicht Cap oder Depletion-Schwelle.
- Saison-, Cycle-, Festival-, Heat- oder Temporal-Flux-Änderung.
- Kitten-Ankunft oder Housing-Änderung.
- Leviathan- oder anderes seltenes Ereignis.
- Metaphysics-, Transcendence-, RR-, Relic- oder Reset-Schwelle erreicht.
- Aktionsfehler oder abweichende Postcondition.

### 21.2 Weiche Replanning-Trigger

Zusätzlich läuft ein periodischer Kontrollpunkt. Sein Abstand ist das Minimum aus 30 Sekunden, 10 Prozent der ETA zum nächsten Milestone und der halben Zeit bis zum nächsten prognostizierten Cap. Dadurch reagiert der Agent rechtzeitig, ohne jeden Tick global neu zu planen.

### 21.3 Planbindung

Ein MacroPlan ist keine unveränderliche Verpflichtung. Nur irreversible Aktionen werden über eine Commit-Grenze fixiert. Alle übrigen Aktionen dürfen beim nächsten Replanning ersetzt werden, wenn ein höherer Planwert entsteht.

## 22. Aktionsausführung, Transaktionen und Fehlerbehandlung

### 22.1 Executor-Regeln

- Jede Aktion besitzt Precondition-, Cost- und Postcondition-Assertions.
- Der Executor liest vor irreversiblen Aktionen den Zustand erneut.
- Aktionswiederholungen sind idempotent oder durch eindeutige Action-IDs geschützt.
- Nach Ausführung werden beobachtete Ressourcenänderungen gegen die Modellprojektion geprüft.
- Bei Fehler wird keine Folgeaktion ausgeführt, bevor der Zustand erneut normalisiert wurde.

### 22.2 Model Mismatch

```
Mismatch = distance(ObservedState, PredictedState) > tolerance(action,type)
```

Bei Mismatch stoppt der autonome Fortschritt. Zulässig bleiben Save-Export, Abschalten riskanter Verbraucher und reine Beobachtung. Das Modell wird erst nach einer versionierten Aktualisierung wieder freigegeben. Automatische freie Neuinterpretation unbekannter Mechaniken findet nicht statt.

### 22.3 Deadlock-Auflösung

Ein Deadlock liegt vor, wenn kein zulässiger positiver Kandidat existiert und WAIT kein zukünftiges Ereignis erzeugt, das den Zustand verbessert. Der Agent erweitert dann den Makrohorizont, lockert ausschließlich Suchraum-Heuristiken und erzeugt neue Pläne. Sicherheitsinvarianten und Versionsbindung werden niemals gelockert.

## 23. Protokollierung, Erklärbarkeit und Reproduzierbarkeit

Jede Entscheidung wird als maschinenlesbarer DecisionTrace gespeichert. Die Erklärung ist numerisch und benötigt kein LLM.

```
DecisionTrace
├─ state_hash
├─ model_version
├─ active_macro_plan
├─ active_milestone
├─ bottleneck_report
├─ candidate_actions
├─ rejected_actions_with_constraints
├─ score_components
├─ selected_action
├─ predicted_post_state
├─ observed_post_state
├─ random_seed / sampled outcomes
└─ replan_reason
```

Für identische Eingaben und identischen Zufallsseed MUSS ein Replay dieselbe Aktionsfolge erzeugen. Bei echter Spiel-RNG wird der beobachtete Outcome protokolliert und ab diesem Zustand deterministisch weitergespielt.

## 24. Verifikation und Abnahmekriterien

### 24.1 Modelltests

- Produktions-, Kosten-, Cap-, Craft-, Trade-, Religion-, Space-, Time-, Challenge- und Reset-Formeln stimmen mit der Referenzimplementierung überein.
- Für jede Aktion existieren Golden-State-Tests vor und nach Ausführung.
- Zufallsverteilungen werden mit statistischen Tests gegen die Referenz validiert.
- Carryover und Reset werden mit vollständigen Save-Differenzen getestet.

### 24.2 Entscheidungs-Tests

| Testklasse | Abnahmekriterium |
|---|---|
| Safety | Kein Testlauf verletzt Food-, Reset-, Version-, Energy- oder Heat-Invarianten. |
| Local optimality | Keine einzelne alternative zulässige Aktion besitzt im gleichen Horizont höheren Score. |
| Macro benchmark | Der Agent erreicht definierte Milestones mindestens so schnell wie die beste hinterlegte Community-/Referenzstrategie. |
| Regression | Versionsgleiche Savegames erzeugen reproduzierbare Pläne und Aktionen. |
| Reset | Post-Reset-Zustand entspricht der Projektion innerhalb numerischer Toleranz. |
| Endgame | Der gemessene ΔlnC/Δt-Wert sinkt durch keine lokal getestete MacroPlan-Alternative. |

### 24.3 Benchmark-Suite

- Neues Savegame bis erster sinnvoller Reset.
- Price-Ratio-Fortschritt bis Renaissance.
- Erster geschützter Time-Crystal-Reset.
- Leviathan-Engine bis positiver TC-Fluss.
- Relic-Station-Aufbau mit vollständiger AM-Wirkung.
- Übergang zu profitabler Shatter-Engine.
- Einzelne Challenge-Erstabschlüsse und ausgewählte Kombinationen.
- Paragon-Speedrun-Optimierung über unterschiedliche Chronosphere-Zahlen.
- AM/Void-Seed und positive Chronosphere-Rekonstruktion.
- Mature-Endgame-Vergleich über längere Simulationszeiträume.

## Anhang A – Datenverträge

### A.1 Normalisierte Einheiten

| Größe | Einheit |
|---|---|
| Ressourcenmenge | Spielinterne Basiseinheit als double/decimal. |
| Produktionsrate | Einheiten pro realer Sekunde. |
| Spielzeit | Reale Sekunden; Kalenderzeit separat. |
| Zielzeitwert | Sekunden erwarteter Restzeit. |
| Wahrscheinlichkeit | 0 bis 1. |
| Energie | Spielinterne Energieeinheiten. |
| Heat | Spielinterne Heat-Einheiten. |
| Nutzen vor F | Negative erwartete Sekunden bis F. |
| Nutzen nach F | Δln(C) pro reale Sekunde. |

### A.2 Enumerationen

```
CarryoverClass = {LOST, FIXED_PROTECTED, PROPORTIONAL, FULL}
ActionAtomicity = {READ_ONLY, REVERSIBLE, BATCH_REVERSIBLE, IRREVERSIBLE}
RunType = {FIRST_RUN, PRICE_RATIO_RUN, CORE_META_RUN, RELIGION_RUN,
           UNICORN_RUN, CHALLENGE_RUN, LEVIATHAN_RUN, RELIC_STATION_RUN,
           SHATTER_RUN, PARAGON_RUN, SEED_RUN, POSITIVE_CS_RUN,
           MATURE_ENDGAME_RUN}
AgentMode = {ACTIVE, MODEL_MISMATCH, SAFE_STOP, POST_RESET_RECOVERY}
```

## Anhang B – Vollständige Aktionsklassen

| ActionType | Semantik |
|---|---|
| WAIT | Bis zu einem berechneten Ereignis warten. |
| ASSIGN_JOB | Kitten einem Job zuweisen oder entfernen. |
| SET_LEADER | Leader und Leader-Job setzen. |
| BUY_BUILDING | Ein einzelnes oder sichere Charge eines Gebäudes kaufen. |
| TOGGLE_BUILDING | Verbraucher/Produzent aktivieren oder deaktivieren. |
| BUY_UPGRADE | Workshop-/Science-/Space-/Time-/Religion-Upgrade kaufen. |
| RESEARCH | Forschung abschließen. |
| SELECT_POLICY | Exklusive Policy wählen. |
| CRAFT | Craftprodukt in berechneter Charge herstellen. |
| HUNT | Hunter-Charge ausführen. |
| TRADE | Trade-Charge mit Race ausführen. |
| PRAISE | Faith preisen. |
| ADORE | Adore-Transaktion. |
| TRANSCEND | Transcendence-Tier erhöhen. |
| SACRIFICE_UNICORNS | Unicorns in Tears umwandeln. |
| REFINE_TEARS | Tears in BLS umwandeln. |
| CONVERT_ALICORNS | Alicorns in TC umwandeln. |
| BUY_PACT | Pact erwerben. |
| SET_SIPHONING | Siphoning-Zustand setzen. |
| START_FESTIVAL | Festival starten. |
| SET_TEMPUS_FUGIT | Tempus Fugit aktivieren/deaktivieren. |
| SHATTER | TC-Batch shattern. |
| ACTIVATE_CHALLENGE | Challenge-Set für nächsten Run setzen. |
| RESET | Pre-Reset-Transaktion abschließen und resetten. |
| EXPORT_SAVE | Save exportieren und hashbasiert sichern. |

## Anhang C – Entscheidungsreferenz

### C.1 Universeller Entscheidungsablauf

```
STATE READ
  ↓
VERSION OK? ── nein → MODEL_MISMATCH / SAFE_STOP
  ↓ ja
SAFETY VIOLATION? ── ja → Safety Action
  ↓ nein
FINITE FRONT COMPLETE?
  ├─ nein → minimiere erwartete Restzeit bis F
  └─ ja   → maximiere ΔlnC/Δt
  ↓
GENERATE MACRO PLANS
  ↓
SIMULATE / SCORE / PRUNE
  ↓
SELECT MACRO PLAN
  ↓
COMPUTE BOTTLENECKS + SHADOW PRICES
  ↓
GENERATE TACTICAL ACTIONS
  ↓
RESET DOMINATES? ── ja → Pre-Reset Transaction
  ↓ nein
BEST POSITIVE ACTION? ── nein → WAIT
  ↓ ja
EXECUTE ONE COMMIT UNIT
  ↓
VALIDATE / REPLAN
```

### C.2 Tie-Breaking

Bei identischem Score gilt strikt: geringere Wahrscheinlichkeit irreversibler Verluste, geringere erwartete Zeitvarianz, weniger irreversible Aktionen, weniger Gesamtaktionen, niedrigere ActionType-Ordinalzahl, lexikografisch kleinere Ziel-ID. Diese Reihenfolge garantiert deterministische Entscheidungen.

## Anhang D – Formelreferenz

| Formel | Definition |
|---|---|
| Cap-Zeit | `(capacity − amount) / max(ε, net_rate)` |
| Depletion-Zeit | `amount / max(ε, −net_rate)` |
| Reset-Paragon | `max(0, kittens − 70) + floor(year / 1000)` |
| Ziel-ETA | Maximum der rekursiven Dependency-ETAs |
| Schattenpreis | `−∂ETA/∂R_i` |
| Zeitkosten | `Σ λ_i · Cost_i` |
| Payback | `Cost_time / MarginalTimeSavingRate` |
| Trade-Wert | `Σ P(outcome)·Value(outcome) − Value(cost)` |
| Reset-Wert | `V(post-reset) − V(continue at same time)` |
| RR-Wert | `Marginal retrieval yield × future shatters − TC cost` |
| CS-Wert | `Carryover + Void + reset speed − UO cost − delay` |
| Endgame-Score | `E[ΔlnC/Δt] − risk penalty` |

## Anhang E – Quellenbasis und Versionsnachweis

Die Systemspezifikation basiert auf der Referenzimplementierung und der aktuellen Community-/Wiki-Progressionsanalyse. Communitywerte werden nicht als unveränderliche Spielregeln verwendet; sie dienen als Benchmarks und Suchraum-Heuristiken.

| Ref. | Quelle | Verwendung |
|---|---|---|
| Q1 | nuclear-unicorn/kittensgame, changelog.txt, v1.5.0.2 vom 24.04.2026 | Versionsumfang und neue Mechaniken. |
| Q2 | nuclear-unicorn/kittensgame, build.version.json, Build Revision 3 | Versionsbindung. |
| Q3 | Kittens Game Wiki: Monstrous Advice | Frühspiel, erste Resets, Price-Ratio-Metas, TAP und Ressourcenrotation. |
| Q4 | Kittens Game Wiki: Sagefault's Endgame Guide | Leviathan-, Relic-, Shatter-, Paragon-, Seed- und Chronosphere-Progression. |
| Q5 | Kittens Game Wiki: Metaphysics, Challenges, Energy, Space, Time, Trade | Mechanik- und Constraintmodell. |
| Q6 | Kittens Game Community/Reddit: Paragon-Speedrun- und Endgame-Diskussionen | Benchmarkvarianten; keine normative Regelquelle. |

## Anhang F – Finale Systemdefinition

> **Abschließende Festlegung:** Die Autonome Optimimale Spiel-Mechanik ist ein version-gebundener, vollständig autonomer, hierarchischer und modellbasierter Optimierungsagent. Er verwendet ein exaktes Spielmodell, harte Invarianten, einen strategischen Meta-Controller, stochastische Vorwärtssimulation, Model Predictive Control, Schattenpreis- und Payback-Optimierung sowie transaktionale Aktionsausführung. Er enthält kein LLM, keine menschliche Zielvorgabe und keine freie Heuristik außerhalb der in diesem Dokument festgelegten Suchraum- und Tie-Break-Regeln.

Mit dieser Spezifikation sind Zweck, Zielfunktion, Systemgrenzen, Komponenten, Datenverträge, Abläufe, Abhängigkeiten, Formeln, Sicherheitsregeln, strategische Phasen, operative Entscheidungen, Reset-Mechanik, Zufallsbehandlung, Ausführung und Verifikation abschließend festgelegt. Die verbleibende Arbeit ist die programmgemäße Umsetzung gegen die Referenzversion.
