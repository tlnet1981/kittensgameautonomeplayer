# Spec-Dynamik-Audit: Wo die Umsetzung (noch) statischer ist als die Spec

Die [Spielmechanik-Spezifikation](spielmechanik-spec.md) fordert an vielen
Stellen **dynamische Bewertung** (Simulation, Schattenpreise, Grenzwerte).
Diese Tabelle ist der ehrliche Abgleich. Die 33 Zeilen des Erstausbaus sind
umgesetzt (✅); der Live-Betrieb und ein adversarialer Light-Audit (drei
Prüf-Agenten, 7. Juli abends) haben danach NEUE offene Zeilen eröffnet
(#34 ff. unten) — dort steht, wo eine kluge Spec-Mechanik bisher nur als
Konstante/Sonderfall gebaut ist. Die drei wichtigsten Pakete daraus
sind am 8. Juli umgesetzt worden: „Economy-Kern ehrlich machen"
(#34+#35+#36+#41), „Makro & Reset ehrlich machen" (#38+#39+#42) und
„Politik, Jobs & irreversible Käufe ehrlich machen" (#37+#40+#43) —
✅ mit Fundstellen in den Zeilen, Abschluss-Notizen am Ende.

Legende: ✅ umgesetzt/spec-nah · 🟠 lohnendste offene Lücken · 🟡 offen, geringere Wirkung

## Bewertungs-Dynamik (Kern-Audit)

| # | Spec | Mechanik (dynamisch gefordert) | Ist-Zustand | Status |
|---|---|---|---|---|
| 1 | 7.2 | **Food-Sicherungshorizont** (saison-/zustandsabhängig) | Saisonprojektion bis Ende des nächsten Winters (`derived.project_catnip`), Schwellen skalieren mit Bedarf | ✅ |
| 2 | 12.1 | **HousingValue** (Ankünfte × Kitten-Wert − Zeitkosten) | Bedarfs-Gate (Kapazität voll) + Food-Projektion inkl. Mehrlast + Paragon-Grenzwert ab 68 Kitten (`tactics._housing_eval`) | ✅ |
| 3 | 20.4 | **Paragon-Speedrun-Abbruch** (marginale Rate) | Marginalraten-Fenster vs. Ø-Rate implementiert (`reset._paragon_speedrun_rule`) | ✅ |
| 4 | 10.2 | **Schattenpreise λᵢ für alle Ressourcen**; Kosten/Nutzen in Zielzeit-Äquivalenten | λᵢ numerisch über die Engpass-ETA inkl. Craft-Kaskade (`shadow.shadow_prices`); Cost_time/Benefit_time/NetValue als Sekundenwerte im Decision Inspector, NetValue fließt normiert in den Score | ✅ |
| 5 | 10.4 | **Payback-Regel** (Amortisation vor Reset/Milestone, sonst kein Produktionskauf) | Payback-Gate in `tactics._building_candidates` gegen `shadow.run_horizon`; Unlocks/Safety/Dependencies ausgenommen (Spec-konform) | ✅ |
| 6 | 12.2 | **Job-Zuweisung** über marginalen Zielzeitgewinn je Job, iterativ mit Tauschoperationen | `shadow.job_score` (Σ λᵢ·Marginalrate) wählt den Job; Tausch nur bei Gewinn > Schwelle (`tactics._job_candidates`/`_job_rebalance_candidate`); Marginalraten seit #40 beobachtet (`job_marginal_rates`), Basisraten nur Fallback | ✅ |
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
| 26 | G-02 / 22.2 | **Harter MODEL_MISMATCH-Stop** (nur lesende/sichernde Aktionen bei Versions-/Modellabweichung) | AgentMode-Gate + acknowledge vorhanden; **Betreiberentscheidung (8. Juli, bewusste G-02-Abweichung):** Bei reiner VERSIONSabweichung meldet der Guard nur noch (Badge + Event) und spielt weiter — hart erst mit `KGP_VERSION_GUARD_HARD=1` (`config.version_guard_hard`, `runtime.apply_version_guard`). Der Prognose-Streak-Stopp (G-10, echte Modellabweichung im Betrieb) bleibt IMMER hart | ✅ |
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
| 37 | 13.4 | **Alle Policies + Kombinationen** über den Restplan bewerten | `policy.POLICY_EFFECTS` deckt alle 66 Policies aus science.js:850-2189 (Übersetzungs-Konventionen im Modul-Docstring; 22 ehrlich `unratable` — Wert 0, I-07 entscheidet statt stillem Ausschluss); Zweigwert `policy.branch_value` (unlocks-BFS ≤ 3, Gruppen-Maximum über blocks-Komponenten, harmonischer Diskont), i07_check/best_policy vergleichen Zweige; Horizont = `run_plan["restzeitS"]` (tactics reicht meta_view.run_plan durch). Restnäherungen ehrlich: Schätz-Konventionen je Eintrag gekennzeichnet (`estimate`), Embassy-/Cycle-Mittelwerte statt Live-Werten | ✅ |
| 38 | 8.3 / 18.2 | **Restzeiten simuliert, ChallengeValue zustandsabhängig** | Alle Restzeit-Konstanten ersetzt: SEED = ETA der nächsten ganzen Carryover-Einheit (`chrono.seed_progress`), POSITIVE_CS = Verdienzeit der Wiederaufbaukosten (`rebuild_cost_vector`/beobachtete Raten), SHATTER-Ziel = Reserve + Heat-gedeckelter Batch (`meta._shatter_tc_target`), CHALLENGE = Zielprojektion je Challenge (`challenge.completion_eta`, Mindestlaufzeit-Floor; unbeobachtbar/unerreichbar → ehrlich ∞). `challenge_value` = `reward_seconds` (Produktionszeit-Äquivalent) / projizierte Completion; Referenzschätzungen NUR noch als Fallback ohne Zielobjekte im Snapshot. Restnäherungen ehrlich: Energy-Stages nicht ablesbar, postApocalypse prinzipiell nicht projizierbar, reward_seconds nur für übersetzbare Effekte | ✅ |
| 39 | 10.4 / 6.4 | **Payback gegen den GEPLANTEN Reset**; Makrohorizont „mind. ein voller Run" | Die Makroplan-Restzeit (`meta.determine_run_plan` → `run_plan["restzeitS"]`) fließt als `reset.evaluate["etaSeconds"]` in `tactics.generate(run_horizon_s=…)`: das Payback-Gate prüft gegen den geplanten Reset, nach unten `HORIZON_PLANNED_MIN` (Anti-Deadlock), nach OBEN ungeklemmt (6.4 — lange Runs planen lang); `resolve_deadlock` reicht durch. `shadow.run_horizon` (2×Spielzeit, [30 min, 4 h]) bleibt Heuristik-Fallback ohne Projektion/Reset-Ziel/bei TC-Block; `_score_plans` bewertet bewusst weiter mit der Heuristik (keine Zirkularität Plan→Horizont→Plan) | ✅ |
| 40 | 12.2 | **Marginalraten mit Gebäude-/Upgrade-Multiplikatoren** | snapshot.js exportiert je Job `ratesPerKitten` (village.js updateResourceProduction für ein Skill-0-Marginalkitten × game.js calcResourcePerTick-Kette 3243-3331; Weather bewusst außen vor — wirkt vor der Villager-Addition; priest.calculateEffects nie aufgerufen); `shadow.job_marginal_rates` autoritativ (auch leer), `job_score`/`target_allocation`/6 tactics-Leser umgestellt — Baseline-Subtraktion exakt statt Phantom-Restrate. JOB_BASE_RATES × Happiness nur noch Fallback ohne Snapshot-Feld. Tests `tests/test_job_rates.py` | ✅ |
| 41 | 12.1 | **ExpectedKittenArrivals** × KittenValue | `_housing_eval`: Slots füllen sequenziell mit `village.kittensPerSec` (Slot i arbeitet H − i/Rate); ohne Snapshot-Rate Fallback Sofort-Vollbelegung; Food-Gate bleibt bewusst worst-case (I-01) | ✅ |
| 42 | 20.1 / 20.2 | **V(post) simuliert; Reset-Trigger je Run-Typ** | Vier Zweige VOR dem Perk-Catch-all in `reset.evaluate`: RELIGION (TAP-Punkt via `transcend_value["worth"]`), UNICORN (Ziggurat + 2500er-Opfer-Batch), SEED (`seed_progress["basisReached"]`), POSITIVE_CS (`positive_cs_check`-Dominanz) — je ResetValue-geprüft (`_goal_reset_decision`). V(post) = Neustart-Kurzsimulation (`_post_reset_paragon`: Carryover-Startkapital, Ankunftsrate × Paragon-Bonus-Verhältnis aus portiertem prestige.js `getParagonProductionRatio`/game.js `getLimitedDR`); ohne Ankunftsrate bleibt die lineare Rampe als Fallback (`vPostMode` transparent). Restnäherung: paragonRatio-Effekt konservativ 1.0 (nicht im Snapshot) | ✅ |
| 43 | 17.2/17.5 / 19.1 | **λ-bewertete irreversible TC-/CS-Käufe** | `timecrystal.tc_opportunity_s` (max aus λ_TC und Shatter-Jahresertrag) bepreist TC-Ausgaben in rr_value und Regel D (`tcValueMode` transparent); `paragon_value_s` = Δ`prestige.paragon_production_ratio`/(1+ratio) × Σλ·rate × Horizont für Regel D (`paragonValueS`); `chrono._rebuild_eta_seconds` = Engpass-ETA des Flotten-Wiederaufbaus aus beobachteten Raten (`rebuildMode` eta\|fallback). Alle drei Konstanten NUR noch Fallback ohne Daten. Bewusste Ausnahme: Regeln A/B behalten supplied-λ-sonst-Referenz — λ_TC := Shatter-Ertrag wäre dort selbstreferenziell (Regel A könnte nie feuern, dokumentiert) | ✅ |
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

## Erledigt (8. Juli): Paket „Makro & Reset ehrlich machen" (#38+#39+#42)

Die strategische Rückgrat-Schicht ist umgesetzt: Alle Restzeit-Konstanten
der Run-Typ-Wahl sind Projektionen gewichen (ehrlich ∞, wo nichts
beobachtbar ist), das Payback-Gate prüft gegen den GEPLANTEN Reset (die
Makroplan-Restzeit fließt einquellig meta → reset.etaSeconds →
tactics.generate; 4-h-Klemme nur noch im Heuristik-Fallback), und
RELIGION/UNICORN/SEED/POSITIVE_CS haben eigene ResetValue-geprüfte
Reset-Trigger vor dem Perk-Catch-all — mit V(post) als echter
Neustart-Kurzsimulation (Rampe bleibt Fallback, vPostMode transparent).
Fundstellen in den Zeilen #38/#39/#42 oben; Regressionstests in
`tests/test_macro_reset.py` (u. a. SEED-Restzeit reagiert auf den
Zustand; run_horizon folgt der Reset-Projektion; RELIGION_RUN erreicht
seine Reset-Transaktion). Bewusst offene Restnäherungen stehen in den
Tabellenzeilen.

## Erledigt (8. Juli): Paket „Politik, Jobs & irreversible Käufe ehrlich machen" (#37+#40+#43)

Die drei Referenztabellen-/Konstanten-Stellen rechnen jetzt aus dem
Zustand: Die Policy-Tabelle deckt alle 66 Policies der Referenzversion ab
(ehrlich `unratable`, wo kein Ratenbezug existiert — die I-07-Prüfung
entscheidet, kein stiller Ausschluss mehr) und bewertet exklusive Zweige
über den Restplan (`policy.branch_value`, Horizont aus
`run_plan["restzeitS"]`); die Soll-Allokation nutzt die BEOBACHTETEN
Pro-Kitten-Marginalraten aus dem Spiel (`village.jobs[].ratesPerKitten`
im Snapshot, `shadow.job_marginal_rates`) statt der statischen
Basisraten — der Baseline-Subtraktionsfehler ist damit weg; und die
irreversiblen TC-/CS-Käufe hängen an `tc_opportunity_s`/
`paragon_value_s`/`_rebuild_eta_seconds` statt an den drei Konstanten
(nur noch dokumentierte Fallbacks). Fundstellen in den Zeilen #37/#40/
#43 oben; Regressionstests in `tests/test_job_rates.py`,
`tests/test_policy.py` (Vollabdeckungs-Invariante, Zweig-Kippfall,
unratable-Semantik) und `tests/test_timecrystal.py` (Regel D reagiert
auf den Zustand, Rebuild-ETA). Bewusst offene Restnäherungen stehen in
den Tabellenzeilen (Schätz-Konventionen je Policy-Eintrag; Skill-0-
Marginalkitten, Weather außen vor; Shatter-Regeln A/B bewusst
supplied-λ-sonst-Referenz).

## Empfohlenes nächstes Paket (Paket 4)

Sinnvoll als nächstes: #44 (C(S) über alle 7 Dimensionen) + #45
(Trade-Verdrängung/Jagd-Batch/Praise-Integral) + #46/#47 (Weckquellen,
CVaR-Proxy) — die verbleibenden, kleineren Light-Reste.
