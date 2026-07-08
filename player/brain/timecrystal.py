"""Shatter-Engine: TC-Bilanz, RR-/Furnace-Wert und Shatter-Regeln A–D
(Spielmechanik-Spec 17.1–17.5 + Anhang D „RR-Wert").

Alle Spielkonstanten stammen aus der Referenzversion (gamefiles/, Kittens
Game 1.5.0.2) und zitieren Datei/Zeile. Fehlen Snapshot- oder λ-Daten,
liefern die Funktionen None bzw. konservative Ergebnisse — der Aufrufer
(tactics._time_candidates) fällt dann auf das bisherige konservative
Verhalten zurück (kein Crash, kein Raten).

Mechanik der Referenz:
- shatter(amt) springt amt Jahre; Ertrag je Jahr = Produktion/Tick ×
  Ticks/Jahr × shatterTCGain, je Ressource am Cap geklemmt
  (time.js:663-736, addRes-Limits 693-705).
- shatterTCGain = 0.01 je Resource-Retrieval-Stufe (time.js:485-496,
  Schreibweise „ressourceRetrieval"!), multipliziert mit (1 + rrRatio)
  (time.js:670) — rrRatio fehlt im Snapshot und zählt konservativ 0.
- Preis: 1 TC je Shatter (ShatterTCBtn), +1 % je Heat-Einheit ÜBER heatMax
  (time.js getPricesMultiple, penaltyPerHeat = 0.01, Zeile ~1260).
- Heat: +10 je Shatter (5 nach 1000-Years-Erstabschluss, time.js:1407
  doShatter); Abbau heatPerTick = 0.01 Basis (time.js:650 effectsBase)
  + 0.02 je Chrono Furnace („blastFurnace", time.js:337), pro Tick.
- Chrono Furnace: 25 TC + 5 Relic, priceRatio 1.25, +100 heatMax je
  Einheit (time.js:328-344, calculateEffects heatMax = 100 + Expansion).
- Kalender: 10 Ticks/Tag × 100 Tage/Saison × 4 Saisons = 4000 Ticks/Jahr
  (calendar.js:212-218); yearsPerCycle = 5 (cycleYearColors,
  calendar.js:46-52/306), cyclesPerEra = 10 (cycles-Array, 55-218/307).
- Paragon aus Jahren: floor(year/1000) (Anhang D, derived.resetParagon).
"""

from __future__ import annotations

from player.state import access as A

from . import challenge, prestige, religion, shadow

EPS = 1e-9

# --- Referenzwerte Kittens Game 1.5.0.2 (Fundstellen siehe Docstring) ---
TICKS_PER_YEAR = 10 * 100 * 4        # calendar.js:212-218
SHATTER_TC_GAIN_PER_RR = 0.01        # time.js:493-495 (shatterTCGain)
HEAT_PER_SHATTER = 10.0              # time.js:1407 (doShatter, factor)
HEAT_PER_SHATTER_1000Y = 5.0         # time.js:1407 (1000Years researched)
BASE_HEAT_PER_TICK = 0.01            # time.js:650 (effectsBase)
FURNACE_HEAT_PER_TICK = 0.02         # time.js:337 (blastFurnace effects)
FURNACE_HEAT_MAX = 100.0             # time.js:341 (heatMax je Furnace)
HEAT_PENALTY_PER_UNIT = 0.01         # time.js:~1260 (penaltyPerHeat)
TC_PRICE_PER_SHATTER = 1.0           # ShatterTCBtn-Basispreis (1 TC/Jahr)
YEARS_PER_CYCLE = 5                  # calendar.js:46-52/306
CYCLES_PER_ERA = 10                  # calendar.js:55-218/307
YEARS_PER_PARAGON = 1000             # Anhang D: floor(year/1000)

# TC-Reserve der Shatter-Engine (wie die bisherige konservative Regel):
TC_RESERVE = 5.0
# Deterministische Obergrenze der Batch-Suche (Rechenbudget, kein Spielwert):
SHATTER_BATCH_SEARCH_MAX = 50

