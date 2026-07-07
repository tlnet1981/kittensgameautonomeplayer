"""Echte Schattenpreise (Spielmechanik-Spec 10.2–10.4, 12.2).

Kernidee: Der Schattenpreis λ_i einer Ressource ist die marginale
Verkürzung der Ziel-ETA durch +1 Einheit dieser Ressource

    λ_i = −∂ ETA(goal) / ∂ R_i        [Sekunden pro Einheit]

und wird hier numerisch über die Engpass-ETA bestimmt (Ziel-ETA = max über
die Preispositionen von fehlend_i / netRate_i, wie access.eta_to_afford).
Damit lassen sich Kosten und Produktionsgewinne in Zielzeitäquivalente
umrechnen (Spec 10.2):

    Cost_time(a)      = Σ_i λ_i · Cost_i(a)
    Benefit_time(a,H) = Σ_i λ_i · ΔRate_i(a) · H + UnlockTimeSaving(a)
    NetValue(a)       = Benefit_time − Cost_time            (Spec 10.3)
    Payback(a)        = Cost_time / max(ε, MarginalTimeSavingRate)  (10.4)

Bewusste Näherungen (dokumentiert statt versteckt):
- Numerische Ableitung statt symbolischer Rekursion über den vollen
  Abhängigkeitsgraphen; Nicht-Zielressourcen erben λ über die
  Craft-Kaskade (Input ← Produkt, gedämpft mit dem Umrechnungsverhältnis).
- Cap-gesperrte Preispositionen erhalten λ = 0: zusätzliche Einheiten
  helfen dort nicht, Storage ist der Fix (Storage-Regel 11.3 A).
- Ressourcen ganz ohne Produktion (Rate ≈ 0) erhalten das endliche Clamp
  LAMBDA_MAX statt ∞ — jede Einheit ist wertvoll, aber vergleichbar.
"""

from __future__ import annotations

import math

from player.state import access as A

EPS = 1e-9
RATE_EPS = 1e-7          # wie access.RATE_EPS: darunter gilt Rate = 0
RATE_PROBE_EPS = 1e-3    # ε für die numerische Raten-Ableitung

# Endliche Clamps statt unendlicher Schattenpreise (Cap-/Rate-0-Fälle):
LAMBDA_MAX = 3600.0             # s pro Einheit
LAMBDA_RATE_MAX = 4 * 3600.0    # s pro (Einheit/s)

# Ab diesem Füllstand gilt eine Ressource als „voll": weitere Produktion
# läuft ins Cap und ist wertlos (Spec 11.1, Cap-Klausel im JobScore).
CAP_FULL_RATIO = 0.975

# Craft-Kaskade (wie tactics._craft_toward): maximale Rekursionstiefe.
CASCADE_MAX_DEPTH = 4

# „Refine catnip" (Bonfire) ist kein Workshop-Craft, aber die früheste
# Konversion der Kaskade: 100 Catnip → 1 Wood.
REFINE_RECIPES: dict[str, list[dict]] = {
    "wood": [{"name": "catnip", "val": 100}],
}

# Run-Horizont-Klemmen (siehe run_horizon):
# Untergrenze 30 min: Kein sinnvoller Run endet früher (Speedrun-
# Mindestlaufzeit in reset.py ist 20 min; der FIRST_RUN braucht Stunden).
# Mit 600 s hatte das Payback-Gate 10.4 früh im Run rentable
# Produktionsgebäude (Feld #14: Payback ~770 s) abgelehnt und die
# Catnip-Bank fürs erste Housing massiv verlangsamt (E2E-Smoke-Fund).
HORIZON_MIN = 1800.0
HORIZON_MAX = 4 * 3600.0

# Spielzeit-Konstanten (wie state/derived.py): 1 Tag = 2 s.
SECONDS_PER_DAY = 2.0

# Basisproduktion pro Job und Sekunde (Näherung! Werte aus village.js der
# Referenzversion 1.5.0.2, pro Tick × 5 Ticks/s, VOR Gebäude-/Upgrade-
# Multiplikatoren; skaliert nur mit Happiness — siehe job_score):
JOB_BASE_RATES: dict[str, dict[str, float]] = {
    "farmer": {"catnip": 5.0},          # 1 / Tick
    "woodcutter": {"wood": 0.09},       # 0.018 / Tick
    "miner": {"minerals": 0.25},        # 0.05 / Tick
    "scholar": {"science": 0.175},      # 0.035 / Tick
    "hunter": {"manpower": 0.3},        # 0.06 / Tick
    "geologist": {"coal": 0.075},       # 0.015 / Tick (Gold erst mit Upgrades)
    "priest": {"faith": 0.0075},        # 0.0015 / Tick
}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# ================================================================ Ziel-ETA

