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
# Untergrenze des GEPLANTEN Reset-Horizonts (#39, Spec 10.4/6.4): steht ein
# Reset unmittelbar bevor (etaSeconds ≈ 0), darf der Payback-Horizont nicht
# auf null kollabieren (jeder Kauf würde abgelehnt → Deadlock-Gefahr) —
# Anti-Deadlock-Floor analog reset.RESET_VALUE_T_MIN. Nach OBEN ist die
# echte Projektion bewusst UNGEKLEMMT: „Horizont mindestens ein voller
# Run" (6.4) heißt, lange Runs planen lang — die 4-h-Klemme gilt nur für
# die Heuristik run_horizon (Fallback ohne Projektion).
HORIZON_PLANNED_MIN = 600.0

# Spielzeit-Konstanten (wie state/derived.py): 1 Tag = 2 s.
SECONDS_PER_DAY = 2.0

# Basisproduktion pro Job und Sekunde — NUR NOCH FALLBACK (#40): die
# maßgebliche Quelle sind die beobachteten Marginalraten `ratesPerKitten`
# aus dem Snapshot (siehe job_marginal_rates). Diese Tabelle greift nur,
# wenn der Snapshot das Feld nicht liefert (alter Driver, Sektion-Fehler).
# Werte aus village.js der Referenzversion 1.5.0.2, pro Tick × 5 Ticks/s,
# VOR Gebäude-/Upgrade-Multiplikatoren; skaliert dann nur mit Happiness:
JOB_BASE_RATES: dict[str, dict[str, float]] = {
    "farmer": {"catnip": 5.0},          # 1 / Tick
    "woodcutter": {"wood": 0.09},       # 0.018 / Tick
    "miner": {"minerals": 0.25},        # 0.05 / Tick
    "scholar": {"science": 0.175},      # 0.035 / Tick
    "hunter": {"manpower": 0.3},        # 0.06 / Tick
    "geologist": {"coal": 0.075},       # 0.015 / Tick (Gold erst mit Upgrades)
    "priest": {"faith": 0.0075},        # 0.0015 / Tick
}


def job_marginal_rates(snap: dict, job_id: str) -> dict[str, float]:
    """Effektive Marginalrate PRO KITTEN und Sekunde für einen Job (#40).

    Maßgeblich ist das Snapshot-Feld `ratesPerKitten` (snapshot.js,
    Nachbau von village.js updateResourceProduction × game.js
    calcResourcePerTick für ein marginales Skill-0-Kitten) — es enthält
    Happiness, Leader-Team-Boost und alle Produktions-Multiplikatoren
    BEREITS. Ein vorhandenes, auch leeres Feld ist autoritativ (Jobs ohne
    Tick-Produktion wie engineer liefern ehrlich {}). Nur wenn das Feld
    fehlt (alter Driver / Sektion-Fehler), fällt die Bewertung auf
    JOB_BASE_RATES × Happiness zurück — Aufrufer dürfen das Ergebnis
    deshalb NICHT erneut mit Happiness multiplizieren."""
    happiness = snap.get("village", {}).get("happiness", 1.0) or 1.0
    for j in snap.get("village", {}).get("jobs", []):
        if j.get("name") != job_id:
            continue
        observed = j.get("ratesPerKitten")
        if isinstance(observed, dict):
            return {res: float(rate) for res, rate in observed.items()
                    if isinstance(rate, (int, float))}
        break
    base = JOB_BASE_RATES.get(job_id)
    if not base:
        return {}
    return {res: rate * happiness for res, rate in base.items()}


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


# ================================================================ λ (Kern)

