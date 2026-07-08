# Spec-Dynamik-Audit: Wo die Umsetzung (noch) statischer ist als die Spec

Die [Spielmechanik-Spezifikation](spielmechanik-spec.md) fordert an vielen
Stellen **dynamische Bewertung** (Simulation, Schattenpreise, Grenzwerte).
Diese Tabelle ist der ehrliche Abgleich. Die 33 Zeilen des Erstausbaus sind
umgesetzt (✅); der Live-Betrieb und ein adversarialer Light-Audit (drei
Prüf-Agenten, 7. Juli abends) haben danach NEUE offene Zeilen eröffnet
(#34 ff. unten) — dort steht, wo eine kluge Spec-Mechanik bisher nur als
Konstante/Sonderfall gebaut ist. Das wichtigste Paket daraus
(#34+#35+#36+#41, „Economy-Kern ehrlich machen") ist am 8. Juli umgesetzt
worden (✅ mit Fundstellen in den Zeilen, Abschluss-Notiz am Ende).

Legende: ✅ umgesetzt/spec-nah · 🟠 lohnendste offene Lücken · 🟡 offen, geringere Wirkung

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

## Offene Lücken aus dem Light-Audit (7. Juli, Live-Betrieb + 3 Prüf-Agenten)

Leitfrage des Audits: Wo fordert die Spec eine RECHNUNG/SIMULATION und der
Code liefert eine Konstante oder einen Sonderfall? (Vorbild-Funde aus dem
Live-Betrieb, alle bereits gefixt: Soll-Allokation 12.2, Pfad-Preisvektor,
Sparfenster der DelayPenalty, Cap-Klausel, Farmer-Hysterese.)

| # | Spec | Kluge Spec-Mechanik | Light-Version (Fundstelle) | Status |
|---|---|---|---|---|
| 34 | 10.2 / 11.1 | **λ für ALLE Ressourcen** im Critical Path | PFAD-Preisvektor: aktives Ziel + Housing + alle offenen Meilensteine (`meta.MetaView.open_targets`), rang-diskontiert 1/(1+k) als diskontiertes Maximum (`shadow.path_shadow_prices`/`path_rate_shadow_prices`, Assembly `tactics.path_targets`); Jagd/Trade/Leader/Storage/Cap-Relief laufen damit im λ-Zweig, Schwellen-Fallbacks nur noch Sicherheitsnetz; Sparregel neutralisiert netValue von Störkäufen; λ-Topliste im Cockpit (Economy-Tab, `plan.lambdaTop`) | ✅ |
| 35 | 13.1 / 13.2 | **Gebäudebewertung über alle Modifier** (direkt+indirekt, Energie, Pollution, Rest-Aktivzeit); Factories nach Craft/Engineer/Pollution | snapshot.js exportiert das volle `effects`-Dict pro Gebäude (+ `pollution`-Sektion); `tactics._rate_delta_from_effects`: mehrressourcig inkl. Verbrauch (PerTick ×TPS, DemandRatio ×Bedarf, Ratio ×Rate, coalRatioGlobal nur 1. Exemplar, magnetoRatio/happiness/craftRatio als dokumentierte Näherungen), Mint/Brewery in der Whitelist, Pollution als λ-bewerteter Zeitkostenterm (`_pollution_cost_time`, Schwelle 5e8). Restnäherungen ehrlich: craftRatio nur Autocraft-Durchsatz, tradeRatio/standingRatio via Trade-EV 14.1, Pollution nur das Arrival-Slowdown-Regime | ✅ |
| 36 | 5.2 / 8.3 | **Vorwärtssimulation mit Bevölkerungswachstum und echten Käufen** | snapshot.js exportiert `village.kittensPerSec` (village.js calculateKittensPerTick ×TPS); `simulate.project` lässt die Population wachsen (Housing-Klemme, Catnip-Mehrlast) → FIRST-/PARAGON-/PRICE_RATIO-Restzeiten zustandsabhängig. Offen bleibt der zweite Halbsatz: Varianten a/b/c sind weiter eine abstrakte Ratenrampe, keine simulierten Kaufsequenzen (Wirkung deutlich kleiner, Restlücke dokumentiert) | ✅ |
| 37 | 13.4 | **Alle Policies + Kombinationen** über den Restplan bewerten | `policy.POLICY_EFFECTS` deckt 23 von ~66 Policies; der Rest (u. a. alle Race-Relations, Pacts-Policies, fullIndustrialization) ist NIE Kandidat; keine Kombinationsbewertung | 🟡 |
| 38 | 8.3 / 18.2 | **Restzeiten simuliert, ChallengeValue zustandsabhängig** | 5 von 12 Run-Typen scoren auf Konstanten (SEED 6 h, CHALLENGE const, POSITIVE_CS 60 s×n …); `challenge_value` = Konstante/Konstante → feste Rangfolge | 🟡 |
| 39 | 10.4 / 6.4 | **Payback gegen den GEPLANTEN Reset**; Makrohorizont „mind. ein voller Run" | `shadow.run_horizon` = 2×Spielzeit geklemmt [30 min, 4 h]; Reset-Projektion (reset.py) wird nicht durchgereicht; 2-h-/4-h-Klemmen schneiden lange Runs ab | 🟡 |
| 40 | 12.2 | **Marginalraten mit Gebäude-/Upgrade-Multiplikatoren** | `shadow.JOB_BASE_RATES` statisch ×Happiness; `target_allocation` subtrahiert Basisraten von multiplikator-behafteten Ist-Raten (Restrate zu hoch) → Mid-Game-Verzerrung | 🟡 |
| 41 | 12.1 | **ExpectedKittenArrivals** × KittenValue | `_housing_eval`: Slots füllen sequenziell mit `village.kittensPerSec` (Slot i arbeitet H − i/Rate); ohne Snapshot-Rate Fallback Sofort-Vollbelegung; Food-Gate bleibt bewusst worst-case (I-01) | ✅ |
| 42 | 20.1 / 20.2 | **V(post) simuliert; Reset-Trigger je Run-Typ** | Neustart als lineare Dreiecksrampe; `reset.evaluate` kennt nur FIRST/PARAGON/CHALLENGE/Perk — RELIGION-, SEED-, POSITIVE_CS-, UNICORN-Runs erreichen ihre Reset-Transaktion nie | 🟡 |
| 43 | 17.2/17.5 / 19.1 | **λ-bewertete irreversible TC-/CS-Käufe** | `TC_VALUE_REF_S=600`, `PARAGON_VALUE_REF_S=900`, `REBUILD_DELAY_PER_CS_S=60` — Referenzkonstanten steuern Shatter-Batches und CS-Zielzahl (irreversibel) | 🟡 |
| 44 | 6.1 / 6.3 | **C(S) über alle 7 Dimensionen projiziert; Meilensteine „operational nutzbar"** | `endgame_score` projiziert nur Paragon (übrige ΔlnC-Beiträge 0); `frontier_complete` prüft Unlock-Flags statt Betrieb (Energie/Versorgung) | 🟡 |
| 45 | 14.1 / 14.2 / 15.1 | **Verdrängungsprüfung, Batch-Optimum, Praise-Integral** | Trade: nur λ-Kosten, kein expliziter Catpower-/Gold-Konkurrenzcheck; Jagd: immer alle Squads, Schwelle statt Batch-Optimum; Praise: Overflow-Heuristik statt Integral bis Adore/Reset | 🟡 |
| 46 | 5.3 | **Weckquellen vollständig** (inkl. „Fertigstellung eines Sparziels") | `scheduler.next_wakeup`: Saison/Cap/ETA/Kontrollpunkt; Sparziel-, Festival-, Heat-, Cycle-Weckung fehlen (Wirkung gering durch 30-s-Clamp) | 🟡 |
| 47 | 5.4 | **CVaR über Ergebnisverteilungen** | P(fatal) binär (Food), Verlustterm ETA-basiert — dokumentierter Proxy | 🟡 |

Sauber spec-treu laut Audit: Kontrollpunkt-Regel 21.2, TAP-Pfad (religion.py),
Energie-Grenznutzen-Reihenfolge 16.4, Governance-Kern (Kap. 21–23).

## Erledigt (8. Juli): Paket „Economy-Kern ehrlich machen" (#34+#35+#36, #41 miterledigt)

Der zusammenhängende Umbau gegen die Fehlerklasse aller bisherigen
Live-Funde (Null-Woodcutter, Monokultur, „kein Spar-Drive") ist umgesetzt —
vollständige Pfad-Schattenpreise, echte Gebäudeeffekte, wachsende
Bevölkerung in Projektion und Housing. Fundstellen in den Zeilen #34/#35/
#36/#41 oben; Regressionstests in `tests/test_economy_core.py` (u. a.
Steamworks-NetValue, λ_furs über die Craft-Kaskade, FIRST_RUN-Restzeit mit
Ankunftsrate). Bewusst offen gebliebene Restnäherungen stehen ehrlich in
den Tabellenzeilen (craftRatio nur Autocraft, tradeRatio via Trade-EV,
Pollution nur Arrival-Slowdown, Kaufsequenz-Simulation der Varianten).