def _eta(snap: dict, prices: list[dict],
         extra_amount: dict[str, float] | None = None,
         extra_rate: dict[str, float] | None = None) -> float:
    """Ziel-ETA = max über Preispositionen von fehlend/Rate (Spec 10.1).

    Wie access.eta_to_afford, aber mit Störtermen für die numerische
    Ableitung: extra_amount hebt den Bestand, extra_rate die Netto-Rate
    einzelner Ressourcen an. math.inf bei Cap-Block oder Rate ≤ 0.
    """
    worst = 0.0
    for p in prices:
        have = A.res_value(snap, p["name"]) + (extra_amount or {}).get(p["name"], 0.0)
        missing = p["val"] - have
        if missing <= EPS:
            continue
        cap = A.res_cap(snap, p["name"])
        if 0 < cap < p["val"]:
            return math.inf                     # Cap blockiert das Ziel (11.3 A)
        rate = A.res_rate(snap, p["name"]) + (extra_rate or {}).get(p["name"], 0.0)
        if rate <= RATE_EPS:
            return math.inf
        worst = max(worst, missing / rate)
    return worst


# ================================================================ λ (Menge)

def shadow_prices(snap: dict, goal_prices: list[dict] | None) -> dict[str, float]:
    """Schattenpreis λ_i in Sekunden pro Einheit für das aktive Ziel.

    Für jede Ressource im Preisvektor: λ ≈ ETA(goal) − ETA(goal | R_i + 1).
    Sonderfälle:
    - Position bereits gedeckt → λ = 0
    - Cap blockiert die Position → λ = 0 (Storage hilft, nicht mehr Einheiten)
    - Rate ≈ 0 (nichts produziert die Ressource) → λ = LAMBDA_MAX (Clamp)
    Nicht-Zielressourcen erben λ über die Craft-Kaskade (siehe
    _propagate_cascade); alles andere hat λ = 0 (fehlt im Dict).
    """
    if not goal_prices:
        return {}
    lam: dict[str, float] = {}
    base = _eta(snap, goal_prices)
    for p in goal_prices:
        name = p["name"]
        if A.res_value(snap, name) + EPS >= p["val"]:
            lam[name] = 0.0
            continue
        cap = A.res_cap(snap, name)
        if 0 < cap < p["val"]:
            lam[name] = 0.0
            continue
        if A.res_rate(snap, name) <= RATE_EPS:
            lam[name] = LAMBDA_MAX
            continue
        if not math.isfinite(base):
            # Eine ANDERE Position blockiert das Ziel — diese hier ist
            # (noch) nicht der Engpass:
            lam[name] = 0.0
            continue
        delta = base - _eta(snap, goal_prices, extra_amount={name: 1.0})
        lam[name] = _clamp(delta, 0.0, LAMBDA_MAX)
    _propagate_cascade(snap, lam)
    return lam


# ================================================================ λ (Rate)

def rate_shadow_prices(snap: dict, goal_prices: list[dict] | None) -> dict[str, float]:
    """Raten-Schattenpreis λ_rate_i in Sekunden pro (Einheit/s).

    λ_rate ≈ (ETA(goal) − ETA(goal | Rate_i + ε)) / ε — der Zielzeitgewinn
    einer dauerhaften Produktionssteigerung. Grundlage für Job- und
    Gebäudebewertung (Spec 12.2 / 10.2). Kaskade wie bei shadow_prices.
    """
    if not goal_prices:
        return {}
    lam_rate: dict[str, float] = {}
    base = _eta(snap, goal_prices)
    for p in goal_prices:
        name = p["name"]
        if A.res_value(snap, name) + EPS >= p["val"]:
            lam_rate[name] = 0.0
            continue
        cap = A.res_cap(snap, name)
        if 0 < cap < p["val"]:
            lam_rate[name] = 0.0
            continue
        if A.res_rate(snap, name) <= RATE_EPS:
            # Nichts produziert die Ressource — jede Produktion ist maximal
            # wertvoll, endlich geklemmt:
            lam_rate[name] = LAMBDA_RATE_MAX
            continue
        if not math.isfinite(base):
            lam_rate[name] = 0.0
            continue
        delta = base - _eta(snap, goal_prices, extra_rate={name: RATE_PROBE_EPS})
        lam_rate[name] = _clamp(delta / RATE_PROBE_EPS, 0.0, LAMBDA_RATE_MAX)
    _propagate_cascade(snap, lam_rate)
    return lam_rate


def shadow_price_of_rate(snap: dict, goal_prices: list[dict] | None,
                         res_id: str) -> float:
    """Raten-Schattenpreis einer einzelnen Ressource (inkl. Kaskade)."""
    return rate_shadow_prices(snap, goal_prices).get(res_id, 0.0)


# ================================================================ Kaskade

def _propagate_cascade(snap: dict, lam: dict[str, float]) -> dict[str, float]:
    """Vererbt λ vom Craftprodukt auf seine Inputs, gedämpft mit dem
    Umrechnungsverhältnis: λ_input = λ_produkt / Inputmenge (Craft Ratio
    bewusst ignoriert — konservative Dämpfung). Mehrere Pfade → max().
    Deterministisch: Ergebnis ist der Fixpunkt der max-Propagation.
    """
    frontier = [(name, val, 0) for name, val in sorted(lam.items()) if val > 0]
    while frontier:
        name, val, depth = frontier.pop()
        if depth >= CASCADE_MAX_DEPTH:
            continue
        recipe = A.craft_recipe(snap, name)
        prices = recipe["prices"] if recipe else REFINE_RECIPES.get(name)
        if not prices:
            continue
        for q in prices:
            if q["val"] <= 0:
                continue
            derived = val / q["val"]
            if derived > lam.get(q["name"], 0.0) + EPS:
                lam[q["name"]] = derived
                frontier.append((q["name"], derived, depth + 1))
    return lam