# REFERENZSCHÄTZUNGEN (ehrlich gekennzeichnet, keine Spielkonstanten).
# Seit #43 sind beide NUR NOCH FALLBACK ohne beobachtbare Daten:
# Sekundenwert eines Time Crystals — Ausgabe-Entscheidungen (rr_value,
# Regel D) nutzen tc_opportunity_s (max aus λ_TC und Shatter-Jahresertrag);
# die Konstante greift nur, wenn beides fehlt (bewusst hoch = konservativ):
TC_VALUE_REF_S = 600.0
# Sekundenwert eines Paragon-Punkts für Regel D — maßgeblich ist
# paragon_value_s (Δ getParagonProductionRatio × λ-bewertete Produktion);
# die Konstante greift nur ohne λ-bewertete Produktionsdaten:
PARAGON_VALUE_REF_S = 900.0

# Cycle-Referenztabelle (calendar.js:55-218, cycles[].effects): je Cycle die
# Einträge, die sich auf eine beobachtbare Ressourcen-Rate abbilden lassen
# (Space-Gebäude → Ressource → Multiplikator). Energie-, Cap- und
# Verbrauchs-Effekte (sunlifter/hrHarvester/cryostation/entangler/
# spaceElevator/observatoryRatio) bleiben bewusst außen vor — sie wirken
# indirekt und sind aus dem Snapshot nicht seriös zu bewerten.
CYCLES: tuple[str, ...] = ("charon", "umbra", "yarn", "helios", "cath",
                           "redmoon", "dune", "piscine", "terminus", "kairo")
CYCLE_RATE_EFFECTS: dict[str, list[tuple[str, str, float]]] = {
    "charon": [("moonOutpost", "unobtainium", 0.9)],
    "umbra": [("hydrofracturer", "oil", 0.75), ("planetCracker", "uranium", 0.9)],
    "yarn": [("hydroponics", "catnip", 2.0), ("researchVessel", "starchart", 0.5)],
    "helios": [],
    "cath": [("spaceStation", "science", 1.5), ("sattelite", "starchart", 2.0),
             ("spaceBeacon", "starchart", 0.1)],
    "redmoon": [("moonOutpost", "unobtainium", 1.2)],
    "dune": [("hydrofracturer", "oil", 1.5), ("planetCracker", "uranium", 1.1)],
    "piscine": [("hydroponics", "catnip", 0.5), ("researchVessel", "starchart", 1.5)],
    "terminus": [],
    "kairo": [("spaceStation", "science", 0.75), ("sattelite", "starchart", 0.75),
              ("spaceBeacon", "starchart", 5.0)],
}


# ================================================================ Snapshot-Zugriff

def _time(snap: dict) -> dict:
    t = snap.get("time")
    return t if isinstance(t, dict) else {}


def _cfu(snap: dict, name: str) -> dict | None:
    """Chronoforge-Upgrade aus dem Snapshot (time.chronoforge)."""
    for u in _time(snap).get("chronoforge", []):
        if u.get("name") == name:
            return u
    return None


def rr_level(snap: dict) -> int:
    """Resource-Retrieval-Stufe (time.js:485, „ressourceRetrieval")."""
    u = _cfu(snap, "ressourceRetrieval")
    return int(u.get("val", 0)) if u else 0


def has_time_data(snap: dict) -> bool:
    """Reicht der Snapshot für die Shatter-Engine? (heatMax > 0 ist das
    Signal, dass die Time-Sektion echte Werte liefert.)"""
    return float(_time(snap).get("heatMax", 0) or 0) > 0


def heat_per_shatter(snap: dict) -> float:
    """Heat je Shatter: 10, bzw. 5 nach 1000-Years-Erstabschluss
    (time.js:1407, challenges.getChallenge('1000Years').researched)."""
    c = challenge.get(snap, "1000Years")
    if c is not None and c.get("researched"):
        return HEAT_PER_SHATTER_1000Y
    return HEAT_PER_SHATTER


def _tps(snap: dict) -> float:
    return float(snap.get("meta", {}).get("ticksPerSecond", 5) or 5)