def _single_lambda(snap: dict, prices: list[dict], *, rate: bool) -> dict[str, float]:
    """λ-Vektor EINES Preisvektors, ohne Kaskade (Kern von shadow_prices/
    rate_shadow_prices — bitidentisches Verhalten, nur faktorisiert für
    die Pfad-Kombination). rate=False: Mengen-λ (s/Einheit, Störterm
    +1 Einheit); rate=True: Raten-λ (s pro Einheit/s, Störterm +ε Rate).
    Sonderfälle wie dokumentiert: gedeckt→0, Cap-Block→0, Rate≈0→Clamp,
    fremdblockierte Position→0."""
    lam: dict[str, float] = {}
    lam_max = LAMBDA_RATE_MAX if rate else LAMBDA_MAX
    base = _eta(snap, prices)
    for p in prices:
        name = p["name"]
        if A.res_value(snap, name) + EPS >= p["val"]:
            lam[name] = 0.0
            continue
        cap = A.res_cap(snap, name)
        if 0 < cap < p["val"]:
            lam[name] = 0.0
            continue
        if A.res_rate(snap, name) <= RATE_EPS:
            # Nichts produziert die Ressource — jede Einheit/Produktion ist
            # maximal wertvoll, endlich geklemmt:
            lam[name] = lam_max
            continue
        if not math.isfinite(base):
            # Eine ANDERE Position blockiert das Ziel — diese hier ist
            # (noch) nicht der Engpass:
            lam[name] = 0.0
            continue
        if rate:
            delta = base - _eta(snap, prices, extra_rate={name: RATE_PROBE_EPS})
            lam[name] = _clamp(delta / RATE_PROBE_EPS, 0.0, lam_max)
        else:
            delta = base - _eta(snap, prices, extra_amount={name: 1.0})
            lam[name] = _clamp(delta, 0.0, lam_max)
    return lam


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
    lam = _single_lambda(snap, goal_prices, rate=False)
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
    lam_rate = _single_lambda(snap, goal_prices, rate=True)
    _propagate_cascade(snap, lam_rate)
    return lam_rate


def shadow_price_of_rate(snap: dict, goal_prices: list[dict] | None,
                         res_id: str) -> float:
    """Raten-Schattenpreis einer einzelnen Ressource (inkl. Kaskade)."""
    return rate_shadow_prices(snap, goal_prices).get(res_id, 0.0)


# ================================================================ λ (Pfad)

def path_weight(rank: int) -> float:
    """Rang-Diskont des Pfad-Preisvektors: w_k = 1/(1+k) (Spec 10.2/11.1,
    „nähere Ziele wiegen mehr").

    Wahl dokumentiert (#34): ETA-basierte Diskontierung wäre endogen
    (λ steuert das Verhalten, das Verhalten ändert die ETA → Rückkopplung/
    Flattern) und für noch unsichtbare Ziele gar nicht definiert. Die
    Meilenstein-Reihenfolge ist dagegen ein deterministischer, snapshot-
    stabiler Zeit-Proxy. Harmonisch (1/(1+k)) statt geometrisch, damit
    Ressourcen weit hinten im Pfad nicht auf ≈0 fallen — Totalentwertung
    von Pfadressourcen ist genau die Fehlerklasse der Live-Funde
    (Null-Woodcutter, Monokultur)."""
    return 1.0 / (1.0 + max(0, rank))


def _path_lambda(snap: dict, path_targets: list[dict], *, rate: bool) -> dict[str, float]:
    """Kombinierter Pfad-λ-Vektor: λ_i = max_k(w_k · λ_i^(k)).

    Diskontiertes MAXIMUM statt Summe (Wahl dokumentiert, #34): λ ist die
    marginale ETA-Verkürzung EINES Ziels durch +1 Einheit; die Meilensteine
    sind sequenziell — dieselbe marginale Einheit wird von genau einem Ziel
    verbraucht. Eine Summe würde sie allen ~20 Zielen gleichzeitig
    gutschreiben (Science würde absurd aufgebläht) und das LAMBDA_MAX-Clamp
    sprengen; das Maximum bleibt automatisch in [0, Clamp]. Die Kaskade
    läuft EINMAL über das kombinierte Maximum (billiger, und Craft-Inputs
    erben so den besten Pfadwert)."""
    combined: dict[str, float] = {}
    for entry in path_targets:
        prices = entry.get("prices")
        if not prices:
            continue
        w = float(entry.get("weight", 1.0))
        if w <= 0:
            continue
        lam_k = _single_lambda(snap, prices, rate=rate)
        for name, val in lam_k.items():
            weighted = w * val
            if weighted > combined.get(name, 0.0):
                combined[name] = weighted
    _propagate_cascade(snap, combined)
    return combined


def path_shadow_prices(snap: dict, path_targets: list[dict]) -> dict[str, float]:
    """Mengen-λ über den PFAD (aktives Ziel + offene Meilensteine + Housing,
    Spec 10.2/11.1 — Lücke #34): Einträge {"prices": [...], "weight": w}."""
    if not path_targets:
        return {}
    return _path_lambda(snap, path_targets, rate=False)


