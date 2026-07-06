# Spec-Dynamik-Audit: Wo die Umsetzung (noch) statischer ist als die Spec

Die [Spielmechanik-Spezifikation](spielmechanik-spec.md) fordert an vielen
Stellen **dynamische Bewertung** (Simulation, Schattenpreise, Grenzwerte).
Diese Tabelle ist der ehrliche Abgleich: Was ist spec-konform dynamisch, was
ist vereinfacht/statisch, was fehlt. Jede offene Zeile taugt als
eigenständiger Auftrag für eine Claude-Code-Session (Umsetzungsrezept:
[brain.md](brain.md) → „Erweitern"; akute Trigger meldet der
Ausbaugrenzen-Wächter im Cockpit automatisch).

Legende: ✅ behoben/spec-nah · 🟠 lohnendste offene Lücken · 🟡 offen, geringere Wirkung

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

## Offene Lücken — Abdeckung (Spielinhalte/Makro)

| # | Spec | Mechanik | Ist-Zustand | Status |
|---|---|---|---|---|
| 16 | 8.2 / 9 | **13 Run-Typen + Makrophasen P0–P8** | 3 Run-Typen aktiv (FIRST/PRICE_RATIO/PARAGON, Rest als Konstanten angelegt), Phasen P0–P2 (`meta._admissible_run_types`/`evaluate`) | 🟠 |
| 17 | 13.4 | **Policy-Wahl**: exklusive Kombinationen über den Restplan simulieren | nicht automatisiert (Frontier „policies" mit Nachrüst-Prompt) | 🟠 |
| 18 | 18.1–18.4 | **Challenges**: Katalog, ChallengeValue-Auswahl, Kombinationssimulation, Reset-Verifikation | nicht automatisiert (Frontier „challenges") | 🟠 |
| 19 | 17.1–17.5 | **Shatter-Engine**: TC-Bilanz, RRValue, Chrono-Furnace/Heat-Steuerung, Relic Stations, Shatter-Regeln A–D | nur konservative Shatter-Basis (`tactics._time_candidates`: RR ≥ 1, Heat-Spielraum, 5-TC-Reserve, Batch ≤ 5); Frontier „shatter_engine" | 🟠 |
| 20 | 15.2 / 15.4 / 15.5 | **TAP-Transaktion, Alicorn-Konvertierung, Pacts** | nur Adore-light beim Reset (`reset.execute_reset`); Transcend/Alicorns/Pacts fehlen (Frontiers „transcend", „pacts") | 🟡 |
| 21 | 20.3 | **Pre-Reset-Transaktion** (12 Schritte) | 5 Schritte (Save-Export, Adore-light, Kapitelkarte, Reset, Validierung); Challenge-Verifikation, permanente Käufe, Konvertierungen, CS-Zielstand fehlen | 🟡 |
| 22 | 16.1 / 16.3 | **AM-Cap als zusammenhängender Makroplan** | Space-Gebäude sind generische Einzelkandidaten mit Engpass-Kopplung; kein Antimatter-Makroplan | 🟡 |
| 23 | 1.3 / 6.3 | **Endgame-Index C(S)** und ΔlnC/Δt nach der Progressionsfront | nicht modelliert (relevant erst ab P7/P8) | 🟡 |
| 24 | 19.2 / 19.3 | **Positive CS-Schleife** (Vektordominanz) und **Void-Makroplan** | nicht modelliert; CS-Zielzahl-Suche (#12) ist die Vorstufe (Frontier „cs_loop") | 🟡 |
| 25 | Anhang B | **SET_TEMPUS_FUGIT** | Tempus Fugit wird nicht angesteuert | 🟡 |

## Offene Lücken — Governance/Infrastruktur

| # | Spec | Mechanik | Ist-Zustand | Status |
|---|---|---|---|---|
| 26 | G-02 / 22.2 | **Harter MODEL_MISMATCH-Stop** (nur lesende/sichernde Aktionen bei Versions-/Modellabweichung) | weiche Warnung + Cockpit-Badge (`runtime._check_version`), keine Aktionssperre — bewusste Designentscheidung (architecture.md #4), bleibt aber eine Safety-Lücke gegenüber der Spec | 🟠 |
| 27 | G-10 / 22.2 | **Prognose-vs-Beobachtung-Distanzprüfung** mit Toleranz und Stop | Beobachtung nur deskriptiv (`loop._cycle` → `record.observed`), kein Vergleich gegen eine Prognose | 🟡 |
| 28 | 21.1–21.3 / 5.3 | **Ereignisgetriebenes Replanning** (harte/weiche Trigger, Ereigniswarteschlange, Commit-Grenze) | fester 1,5-s-Tick (`loop.run`); Safety-Vorrang existiert, aber keine Trigger-Klassifikation und keine Planbindung | 🟡 |
| 29 | 5.4 / 6.2 | **Risikoterme** (CVaR, κ·P(fatal), μ·irreversible Verluste) | nicht modelliert; Vorsicht steckt nur in deterministischen Gates (Food, TC-Schutz) | 🟡 |
| 30 | 11.2 / 11.4 | **Effektive Craft-Kosten inkl. Opportunitätskosten; Cap-Ausgabe als NetValue-Reihenfolge** | Craft-Kaskade rekursiv, aber Score tiefenbasiert; Cap-Schutz verteilt auf feste Schwellen (0,92 Craft / 0,95 Gold; Jagd/Praise inzwischen EV-basiert) | 🟡 |
| 31 | 23 | **DecisionTrace-Vollständigkeit** (state_hash, predicted vs. observed, replan_reason) | DecisionRecord mit Kandidaten/Komponenten/Beobachtung, aber ohne state_hash, Prognosefeld und strukturierten replan_reason (`records.py`) | 🟡 |
| 32 | 24.1 | **Golden-State-Fixtures + Replay-Test** | nur programmatische `make_snap`-Fixtures; kein `tests/fixtures/`, kein Replay aus dem JSONL-Log | 🟡 |
| 33 | 8.4 / 22.3 | **Optionswert von Unlocks; generische Deadlock-Auflösung** | Unlocks mit festen Score-Gewichten; Deadlocks punktuell gelöst (`wood_first`, Konversions-Reservierung) | 🟡 |

## Empfohlenes nächstes Paket (größter Verhaltensgewinn)

**#16 + #18 zusammen** („Makro-Vollausbau"): Die Simulations-Infrastruktur
(`simulate.project`, `determine_run_plan`) steht seit dem
Schattenpreis-Ausbau — neue Run-Typen brauchen nur noch Zulässigkeitsregel,
Zielmeilensteine und eine Restzeit-Formel in `meta._plan_restzeit`.
CHALLENGE_RUN ist der wertvollste Kandidat (Erstbelohnungen sind permanente
Meilensteine der Progressionsfront), danach RELIGION_RUN/UNICORN_RUN.

Fertiger Auftrag zum Kopieren:

> Erweitere den Kittens-Player um CHALLENGE_RUN (Spec 8.2, 18.1–18.4):
> Challenge-Katalog mit formalem Profil (Einschränkungen, Zielbedingung,
> Erstbelohnung) als Daten, ChallengeValue = Verkürzung der erwarteten
> Restzeit / erwartete Abschlusszeit (18.2), Zulässigkeit und Restzeit in
> player/brain/meta.py (_admissible_run_types/_plan_restzeit) über die
> EV-Projektion aus player/brain/simulate.py, Challenge-Aktivierung als
> irreversible Aktion mit Verifikation vor dem Reset (18.4,
> reset.execute_reset). Bestehende Tests bleiben grün; neue Tests auf
> make_snap-Fixtures.