# ================================================================ Zeitwerte

def cost_time(prices: list[dict], lam: dict[str, float]) -> float:
    """Cost_time(a) = Σ λ_i · Kosten_i — Kaufkosten in Ziel-Sekunden."""
    if not prices or not lam:
        return 0.0
    return sum(lam.get(p["name"], 0.0) * p["val"] for p in prices)


def benefit_time(rate_delta: dict[str, float], lam: dict[str, float],
                 horizon: float, unlock_bonus: float = 0.0) -> float:
    """Benefit_time(a,H) = Σ λ_i · ΔRate_i · H (+ unlock_bonus), Spec 10.2.

    λ ist der Mengen-Schattenpreis (s/Einheit): ΔRate·H zusätzliche
    Einheiten über den Horizont, jede λ Sekunden wert. Heuristik — der
    tatsächliche Gewinn ist durch die Rest-ETA begrenzt; der Aufrufer
    normiert das Ergebnis (tactics._score).
    """
    total = unlock_bonus
    if rate_delta and lam:
        total += sum(lam.get(res, 0.0) * dr * horizon
                     for res, dr in rate_delta.items())
    return total


def net_value(benefit_t: float, cost_t: float) -> float:
    """NetValue = Benefit_time − Cost_time (Kaufregel 10.3)."""
    return benefit_t - cost_t


def payback(cost_t: float, marginal_saving_rate: float) -> float:
    """Payback(a) = Cost_time / max(ε, MarginalTimeSavingRate) (Spec 10.4).

    marginal_saving_rate in „gesparte Ziel-Sekunden pro Sekunde"
    (= Σ λ_i · ΔRate_i). Ohne Ersparnis: math.inf.
    """
    if cost_t <= EPS:
        return 0.0
    if marginal_saving_rate <= EPS:
        return math.inf
    return cost_t / marginal_saving_rate


# ================================================================ Horizont

def run_horizon(snap: dict) -> float:
    """Erwartete Restlaufzeit des Runs in Sekunden (für Payback-Gate 10.4).

    Wahl der Heuristik: Der Snapshot enthält keine Verlaufsdaten (die
    paragon_samples aus reset.py leben im Brain, nicht im Snapshot), aber
    der Kalender misst die bisherige Run-Spielzeit exakt (Reset setzt ihn
    auf null; 1 Tag = 2 s wie in state/derived.py). Konservative Annahme
    analog zur Speedrun-Mindestlaufzeit in reset.py: Der Run läuft noch
    etwa 2× so lange, wie er bereits gedauert hat — junge Runs planen
    kurz, reife Runs weit. Geklemmt auf [30 min, 4 h] (Untergrenze siehe
    HORIZON_MIN: Spec 10.4 verlangt Amortisation vor dem GEPLANTEN Reset,
    und kein geplanter Reset liegt früher als die Speedrun-Mindestlaufzeit).
    """
    cal = snap.get("calendar", {})
    days_per_season = float(cal.get("daysPerSeason", 100)) or 100.0
    elapsed = (cal.get("year", 0) * 4 * days_per_season
               + cal.get("season", 0) * days_per_season
               + cal.get("day", 0)) * SECONDS_PER_DAY
    return _clamp(2.0 * elapsed, HORIZON_MIN, HORIZON_MAX)


# ================================================================ Jobs

def job_score(snap: dict, job_id: str, lam_rate: dict[str, float]) -> float:
    """JobScore(j) = Σ λ_rate_i · MarginalRate_i(j) (Spec 12.2) —
    Sekunden Zielzeitgewinn pro Sekunde Arbeit eines weiteren Kittens.

    Näherung: Die Marginalrate je Job stammt aus der Basisraten-Tabelle
    JOB_BASE_RATES (Snapshot liefert nur Netto-perSec, aus der sich der
    Beitrag eines einzelnen Jobs nicht sauber isolieren lässt), skaliert
    mit der Dorf-Happiness. Gebäude-/Upgrade-Multiplikatoren fehlen —
    für den VERGLEICH zwischen Jobs ist das ausreichend genau.
    """
    rates = JOB_BASE_RATES.get(job_id)
    if not rates or not lam_rate:
        return 0.0
    happiness = snap.get("village", {}).get("happiness", 1.0) or 1.0
    total = 0.0
    for res, rate in rates.items():
        # Cap-Klausel (Spec 11.1): Produktion in eine VOLLE Ressource läuft
        # ins Cap und ist wertlos — Grenzwert 0 (Live-Fund: beide Kitten
        # Scholars bei Science am Cap).
        cap = A.res_cap(snap, res)
        if cap > 0 and A.res_value(snap, res) >= cap * CAP_FULL_RATIO:
            continue
        total += lam_rate.get(res, 0.0) * rate * happiness
    return total