def path_rate_shadow_prices(snap: dict, path_targets: list[dict]) -> dict[str, float]:
    """Raten-λ über den PFAD (Gegenstück zu path_shadow_prices)."""
    if not path_targets:
        return {}
    return _path_lambda(snap, path_targets, rate=True)


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

    Die Marginalrate je Job kommt aus job_marginal_rates (#40): beobachtete
    ratesPerKitten aus dem Snapshot (inkl. Happiness, Leader-Boost und
    Upgrade-/Gebäude-Multiplikatoren), Fallback JOB_BASE_RATES × Happiness.
    """
    rates = job_marginal_rates(snap, job_id)
    if not rates or not lam_rate:
        return 0.0
    total = 0.0
    for res, rate in rates.items():
        # Cap-Klausel (Spec 11.1): Produktion in eine VOLLE Ressource läuft
        # ins Cap und ist wertlos — Grenzwert 0 (Live-Fund: beide Kitten
        # Scholars bei Science am Cap).
        cap = A.res_cap(snap, res)
        if cap > 0 and A.res_value(snap, res) >= cap * CAP_FULL_RATIO:
            continue
        total += lam_rate.get(res, 0.0) * rate
    return total


# ================================================================ Soll-Allokation (12.2)

# Deterministische Job-Reihenfolge der Allokation (Tie-Break):
ALLOC_JOB_ORDER = ("farmer", "woodcutter", "scholar", "miner",
                   "hunter", "geologist", "priest")


# Totzeit-Referenz der Allokation: eine Zielressource ohne jede Produktion
# zählt wie eine Stunde Engpass. Die Sättigung in _alloc_eta hält jeden
# Posten unterhalb dieser Schranke — hoffnungslose Einträge können die
# Summe nie dominieren, geben aber (streng monoton) weiterhin einen
# kleinen Gewinn je zusätzlichem Kitten ab.
ALLOC_DEAD_ETA_S = 3600.0

# Mindestgewinn (Sekundensumme) für eine Greedy-Zuweisung — filtert
# numerisches Rauschen, damit „praktisch kein Gewinn" in die Stickiness-
# Restverteilung fällt statt Kitten zu verschieben.
ALLOC_GAIN_EPS = 1.0


def _alloc_eta(prices: list[dict], amounts: dict, rates: dict) -> float:
    """Gewichtete Engpass-Zeitsumme Σ wᵢ·sat(ETAᵢ) der Allokation, mit
    Sättigung sat(η) = Totzeit·η/(η+Totzeit).

    SUMME statt Maximum, damit kein einzelner (z. B. unbeeinflussbarer)
    Posten alle übrigen Verbesserungen maskiert — der Greedy in
    target_allocation vergibt jedes Kitten an die größte Senkung dieser
    Summe. Die Sättigung statt eines harten min(η, Totzeit): nahe Ziele
    zählen praktisch als ihre ETA (η ≪ Totzeit → sat ≈ η), tote
    Ressourcen (keine Rate, η = ∞) als volle Totzeit, und GROSSE Ziele
    (η > Totzeit selbst MIT Kitten — Live-Fund: 2750er-Science-Ziel)
    geben weiterhin einen streng monotonen Gewinn je weiterem Kitten ab;
    ein harter Deckel machte diesen Gewinn exakt 0 und kein Scholar wurde
    je zugeteilt. Hoffnungslose Posten bleiben durch die Schranke klein
    und werden zusätzlich von ALLOC_GAIN_EPS gefiltert. Optionales
    "weight" je Eintrag (Pfadziele, tactics._allocation_prices)
    diskontiert ferne Ziele wie beim Pfad-λ."""
    total = 0.0
    for p in prices:
        missing = p["val"] - amounts.get(p["name"], 0.0)
        if missing <= 0:
            continue
        r = rates.get(p["name"], 0.0)
        if r > RATE_EPS:
            eta = missing / r
            sat = ALLOC_DEAD_ETA_S * eta / (eta + ALLOC_DEAD_ETA_S)
        else:
            sat = ALLOC_DEAD_ETA_S
        total += p.get("weight", 1.0) * sat
    return total


def target_allocation(snap: dict, goal_prices: list[dict] | None,
                      min_farmers: int = 0) -> dict[str, int]:
    """Soll-Jobverteilung nach Spec 12.2 (iterativ, deterministisch):

    1. min_farmers (Food-Invariante I-01) werden vorab reserviert.
    2. Jedes weitere Kitten geht an den Job mit dem größten marginalen
       Zielzeitgewinn; nach jeder Zuweisung werden die angenommenen Raten
       aktualisiert (dadurch fallende Grenzwerte — kein Alle-auf-einen-Job).
    3. Bleibt kein positiver Grenzwert (Ziel bezahlbar/gedeckt), werden
       restliche Kitten round-robin auf Jobs ohne volle Ertragsressource
       verteilt (Balance statt Leerlauf).

    Basisraten: beobachtete Raten MINUS aktuelle Kitten-Beiträge — die
    Allokation plant, als wären alle Kitten neu verteilbar. Die Beiträge
    kommen aus job_marginal_rates (#40): mit beobachteten ratesPerKitten
    ist die Subtraktion exakt (früher wurden statische Basisraten von
    multiplikator-behafteten Ist-Raten abgezogen — Phantom-Restrate).
    Leeres goal_prices → {} (Aufrufer nutzt den bisherigen Fallback)."""
    village = snap.get("village", {})
    total = int(village.get("kittens", 0) or 0)
    if total <= 0 or not goal_prices:
        return {}
    jobs = [j for j in ALLOC_JOB_ORDER if A.job_unlocked(snap, j)]
    if not jobs:
        return {}
    # Marginalraten je Job EINMAL bestimmen (enthalten Happiness bereits):
    jrates = {j: job_marginal_rates(snap, j) for j in jobs}

    def _capped(res: str) -> bool:
        cap = A.res_cap(snap, res)
        return cap > 0 and A.res_value(snap, res) >= cap * CAP_FULL_RATIO

    # Nur Einträge behalten, die ein freigeschalteter Job überhaupt
    # beeinflussen kann und die nicht am Cap kleben — alles andere wäre
    # ein konstanter Term in der Zeitsumme, den kein Kitten senken kann
    # (Cap-Anhebung ist Sache der Gebäudekandidaten, nicht der Jobs).
    producible = {res for j in jobs for res in jrates[j]}
    goal_prices = [p for p in goal_prices
                   if p["name"] in producible and not _capped(p["name"])]
    if not goal_prices:
        return {}

    amounts = {p["name"]: A.res_value(snap, p["name"]) for p in goal_prices}
    rates: dict[str, float] = {}
    for p in goal_prices:
        rates[p["name"]] = A.res_rate(snap, p["name"])
    # Kitten-Beiträge herausrechnen (nur bekannte Job-Ressourcen). Floor
    # bei 0: Verbrauch/Messrauschen kann die Baseline sonst negativ machen,
    # und ein Trial-Kitten hebt sie dann nur auf exakt 0 — die Ressource
    # bliebe „tot", der Fixpunkt hinge vom Ist-Zustand ab (Oszillation).
    # Verbrauchssicherheit (Catnip) ist Sache von min_farmers/Safety, hier
    # zählt die Produktions-ETA.
    for j in jobs:
        count = A.job_count(snap, j)
        for res, rate in jrates[j].items():
            if res in rates:
                rates[res] -= count * rate
    for res in rates:
        rates[res] = max(0.0, rates[res])

    alloc = {j: 0 for j in jobs}
    remaining = total
    if "farmer" in alloc and min_farmers > 0:
        take = min(min_farmers, remaining)
        alloc["farmer"] = take
        remaining -= take
        for res, rate in jrates.get("farmer", {}).items():
            if res in rates:
                rates[res] += take * rate

    for _ in range(remaining):
        base = _alloc_eta(goal_prices, amounts, rates)
        best_job, best_gain = None, ALLOC_GAIN_EPS
        for j in jobs:
            trial = dict(rates)
            touched = False
            for res, rate in jrates.get(j, {}).items():
                if res in trial and not _capped(res):
                    trial[res] += rate
                    touched = True
            if not touched:
                continue
            gain = base - _alloc_eta(goal_prices, amounts, trial)
            if gain > best_gain:
                best_gain, best_job = gain, j
        if best_job is None:
            break   # kein positiver Grenzwert mehr → Rest per Round-Robin
        alloc[best_job] += 1
        for res, rate in jrates.get(best_job, {}).items():
            if res in rates:
                rates[res] += rate
        remaining -= 1

    # Rest-Verteilung mit STICKINESS (Anti-Flattern, Nutzer-Fund): Kitten
    # ohne positiven Grenzwert bleiben bevorzugt in ihren AKTUELLEN Jobs
    # (minimale Bewegung), solange deren Ertrag nicht voll ist; nur ein
    # echter Überhang wird round-robin auf offene Jobs verteilt.
    if remaining > 0:
        open_jobs = [j for j in jobs
                     if not all(_capped(r) for r in jrates.get(j, {}))]
        for j in open_jobs:
            if remaining <= 0:
                break
            keep = min(remaining, max(0, A.job_count(snap, j) - alloc[j]))
            alloc[j] += keep
            remaining -= keep
        i = 0
        while remaining > 0 and open_jobs:
            alloc[open_jobs[i % len(open_jobs)]] += 1
            i += 1
            remaining -= 1
    return alloc
