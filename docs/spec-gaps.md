# Spec-Dynamik-Audit: Wo die Umsetzung (noch) statischer ist als die Spec

Die Spielmechanik-Spezifikation fordert an vielen Stellen **dynamische
Bewertung** (Simulation, Schattenpreise, Grenzwerte). Diese Tabelle ist der
ehrliche Abgleich: Was ist spec-konform dynamisch, was ist vereinfacht/
statisch, was fehlt. Jede offene Zeile taugt als eigenständiger Auftrag für
eine Claude-Code-Session (Umsetzungsrezept: [brain.md](brain.md) → „Erweitern";
akute Trigger meldet der Ausbaugrenzen-Wächter im Cockpit automatisch).

Legende: ✅ behoben/spec-nah · 🟠 lohnendste offene Lücken · 🟡 offen, geringere Wirkung

| # | Spec | Mechanik (dynamisch gefordert) | Ist-Zustand | Status |
|---|---|---|---|---|
| 1 | 7.2 | **Food-Sicherungshorizont** (saison-/zustandsabhängig) | Saisonprojektion bis Ende des nächsten Winters (`derived.project_catnip`), Schwellen skalieren mit Bedarf | ✅ |
| 2 | 12.1 | **HousingValue** (Ankünfte × Kitten-Wert − Zeitkosten) | Bedarfs-Gate (Kapazität voll) + Food-Projektion inkl. Mehrlast + Paragon-Grenzwert ab 68 Kitten (`tactics._housing_eval`) | ✅ |
| 3 | 20.4 | **Paragon-Speedrun-Abbruch** (marginale Rate) | Marginalraten-Fenster vs. Ø-Rate implementiert (`reset._paragon_speedrun_rule`) | ✅ |
| 4 | 10.2 | **Schattenpreise λᵢ für alle Ressourcen**; Kosten/Nutzen in Zielzeit-Äquivalenten | nur Engpass-ETA EINER Ressource + feste Score-Gewichte | 🟠 |
| 5 | 10.4 | **Payback-Regel** (Amortisation vor Reset/Milestone, sonst kein Produktionskauf) | nur implizit über Gewichte | 🟠 |
| 6 | 12.2 | **Job-Zuweisung** über marginalen Zielzeitgewinn je Job, iterativ mit Tauschoperationen | Engpass→Job-Mapping, Balance-Fallback, Ein-Kitten-Rebalance | 🟠 |
| 7 | 8.3 | **Run-Typ-Wahl** durch Simulation aller Makroplan-Kandidaten (×3 Varianten) | feste Zustandsableitung FIRST → PRICE_RATIO → PARAGON | 🟠 |
| 8 | 14.1 | **TradeValue** als Erwartungswert über die Ergebnisverteilung (Saison, Standing, Ships) | „Rasse liefert Engpass"-Regel + Batch-Limits | 🟡 |
| 9 | 20.1 | **Reset-Wert** V(post-reset) − V(continue) via Simulation | Schwellenregeln (35 Paragon; Perk-Finanzierung) | 🟡 |
| 10 | 11.3 | **Storage-Bedingungen B–D** (Carryover-Wert, Offline-Puffer, Challenge-Cap) | nur Bedingung A (Cap blockiert Critical-Path-Ziel) | 🟡 |
| 11 | 16.4 | **Energie-Drosselung**: Verbraucher nach Grenznutzen deaktivieren | nur Erzeuger-Priorisierung bei Defizit | 🟡 |
| 12 | 19.1 | **Chronosphere-Zahl**: Suche über n−2…n+3 je Run | opportunistischer Einzelkauf | 🟡 |
| 13 | 12.3 | **Leader-Wahl** (Trait/Job-Paar mit größter Zielzeitverkürzung) | nicht umgesetzt | 🟡 |
| 14 | 14.2 / 15.1 | **Jagd-/Praise-Timing** per EV-Vergleich | Cap-Schwellen (85 % / 95 %) + Praise-Sparregel für Religion-Käufe | 🟡 |
| 15 | 5 / 6.2 | **Stochastische Vorwärtssimulation + Planbewertung** | Live-Raten + Formeln aus Anhang D (Grundsatzentscheidung: „das Spiel ist das Modell") | 🟡 |

## Empfohlenes nächstes Paket (größter Verhaltensgewinn)

**#4 + #5 + #6 zusammen** („echte Schattenpreise"): ein gemeinsamer Umbau in
`player/brain/tactics.py`, der ETA-Ableitungen je Ressource berechnet
(λᵢ ≈ ΔETA bei +1 Einheit/s), Kauf-Scores daraus ableitet (Cost_time/
Benefit_time, Spec 10.3) und die Job-Zuweisung über denselben Grenzwert
laufen lässt. Damit werden die meisten festen Gewichte durch berechnete
Werte ersetzt — und der Decision Inspector zeigt automatisch die echten
Zeit-Äquivalente.

Fertiger Auftrag zum Kopieren:

> Erweitere den Kittens-Player um echte Schattenpreise (Spec 10.2–10.4 und
> 12.2): Berechne je Ressource λᵢ = marginale ETA-Verkürzung am aktiven
> Meilenstein (numerische Ableitung über die Engpass-ETA genügt), rechne
> Kandidaten-Kosten/-Nutzen in Zielzeit-Äquivalente um (NetValue = Benefit_time
> − Cost_time, Payback-Regel 10.4 gegen den Run-Horizont), und ersetze die
> festen Score-Gewichte in player/brain/tactics.py schrittweise. Job-Zuweisung
> (12.2): marginaler Zielzeitgewinn je Job statt Engpass-Mapping. Die
> Score-Komponenten im DecisionRecord sollen die berechneten Sekundenwerte
> zeigen. Bestehende Tests anpassen, neue Tests auf Snapshot-Fixtures.