def _space_building_val(snap: dict, name: str) -> int:
    for planet in snap.get("space", {}).get("planets", []):
        for b in planet.get("buildings", []):
            if b.get("name") == name:
                return int(b.get("val", 0))
    return 0


# ================================================================ 17.1 TC-Bilanz

def tc_balance(snap: dict) -> dict:
    """TC-Bilanz aus beobachtbaren Quellen (Spec 17.1).

    TC_net = Zuflüsse − Shatter − Investitionen; Shatter/Investitionen sind
    Entscheidungen des Agenten, beobachtbar sind Bestand und Zuflüsse:
    - Netto-Rate der Ressource timeCrystal (falls etwas produziert),
    - Alicorn-Konversionspotenzial: ⌊Alicorns/25⌋ × (1 + tcRefineRatio)
      (religion.js:3028-3049, Konstanten aus religion.py),
    - Leviathan-Handel: E[TC je Trade] = value × chance/100 der
      timeCrystal-Position (diplomacy.js tradeImpl, Spec 14.4).
    netPositive = mindestens eine Zuflussquelle ist positiv.
    """
    stock = A.res_value(snap, "timeCrystal")
    rate = A.res_rate(snap, "timeCrystal")
    alicorns = A.res_value(snap, "alicorn")
    ratio = float(snap.get("religion", {}).get("tcRefineRatio", 0.0) or 0.0)
    alicorn_tc = (alicorns // religion.ALICORN_SAC_BATCH) * (1.0 + ratio)
    lev_tc = 0.0
    lev = A.race(snap, "leviathans")
    if lev is not None:
        for s in lev.get("sells", []):
            if s.get("name") == "timeCrystal":
                chance = max(0.0, min(1.0, (s.get("chance") or 0.0) / 100.0))
                lev_tc += (s.get("value") or 0.0) * chance
    positive = rate > EPS or alicorn_tc > EPS or lev_tc > EPS
    return {
        "stock": stock,
        "ratePerSec": rate,
        "alicornTcPotential": round(alicorn_tc, 4),
        "leviathanTcPerTrade": round(lev_tc, 4),
        "netPositive": positive,
    }


# ================================================================ RR-Ertrag

def _yield_seconds(snap: dict, lam: dict[str, float], gain: float,
                   years: int) -> float:
    """λ-bewerteter Resource-Retrieval-Ertrag von `years` Shatter-Jahren.

    Je Ressource: Produktion/Tick × 4000 Ticks/Jahr × gain, KUMULIERT am
    Cap-Spielraum geklemmt (time.js:693-705: addRes bis maxValue) — dadurch
    ist der Batch-Wert konkav und die Batch-Suche endet am Sättigungspunkt.
    """
    if gain <= 0 or years < 1 or not lam:
        return 0.0
    tps = _tps(snap)
    total = 0.0
    for r in snap.get("resources", []):
        lam_i = lam.get(r["name"], 0.0)
        rate = r.get("perSec", 0.0)
        if lam_i <= 0.0 or rate <= EPS:
            continue
        amount = (rate / tps) * TICKS_PER_YEAR * gain * years
        cap = r.get("maxValue", 0.0) or 0.0
        if cap > 0:
            amount = min(amount, max(0.0, cap - r.get("value", 0.0)))
        total += lam_i * amount
    return total


def _lam_tc(lam: dict[str, float] | None) -> float:
    """λ_TC für die SHATTER-Regeln A/B — Schattenpreis eines Time
    Crystals; ohne Ziel-λ die dokumentierte Referenzschätzung
    TC_VALUE_REF_S (konservativ hoch).

    Bewusst NICHT tc_opportunity_s (#43): Regeln A/B vergleichen den
    Shatter-Ertrag mit den TC-Kosten — würde λ_TC dort selbst als
    Shatter-Ertrag definiert, wäre der Vergleich selbstreferenziell
    (die Alternative zum Shattern IST das Shattern; Regel A könnte nie
    feuern). λ_TC am aktiven Ziel bleibt die einzige echte Alternative."""
    v = (lam or {}).get("timeCrystal", 0.0)
    return v if v > EPS else TC_VALUE_REF_S


def tc_opportunity_s(snap: dict, lam: dict[str, float] | None
                     ) -> tuple[float, str]:
    """Opportunitätswert eines Time Crystals in Ziel-Sekunden für
    AUSGABE-Entscheidungen (#43: RR-Kauf 17.2, Paragon-Shatter Regel D).

    Der beste beobachtbare Alternativnutzen eines TC ist das Maximum aus
    - λ_TC am aktiven Ziel (TC direkt fürs Ziel verwendbar) und
    - dem λ-bewerteten Shatter-Jahresertrag (1 TC ≙ 1 Shatter-Jahr,
      time.js ShatterTCBtn; Ertrag je Jahr = Produktion/Tick × 4000 ×
      shatterTCGain der aktuellen RR-Stufe, siehe _yield_seconds).
    Fallback TC_VALUE_REF_S nur, wenn beides keine Daten liefert.
    Rückgabe (wert, modus) mit modus ∈ lambda|shatterYield|fallback."""
    lam_tc = (lam or {}).get("timeCrystal", 0.0)
    yield_s = _yield_seconds(snap, lam or {},
                             SHATTER_TC_GAIN_PER_RR * rr_level(snap), 1)
    if lam_tc > EPS or yield_s > EPS:
        if lam_tc >= yield_s:
            return lam_tc, "lambda"
        return yield_s, "shatterYield"
    return TC_VALUE_REF_S, "fallback"


# ================================================================ 17.2 RR-Wert

def rr_value(snap: dict, lam: dict[str, float] | None,
             horizon: float | None = None) -> dict | None:
    """RRValue(k+1) = E[MarginalResourcesPerShatter] · ExpectedFutureShatters
    − TCPrice(k+1) · λ_TC (Spec 17.2 / Anhang D).

    - MarginalResourcesPerShatter: der ZUSATZ-Ertrag einer weiteren RR-Stufe
      (+0.01 shatterTCGain, time.js:494) je Shatter-Jahr, λ-bewertet.
    - ExpectedFutureShatters: konservativ aus dem TC-Bestand — was nach dem
      RR-Kauf und der Reserve übrig bleibt (1 TC je Shatter); Zuflüsse
      (tc_balance) werden bewusst NICHT eingerechnet (dokumentiert).
    - TCPrice(k+1): Effektivpreis aus dem Snapshot (snapshot.js rechnet
      priceRatio 1.3^val ein, time.js:491), bewertet mit tc_opportunity_s
      (#43): der TC-Einsatz kostet den besten Alternativnutzen (λ_TC am
      Ziel oder Shatter-Jahresertrag), nicht eine Konstante.
    None ohne Resource-Retrieval-Eintrag im Snapshot (Schicht nicht erreicht).
    """
    u = _cfu(snap, "ressourceRetrieval")
    if u is None:
        return None
    price_tc = next((p["val"] for p in u.get("prices", [])
                     if p["name"] == "timeCrystal"), 0.0)
    stock = A.res_value(snap, "timeCrystal")
    expected_shatters = max(0.0, stock - price_tc - TC_RESERVE)
    marginal_s = _yield_seconds(snap, lam or {}, SHATTER_TC_GAIN_PER_RR, 1)
    tc_value_s, tc_mode = tc_opportunity_s(snap, lam)
    value = marginal_s * expected_shatters - price_tc * tc_value_s
    return {
        "rrValueS": round(value, 2),
        "marginalPerShatterS": round(marginal_s, 4),
        "expectedShatters": round(expected_shatters, 1),
        "priceTc": price_tc,
        "tcValueS": round(tc_value_s, 2),
        "tcValueMode": tc_mode,
        "level": int(u.get("val", 0)),
    }


# ================================================================ 17.3 Furnace-Wert

def furnace_value(snap: dict, lam: dict[str, float] | None,
                  horizon: float) -> dict | None:
    """FurnaceValue = AvoidedIdleTime + AdditionalBatchValue − Cost_time
    (Spec 17.3). None ohne blastFurnace-Eintrag im Snapshot.

    - AvoidedIdleTime: Heat-blockierte Shatter müssen auf den Heat-Abbau
      warten (heatPerTick 0.01 Basis + 0.02 je Furnace, time.js:161-169);
      eine weitere Furnace verkürzt die Wartezeit je blockiertem Shatter um
      heatPerShatter × (1/rate_alt − 1/rate_neu) Realsekunden.
    - AdditionalBatchValue: +100 heatMax je Furnace (time.js:341) schaltet
      sofort +100/heatPerShatter Shatter frei — bewertet mit dem λ-RR-Ertrag
      je Shatter, gedeckelt auf die tatsächlich blockierten Shatter.
    - Cost_time: Effektivpreise aus dem Snapshot × λ (shadow.cost_time).
    """
    bf = _cfu(snap, "blastFurnace")
    if bf is None:
        return None
    time_state = _time(snap)
    heat = float(time_state.get("heat", 0) or 0)
    heat_max = float(time_state.get("heatMax", 0) or 0)
    hps = heat_per_shatter(snap)
    stock = A.res_value(snap, "timeCrystal")
    desired = min(max(0.0, stock - TC_RESERVE), float(SHATTER_BATCH_SEARCH_MAX))
    headroom = max(0.0, heat_max - heat) / hps
    blocked = max(0.0, desired - headroom)
    tps = _tps(snap)
    n = int(bf.get("val", 0))
    rate_old = (BASE_HEAT_PER_TICK + FURNACE_HEAT_PER_TICK * n) * tps
    rate_new = rate_old + FURNACE_HEAT_PER_TICK * tps
    avoided_idle_s = blocked * hps * (1.0 / rate_old - 1.0 / rate_new)
    per_shatter_s = _yield_seconds(
        snap, lam or {}, SHATTER_TC_GAIN_PER_RR * rr_level(snap), 1)
    extra_shatters = min(blocked, FURNACE_HEAT_MAX / hps)
    batch_value_s = extra_shatters * per_shatter_s
    cost_s = shadow.cost_time(bf.get("prices", []), lam or {})
    value = avoided_idle_s + batch_value_s - cost_s
    return {
        "furnaceValueS": round(value, 2),
        "avoidedIdleS": round(avoided_idle_s, 2),
        "additionalBatchS": round(batch_value_s, 2),
        "costS": round(cost_s, 2),
        "blockedShatters": round(blocked, 1),
    }


# ================================================================ Cycle-Bewertung

def cycle_bonus_s(snap: dict, cycle_idx: int, lam: dict[str, float],
                  horizon: float) -> float:
    """λ-bewerteter Zusatzertrag eines Cycles über den Horizont.

    Referenztabelle CYCLE_RATE_EFFECTS (calendar.js:55-218). Dokumentierte
    Näherung: der Multiplikator wirkt auf die GESAMTE beobachtete Netto-Rate
    der Ressource (Obergrenze — der Snapshot trennt die Gebäudeanteile
    nicht), und nur wenn das Space-Gebäude tatsächlich steht (val ≥ 1)."""
    if not (0 <= cycle_idx < len(CYCLES)) or not lam:
        return 0.0
    total = 0.0
    for bld, res, mult in CYCLE_RATE_EFFECTS[CYCLES[cycle_idx]]:
        if _space_building_val(snap, bld) < 1:
            continue
        lam_i = lam.get(res, 0.0)
        rate = A.res_rate(snap, res)
        if lam_i <= 0.0 or rate <= EPS:
            continue
        total += (mult - 1.0) * rate * lam_i * horizon
    return total


# ================================================================ Paragon-Wert

def paragon_value_s(snap: dict, lam: dict[str, float] | None,
                    horizon: float) -> float:
    """Zustandsabhängiger Sekundenwert EINES Paragon-Punkts (#43).

    Paragon wirkt als Produktionsmultiplikator auf jede Rate (game.js
    calcResourcePerTick:3282-3287, ×(1+getParagonProductionRatio)). Der
    Wert eines weiteren Punkts ist der Ratenzuwachs der λ-bewerteten
    Produktion über den Horizont:

        Δratio/(1+ratio_now) × Σ_i λ_i·rate_i × H

    mit Δratio aus dem Port prestige.paragon_production_ratio (LimitedDR-
    Kappe inklusive — nahe der 2.0-Kappe ist ein Paragon ehrlich fast
    wertlos). Die beobachteten Raten enthalten (1+ratio_now) bereits,
    daher die Normierung. 0.0 ohne λ-bewertete Produktion — der Aufrufer
    (Regel D) fällt dann auf PARAGON_VALUE_REF_S zurück."""
    lam = lam or {}
    prod_s = 0.0
    for r in snap.get("resources", []):
        lam_i = lam.get(r["name"], 0.0)
        rate = r.get("perSec", 0.0)
        if lam_i > 0.0 and rate > EPS:
            prod_s += lam_i * rate
    if prod_s <= EPS:
        return 0.0
    p = snap.get("prestige", {})
    paragon = float(p.get("paragon", 0) or 0)
    burned = float(p.get("burnedParagon", 0) or 0)
    ratio_now = prestige.paragon_production_ratio(paragon, burned)
    ratio_new = prestige.paragon_production_ratio(paragon + 1.0, burned)
    return (ratio_new - ratio_now) / (1.0 + ratio_now) * prod_s * horizon


# ================================================================ 17.5 Shatter-Regeln

def _max_batch(snap: dict) -> int:
    """Harte Batch-Obergrenze: Heat-Spielraum (kein Überhitzen — die
    +1 %/Heat-Preisstrafe, time.js penaltyPerHeat, wird nie bezahlt),
    TC-Bestand über der Reserve, Suchbudget."""
    time_state = _time(snap)
    heat = float(time_state.get("heat", 0) or 0)
    heat_max = float(time_state.get("heatMax", 0) or 0)
    if heat_max <= 0:
        return 0
    headroom = int((heat_max - heat) // heat_per_shatter(snap))
    tc_room = int(A.res_value(snap, "timeCrystal") - TC_RESERVE)
    return max(0, min(headroom, tc_room, SHATTER_BATCH_SEARCH_MAX))


def _rule_a(snap: dict, lam: dict[str, float], max_batch: int
            ) -> tuple[int, dict] | None:
    """Regel A: erwarteter Gesamt-Rückfluss > eingesetztes TC-Äquivalent.
    Deterministische Batch-Suche 1..N über den kumulativ Cap-geklemmten
    RR-Ertrag (konkav) minus λ-bewertete TC-Kosten; kleinster Batch bei
    Gleichstand (strikte Verbesserung nötig)."""
    gain = SHATTER_TC_GAIN_PER_RR * rr_level(snap)
    if gain <= 0:
        return None
    tc_cost_s = TC_PRICE_PER_SHATTER * _lam_tc(lam)
    best_value, best_batch = 0.0, 0
    for batch in range(1, max_batch + 1):
        value = _yield_seconds(snap, lam, gain, batch) - batch * tc_cost_s
        if value > best_value + EPS:
            best_value, best_batch = value, batch
    if best_batch < 1:
        return None
    return best_batch, {"valueS": round(best_value, 2),
                        "yieldPerYearS": round(_yield_seconds(snap, lam, gain, 1), 2),
                        "tcCostPerYearS": round(tc_cost_s, 2)}


def _rule_b(snap: dict, lam: dict[str, float], max_batch: int,
            horizon: float) -> tuple[int, dict] | None:
    """Regel B: Cycle-Positionierung — Shatter zum Cycle mit höherem
    Planwert, wenn der λ-Gewinn die Sprungkosten übersteigt (Referenztabelle
    calendar.js). Deterministisch: bester Netto-Gewinn, Tie-Break kleinere
    Jahre, dann Cycle-Reihenfolge."""
    cal = snap.get("calendar", {})
    cycle = int(cal.get("cycle", 0) or 0) % CYCLES_PER_ERA
    cycle_year = int(cal.get("cycleYear", 0) or 0)
    current = cycle_bonus_s(snap, cycle, lam, horizon)
    tc_cost_s = TC_PRICE_PER_SHATTER * _lam_tc(lam)
    best: tuple[float, int, int] | None = None   # (−gain, years, idx)
    for idx in range(CYCLES_PER_ERA):
        if idx == cycle:
            continue
        years = ((idx - cycle) % CYCLES_PER_ERA) * YEARS_PER_CYCLE - cycle_year
        if years < 1 or years > max_batch:
            continue
        gain = cycle_bonus_s(snap, idx, lam, horizon) - current - years * tc_cost_s
        if gain <= EPS:
            continue
        key = (-gain, years, idx)
        if best is None or key < best:
            best = key
    if best is None:
        return None
    neg_gain, years, idx = best
    return years, {"valueS": round(-neg_gain, 2), "targetCycle": CYCLES[idx],
                   "fromCycle": CYCLES[cycle]}


def _rule_c(snap: dict, max_batch: int) -> tuple[int, dict] | None:
    """Regel C: eine Challenge verlangt den Zeitsprung — 1000 Years
    (Ziel Jahr 1000 per Shatter, time.js:727-730, challenge.py-Profil)."""
    act = challenge.active_challenge(snap)
    if act is None or act.get("name") != "1000Years":
        return None
    year = int(snap.get("calendar", {}).get("year", 0) or 0)
    years_needed = max(1, 1000 - year)
    batch = min(max_batch, years_needed)
    if batch < 1:
        return None
    return batch, {"valueS": 0.0, "challenge": "1000Years",
                   "yearsToGoal": years_needed}


def _rule_d(snap: dict, lam: dict[str, float] | None, max_batch: int,
            horizon: float) -> tuple[int, dict] | None:
    """Regel D: Paragon aus Jahren > TC-Verbrauch. Reset-Paragon enthält
    floor(year/1000) (Anhang D) — der Sprung über die nächste 1000er-Grenze
    bringt +1 Paragon; er lohnt, wenn der zustandsabhängige Paragon-Wert
    (paragon_value_s, #43; Fallback PARAGON_VALUE_REF_S ohne λ-bewertete
    Produktion) die TC-Kosten zum Opportunitätswert (tc_opportunity_s)
    übersteigt."""
    year = int(snap.get("calendar", {}).get("year", 0) or 0)
    years_to_boundary = YEARS_PER_PARAGON - (year % YEARS_PER_PARAGON)
    if years_to_boundary > max_batch:
        return None
    paragon_s = paragon_value_s(snap, lam, horizon)
    if paragon_s <= EPS:
        paragon_s = PARAGON_VALUE_REF_S
    tc_value_s, tc_mode = tc_opportunity_s(snap, lam)
    cost_s = years_to_boundary * TC_PRICE_PER_SHATTER * tc_value_s
    value = paragon_s - cost_s
    if value <= EPS:
        return None
    return years_to_boundary, {"valueS": round(value, 2),
                               "paragonGain": 1,
                               "paragonValueS": round(paragon_s, 2),
                               "tcValueMode": tc_mode,
                               "tcCostS": round(cost_s, 2)}


def shatter_decision(snap: dict, lam: dict[str, float] | None,
                     horizon: float | None = None
                     ) -> tuple[int, str, dict] | None:
    """Shatter-Aktionsregel (Spec 17.5): Regeln A–D in fester Reihenfolge,
    Batchgröße maximiert unter Heat-/Cap-Constraints (siehe _max_batch,
    _rule_a). Rückgabe (batch, rule, detail) oder None (kein Shatter).

    Fallback: ohne Time-Daten (heatMax fehlt) None — der Aufrufer nutzt
    dann die alte konservative Regel bzw. lässt Shatter aus."""
    if not has_time_data(snap):
        return None
    max_batch = _max_batch(snap)
    if max_batch < 1:
        return None
    lam = lam or {}
    horizon = horizon if horizon is not None else 600.0
    if lam:
        hit = _rule_a(snap, lam, max_batch)
        if hit:
            return hit[0], "A", hit[1]
        hit = _rule_b(snap, lam, max_batch, horizon)
        if hit:
            return hit[0], "B", hit[1]
    hit = _rule_c(snap, max_batch)
    if hit:
        return hit[0], "C", hit[1]
    hit = _rule_d(snap, lam, max_batch, horizon)
    if hit:
        return hit[0], "D", hit[1]
    return None
