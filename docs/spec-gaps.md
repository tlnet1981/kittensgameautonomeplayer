# Spec-Dynamik-Audit: Wo die Umsetzung (noch) statischer ist als die Spec

Die [Spielmechanik-Spezifikation](spielmechanik-spec.md) fordert an vielen
Stellen **dynamische Bewertung** (Simulation, Schattenpreise, Grenzwerte).
Diese Tabelle ist der ehrliche Abgleich. Stand jetzt: **alle 33 Zeilen
umgesetzt** (✅); die verbleibenden dokumentierten Näherungen stehen am Ende.
Der Ausbaugrenzen-Wächter im Cockpit meldet nur noch dynamische Befunde
(z. B. Deadlocks).

Legende: ✅ umgesetzt/spec-nah (offene Lücken erschienen hier als 🟠/🟡 — aktuell keine)

## Bewertungs-Dynamik (Kern-Audit)

| # | Spec | Mechanik (dynamisch gefordert) | Ist-Zustand | Status |
|---|---|---|---|---|
| 1 | 7.2 | **Food-Sicherungshorizont** (saison-/zustandsabhängig) | Saisonprojektion bis Ende des nächsten Winters (`derived.project_catnip`), Schwellen skalieren mit Bedarf | ✅ |
| 2 | 12.1 | **HousingValue** (Ankünfte × Kitten-Wert − Zeitkosten) | Bedarfs-Gate (Kapazität voll) + Food-Projektion inkl. Mehrlast + Paragon-Grenzwert ab 68 Kitten (`tactics._housing_eval`) | ✅ |
| 3 | 20.4 | **Paragon-Speedrun-Abbruch** (marginale Rate) | Marginalraten-Fenster vs. Ø-Rate implementiert (`reset._paragon_speedrun_rule`) | ✅ |
| 4 | 10.2 | **Schattenpreise λᵢ für alle Ressourcen**; Kosten/Nutzen in Zielzeit-Äquivalenten | λᵢ numerisch über die Engpass-ETA inkl. Craft-Kaskade (`shadow.shadow_prices`); Cost_time/Benefit_time/NetValue als Sekundenwerte im Decision Inspector, NetValue fließt normiert in den Score | ✅ |
| 5 | 10.4 | **Payback-Regel** (Amortisation vor Reset/Milestone, sonst kein Produktionskauf) | Payback-Gate in `tactics._building_candidates` gegen `shadow.run_horizon`; Unlocks/Safety/Dependencies ausgenommen (Spec-konform) | ✅ |
| 6 | 12.2 | **Job-Zuweisung** über marginalen Zielzeitgewinn je Job, iterativ mit Tauschoperationen | `shadow.job_score` (Σ λᵢ·Marginalrate) wählt den Job; Tausch nur bei Gewinn > Schwelle (`tactics._job_candidates`/`_job_rebalance_candidate`); Basisraten-Näherung im Docstring dokumentiert | ✅ |
| 7 | 8.3 | **Run-Typ-Wahl** durch Simulation aller Makroplan-Kandidaten (×3 Varianten) | `meta.determine_run_plan`: zulässige Run-Typen × Varianten a/b/c per EV-Projektion, Score = −Restzeit, Tie-Break C.2 — für die 3 aktiven Run-Typen (alle 13 siehe #16) | ✅ |
| 8 | 14.1 | **TradeValue** als Erwartungswert über die Ergebnisverteilung (Saison, Standing, Ships) | `tactics._trade_value`: Σ P(o)·λ-Wert(o) − λ-Kosten aus Race-Daten im Snapshot (sells/Saison-Deltas/Standing/Ships); EV-Gate, Engpass-Regel als Fallback | ✅ |
| 9 | 20.1 | **Reset-Wert** V(post-reset) − V(continue) via Simulation | `reset._reset_value` über die EV-Projektion am gleichen Realzeithorizont (Neustart-Rampe als dokumentierte Näherung); Schwelle 35 bleibt notwendige Vorbedingung, Perk-Finanzierung harte Regel | ✅ |
| 10 | 11.3 | **Storage-Bedingungen B–D** (Carryover-Wert, Offline-Puffer, Challenge-Cap) | `tactics._storage_eval`: A (Cap blockiert Ziel), B (Carryover × 1,5 %/CS × λ vs. Baukosten), C (bewerteter Cap-Verlust im 60-s-Puffer), D (Challenge-Gate; ohne Challenge-Snapshot-Daten inaktiv) | ✅ |
| 11 | 16.4 | **Energie-Drosselung**: Verbraucher nach Grenznutzen deaktivieren | `tactics._energy_candidates` + Aktion `toggle_building`: kleinster λ-Zielbeitrag je Energieeinheit zuerst, lebenswichtige nie, Reaktivierung mit Hysterese | ✅ |
| 12 | 19.1 | **Chronosphere-Zahl**: Suche über n−2…n+3 je Run | `chrono.optimal_chronosphere_count` (CSValue-Fenster); Kauf nur bis Zielzahl, csValue transparent | ✅ |
| 13 | 12.3 | **Leader-Wahl** (Trait/Job-Paar mit größter Zielzeitverkürzung) | `tactics._leader_candidate` + Aktion `set_leader`: Trait-Boni λ-bewertet, Wechsel nur über 120-s-Gewinnschwelle; Census im Snapshot | ✅ |
| 14 | 14.2 / 15.1 | **Jagd-/Praise-Timing** per EV-Vergleich | Jagd als Trade mit Referenz-Beuteverteilung (sofort bei Cap-Druck oder λ-Sofortnutzen > Batch-Vorteil); Praise per Gain-vs-Hold inkl. intakter Sparregel; Cap-Schwellen als Fallback | ✅ |
| 15 | 5 / 6.2 | **Stochastische Vorwärtssimulation + Planbewertung** | Deterministische **EV-Projektion** `brain/simulate.py` (Saisonmodifikatoren, Cap-Klemmen, Kitten-Mehrlast) bewertet Makropläne; bewusst kein Monte-Carlo — Zufallsaktionen gehen als Erwartungswerte ein | ✅ |

## Abdeckung (Spielinhalte/Makro)

| # | Spec | Mechanik | Ist-Zustand | Status |
|---|---|---|---|---|
| 16 | 8.2 / 9 | **13 Run-Typen + Makrophasen P0–P8** | Alle 13 Run-Typen aktiv zulässig (`meta._admissible_run_types`/`_endgame_run_types`, Restzeit-Formeln in `_plan_restzeit`); Phasen P0–P8 aus operationalen Austrittskriterien (`meta.determine_phase`); 9.2-Kaskade als Zulässigkeits-Gates | ✅ |
| 17 | 13.4 | **Policy-Wahl**: exklusive Kombinationen über den Restplan simulieren | `brain/policy.py`: Effekt-Referenztabelle aus gamefiles/js/science.js, PolicyValue λ-bewertet über den Restplan-Horizont, I-07 gegen alle `blocks`-Alternativen (auch unsichtbare via Referenzpreise), 13.4-Prior je Run-Typ als Suchraumreduktion; Kandidat `tactics._policy_candidates` (IRREVERSIBLE → Commit-Grenze), Actor via PolicyBtnController-API | ✅ |
| 18 | 18.1–18.4 | **Challenges**: Katalog, ChallengeValue-Auswahl, Kombinationssimulation, Reset-Verifikation | `brain/challenge.py`: Katalog aus gamefiles/js/challenges.js, ChallengeValue = ΔE[T_F]-Proxy / E[Completion] (Referenzschätzungen gekennzeichnet), immer einzeln (18.3-Gate dokumentiert); CHALLENGE_RUN im Meta-Controller (konservative Restzeit-Konstante), 18.4-Gate `challenge.reset_gate` (nur das researched-Flag des Spiels öffnet), pending-Aktivierung in `reset.execute_reset` (applyPending-Kernschritte ohne UI-Confirm) | ✅ |
| 19 | 17.1–17.5 | **Shatter-Engine**: TC-Bilanz, RRValue, Chrono-Furnace/Heat-Steuerung, Relic Stations, Shatter-Regeln A–D | `brain/timecrystal.py`: tc_balance, rr_value, furnace_value, shatter_decision (Regeln A–D, Batch-Suche unter Heat-/Cap-Constraints, Cycle-Referenztabelle); `_time_candidates` nutzt sie, konservativer Fallback ohne λ-Daten | ✅ |
| 20 | 15.2 / 15.4 / 15.5 | **TAP-Transaktion, Alicorn-Konvertierung, Pacts** | `brain/religion.py`: transcend_value/tap_plan (Epiphany-Bilanz aus religion.js), Alicorn→TC- und Tears→BLS-Grenzwertregeln (nur mit Anachronomancy-Schutz), pact_value mit Upkeep/Debt/Fracture + Siphoning-Regel; irreversible Aktionen transcend/convert_alicorns/refine_tears/buy_pact | ✅ |
| 21 | 20.3 | **Pre-Reset-Transaktion** (12 Schritte) | `reset.execute_reset`: volle 12-Schritt-Sequenz mit reset.step-Events — Save-Export, Challenge-Verifikation, permanente Perk-Käufe, Paragon-Verifikation, TAP, Konvertierungen, CS-/Cryo-Zielstand, Restwert-Crafts, Post-Reset-Projektion, harte Assertions, applyPending+Reset, Validierung | ✅ |
| 22 | 16.1 / 16.3 | **AM-Cap als zusammenhängender Makroplan** | RELIC_STATION_RUN mit AM-Cap-5000-Meilensteinblock (`meta._am_cap_milestones`: containmentChamber/Beacons/relicStation aus space.js); 16.2-Energie-Malus für Space-Gebäude | ✅ |
| 23 | 1.3 / 6.3 | **Endgame-Index C(S)** und ΔlnC/Δt nach der Progressionsfront | `brain/endgame.py`: C(S) = geometrisches Mittel max(ε, rᵢ/bᵢ) über 7 persistente Dimensionen; frontier_complete-Proxy schaltet den Makro-Score von −Restzeit (6.2) auf E[ΔlnC/Δt] (6.3) um; MATURE_ENDGAME_RUN | ✅ |
| 24 | 19.2 / 19.3 | **Positive CS-Schleife** (Vektordominanz) und **Void-Makroplan** | `chrono.positive_cs_check` (Carryover- vs. Wiederaufbau-Vektor aus game._resetInternal, Dominanz + strikte Verbesserung); Void-Strukturen λ-bewertet nur im SEED_RUN (`chrono.seed_run_admissible`) | ✅ |
| 25 | Anhang B | **SET_TEMPUS_FUGIT** | Aktion `set_tempus_fugit` (idempotenter JS-Kern mit Flux-Prüfung); `_tempus_fugit_candidate` mit Nutzenregel + Hysterese (120 s an / 30 s aus) | ✅ |

## Governance/Infrastruktur

| # | Spec | Mechanik | Ist-Zustand | Status |
|---|---|---|---|---|
| 26 | G-02 / 22.2 | **Harter MODEL_MISMATCH-Stop** (nur lesende/sichernde Aktionen bei Versions-/Modellabweichung) | AgentMode ACTIVE/MODEL_MISMATCH/SAFE_STOP (`runtime.apply_version_guard`, periodisch im Telemetrie-Loop); Gate im Loop (`loop.apply_mode_gate`, nur READ_ONLY + Verbraucher-Abschalten), Reset gesperrt; manuelle Freigabe `acknowledge_mismatch` (Cockpit-Control, quittierte Version retriggert nicht) | ✅ |
| 27 | G-10 / 22.2 | **Prognose-vs-Beobachtung-Distanzprüfung** mit Toleranz und Stop | `predicted`-Dict an Aktionen (Käufe/Craft/Refine/Gather exakt, Trade/Jagd als EV); `loop.check_prediction` (15 % + Puffer + Produktionsdrift; stochastisch nur Vorzeichen/Größenordnung); erst 3 harte Abweichungen in Folge → MODEL_MISMATCH (`mismatch_streak`) | ✅ |
| 28 | 21.1–21.3 / 5.3 | **Ereignisgetriebenes Replanning** (harte/weiche Trigger, Ereigniswarteschlange, Commit-Grenze) | `brain/scheduler.py`: `next_wakeup` (Saison/½-Cap/10 %-ETA/30-s-Kontrollpunkt, Klemme [decision_interval, 30 s]) steuert den Loop-Schlaf; harte Trigger per Vorzyklus-Signatur (`classify_hard_trigger`); Commit-Grenze für IRREVERSIBLE (`loop.commit_guard`: Re-Read + Precondition, Abbruch ohne Retry) | ✅ |
| 29 | 5.4 / 6.2 | **Risikoterme** (CVaR, κ·P(fatal), μ·irreversible Verluste) | Makro-Score = −Restzeit − κ·P(fatal) − μ·E[Verlust] (`meta._score_plans`): P(fatal) über `Projection.food_fatal`, Verlustproxy über die Carryover-Fallliste — dokumentiert als deterministische Proxys, kein CVaR (bräuchte Verteilungen) | ✅ |
| 30 | 11.2 / 11.4 | **Effektive Craft-Kosten inkl. Opportunitätskosten; Cap-Ausgabe als NetValue-Reihenfolge** | `_craft_toward` scored über EffectiveCost 11.2 (λ-Opportunitätskosten der Ziel-Inputs, Fallback Tiefen-Score); Cap-Schutz 11.4 rankt Ausgabe-Optionen per NetValue (Schwellen nur noch Trigger-Vorfilter, akzeptierter Verlust explizit) | ✅ |
| 31 | 23 | **DecisionTrace-Vollständigkeit** (state_hash, predicted vs. observed, replan_reason) | `records.state_hash` (sha256-Kurzhash, Rundung 2/3 Nachkommastellen) + `replan_reason`/`predicted`/`observed_delta`/`prediction_ok` im DecisionRecord und `to_dict` (camelCase, Cockpit erbt ohne Whitelist) | ✅ |
| 32 | 24.1 | **Golden-State-Fixtures + Replay-Test** | `tests/fixtures/{early,mid,late}.json` (eingefroren, deterministisch, ohne Zeitstempel) + Loader `tests/helpers.load_fixture`; `tests/test_replay.py`: Determinismus, Golden-Gewinner je Fixture, state_hash-Stabilität | ✅ |
| 33 | 8.4 / 22.3 | **Optionswert von Unlocks; generische Deadlock-Auflösung** | OptionValue-Sekundenwert für Forschung/Upgrades aus Referenz-Ratentabellen (gamefiles); Deadlock 22.3: Horizont ×2 → Suchraum lockern → Frontier-Meldung (`tactics.is_deadlock`/`resolve_deadlock`, Safety nie gelockert) | ✅ |

## Stand: Spec vollständig umgesetzt — verbleibende ehrliche Grenzen

Alle 33 Audit-Zeilen sind ✅. Was bewusst NICHT der Spec-Maximalausbau ist
(im Code jeweils als REFERENZSCHÄTZUNG/Näherung gekennzeichnet):

- **EV statt Monte-Carlo (Kap. 5):** Die Planbewertung nutzt deterministische
  Erwartungswert-Projektionen (`brain/simulate.py`); Zufallsaktionen gehen als
  EV ein. Spec-konforme Ergebnisverteilungen existieren nur dort, wo das Spiel
  sie liefert (Trade/Jagd).
- **Risikoterme als Proxys (5.4):** P(fatal) = Food-Invariante im Horizont,
  Verlustterm ETA-basiert — kein echtes CVaR über Verteilungen.
- **Referenzkonstanten:** Challenge-Completion-Zeiten, Necrocorn-/TC-/
  Paragon-Zeitwerte, Endgame-Referenzraten bᵢ und einige Policy-/Trait-
  Effekte sind dokumentierte Schätz-/Normierungswerte, keine simulierten
  Größen. Sie beeinflussen Prioritäten, nicht die Korrektheit der Gates.
- **Live-Validierung Late-Game:** Pacts, Leviathans, Relic Stations, Void,
  Challenges und die 12-Schritt-Pre-Reset-Transaktion sind gegen die
  Referenzimplementierung (gamefiles/) und synthetische Fixtures getestet;
  ein Live-Nachweis in fortgeschrittenen Spielständen steht aus. Der
  Governance-Kern (Prognose-Abgleich, MODEL_MISMATCH-Stop) fängt
  Abweichungen im Betrieb ab.

Wenn eine dieser Grenzen im Betrieb sichtbar wird (z. B. wiederholte
Prognose-Abweichungen in einem Late-Game-Modul), ist der Auftrag: die
betroffene Referenzschätzung durch eine gemessene Rate oder eine exakte
gamefiles-Formel ersetzen — die Fundstellen stehen als Kommentar am Wert.
