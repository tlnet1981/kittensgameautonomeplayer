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

## Safety (`brain/safety.py`, Spec Kap. 7)

Umgesetzt ist die **Food-Invariante I-01** über die Worst-Winter-Projektion:

```
worstWinterNet = netJetzt − feldBasis·saisonMod + feldBasis·winterMod (0.25)
Reserve        = catnip / max(ε, −worstWinterNet)
```

- Reserve < **5 min** → Schutzaktion mit Score 10 (Farmer zuweisen →
  Kitten aus größtem Job ziehen → Feld bauen → Catnip sammeln).
  Kalibrierung: ein kompletter Winter dauert ~200 s Realzeit.
- Reserve < **10 min** → Housing-Käufe blockiert (neue Kitten = mehr Verbrauch).
- Die Schutzaktion **ersetzt nicht** die Kandidatenliste, sie wird mit
  Vorrang eingereiht — das Cockpit zeigt weiterhin alle Alternativen.

Energie- (I-04) und Reset-Invarianten (I-02) folgen mit M4/M3.

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

## DecisionRecord (`brain/records.py`, Spec Kap. 23)

Jede Entscheidung enthält: Trigger, Phase/Run/Ziel, Engpass, **alle**
Kandidaten mit Score-Zerlegung und Ablehnungsgrund, Gewinner,
Ausführungsergebnis und beobachteten Effekt. Das ist die Datenquelle des
Decision Inspectors und des JSONL-Logs (Reproduzierbarkeit).

## Bewusste Vereinfachungen gegenüber der Spec (Stand M1)

| Spec | Hier | Warum |
|---|---|---|
| Stochastische Vorwärtssimulation (Kap. 5) | Live-Raten + Formeln Anhang D | Spiel = Modell; genügt für P0–P2 |
| Exakte Schattenpreise λᵢ (10.2) | Engpass-ETA + Komponenten-Gewichte | transparent, robust, deterministisch |
| MacroPlan-Kandidaten ×3 Varianten (8.3) | ein Meilensteinpfad + Opportunismus | kommt mit M3 (Run-Typen) |
| Payback-Regel (10.4) | implizit über Gewichte | explizit ab M2 (Handel) |
| Model-Mismatch-Stop (22.2) | Warnung + DEGRADED | privater Betrieb gegen Online-Spiel |
