"""Policy-Wahl (Spielmechanik-Spec 13.4 + Invariante I-07).

Policies sind exklusive, irreversible Modifierpakete: wer z. B. Liberty
erforscht, blockiert Tradition für den ganzen Run (science.js:847-849:
„Once policy is blocked, there is no way to unlock it other than reset").
Deshalb gilt Invariante I-07: Eine exklusive Policy DARF nur gewählt
werden, wenn alle ausgeschlossenen Alternativen im Planwert berücksichtigt
wurden — hier: PolicyValue(gewählt) ≥ PolicyValue(Alternative) für jede
Alternative aus dem `blocks`-Vektor, beide über denselben λ-Horizont.

Bewertung (PolicyValue in Ziel-Sekunden, wie shadow.net_value):

    PolicyValue(p) = Benefit_time(ΔRate(p), λ, H) − Cost_time(prices(p), λ)

ΔRate(p) kommt aus der Effekt-Referenztabelle POLICY_EFFECTS unten. Die
Tabelle ist aus gamefiles/js/science.js (policies-Array, Zeilen 850 ff)
abgeleitet; jede Zeile nennt die Quelle. Zwei Effektklassen:

- rate_ratio {res: r}: ±r × aktuelle Produktionsrate der Ressource.
  Exakt, wo das Spiel einen "...PolicyRatio"-Effekt trägt (z. B.
  knowledgeSharing: sciencePolicyRatio 0.05); REFERENZSCHÄTZUNG, wo der
  Spieleffekt nicht direkt eine Rate ist (im Eintrag gekennzeichnet).
- global_ratio g: g × Rate für JEDE Ressource mit λ > 0 — Proxy für
  Happiness-/Global-Effekte (REFERENZSCHÄTZUNG).

Suchraum-Prior (Spec 13.4, „Statische Defaults nur zur Suchraumreduktion"):
POLICY_PRIOR bildet die 13.4-Starttabelle auf unsere Run-Typen ab. Der
Prior wird um die exklusiven Gegenstücke der Kandidaten erweitert — sonst
könnte I-07 die Wahl dauerhaft blockieren, obwohl die (bewertete!)
Alternative die bessere ist.

Fallbacks: ohne `policies`-Sektion im Snapshot, ohne λ-Daten oder ohne
Effekt-Referenz entsteht KEIN Kandidat (Wert 0 → nicht positiv).
"""

from __future__ import annotations

from player.state import access as A

from . import shadow

EPS = 1e-9

# ------------------------------------------------------- Effekt-Referenztabelle
# Quelle: gamefiles/js/science.js, policies-Array (Kittens Game 1.5.0.2 r3).
# "estimate": True = der Spieleffekt ist keine direkte Produktionsrate;
# die rate_ratio-/global_ratio-Übersetzung ist eine dokumentierte
# REFERENZSCHÄTZUNG (ehrlich gekennzeichnet, keine Spielkonstante).
POLICY_EFFECTS: dict[str, dict] = {
    # --- Frühzeit (writing unlocks liberty/tradition, science.js:161) ---
    "liberty": {
        # science.js: happinessKittenProductionRatio 0.1 (+maxKittens 1) —
        # globaler Produktions-Proxy.
        "global_ratio": 0.10, "estimate": True,
        "source": "science.js liberty: happinessKittenProductionRatio 0.1",
    },
    "tradition": {
        # science.js: cultureFromManuscripts +1, manuscriptParchmentCost −5 —
        # als +10 % Culture-Rate geschätzt.
        "rate_ratio": {"culture": 0.10}, "estimate": True,
        "source": "science.js tradition: cultureFromManuscripts 1",
    },
    # --- Klassik (liberty/tradition unlocks, science.js:866/887) ---
    "monarchy": {
        # science.js: goldPolicyRatio −0.1 (exakter Ratensatz).
        "rate_ratio": {"gold": -0.10}, "estimate": False,
        "source": "science.js monarchy: goldPolicyRatio -0.1",
    },
    "republic": {
        # science.js: boostFromLeader 0.01 — kleiner globaler Proxy.
        "global_ratio": 0.01, "estimate": True,
        "source": "science.js republic: boostFromLeader 0.01",
    },
    "authocracy": {
        # science.js: rankLeaderBonusConversion (0.004 × uncapped Housing).
        "global_ratio": 0.005, "estimate": True,
        "source": "science.js authocracy: rankLeaderBonusConversion",
    },
    # --- Foreign Policy (currency unlocks, science.js:149) ---
    "diplomacy": {
        # science.js: tradeCatpowerDiscount 5 (−5 Catpower je Trade) —
        # als +5 % effektive Catpower-Rate geschätzt.
        "rate_ratio": {"manpower": 0.05}, "estimate": True,
        "source": "science.js diplomacy: tradeCatpowerDiscount 5",
    },
    "isolationism": {
        # science.js: tradeGoldDiscount 1 (−1 Gold je Trade) — klein.
        "rate_ratio": {"gold": 0.01}, "estimate": True,
        "source": "science.js isolationism: tradeGoldDiscount 1",
    },
    "zebraRelationsAppeasement": {
        # science.js: zebraRelationModifier +15, goldPolicyRatio −0.05.
        # Zebra-Standing verbessert Titanium-Trades → Titanium-Schätzung.
        "rate_ratio": {"gold": -0.05, "titanium": 0.15}, "estimate": True,
        "source": "science.js zebraRelationsAppeasement: zebraRelationModifier 15, goldPolicyRatio -0.05",
    },
    "zebraRelationsBellicosity": {
        # science.js: nonZebraRelationModifier +5, zebraRelationModifier −10.
        "rate_ratio": {"titanium": -0.10}, "estimate": True,
        "source": "science.js zebraRelationsBellicosity: zebraRelationModifier -10",
    },
    "knowledgeSharing": {
        # science.js: sciencePolicyRatio 0.05 (exakter Ratensatz).
        "rate_ratio": {"science": 0.05}, "estimate": False,
        "source": "science.js knowledgeSharing: sciencePolicyRatio 0.05",
    },
    "culturalExchange": {
        # science.js: culturePolicyRatio 0.05 (exakter Ratensatz).
        "rate_ratio": {"culture": 0.05}, "estimate": False,
        "source": "science.js culturalExchange: culturePolicyRatio 0.05",
    },
    "outerSpaceTreaty": {
        # science.js: globalRelationsBonus 10 — bessere Trades, kleiner Proxy.
        "global_ratio": 0.01, "estimate": True,
        "source": "science.js outerSpaceTreaty: globalRelationsBonus 10",
    },
    "militarizeSpace": {
        # science.js: satelliteSynergyBonus 0.1 → Starchart-Schätzung.
        "rate_ratio": {"starchart": 0.10}, "estimate": True,
        "source": "science.js militarizeSpace: satelliteSynergyBonus 0.1",
    },
    # --- Philosophie (philosophy unlocks, science.js:175) ---
    "epicurianism": {
        # science.js (sic!): luxuryHappinessBonus 1 — Happiness-Proxy.
        "global_ratio": 0.05, "estimate": True,
        "source": "science.js epicurianism: luxuryHappinessBonus 1",
    },
    "stoicism": {
        # science.js: luxuryDemandRatio −0.5, breweryConsumptionRatio −0.25 —
        # gesparter Luxuskonsum, kleiner globaler Proxy.
        "global_ratio": 0.02, "estimate": True,
        "source": "science.js stoicism: luxuryDemandRatio -0.5",
    },
    "carnivale": {
        # science.js: festivalArrivalRatio 0.3 — Kitten-Ankünfte-Proxy.
        "global_ratio": 0.02, "estimate": True,
        "source": "science.js carnivale: festivalArrivalRatio 0.3",
    },
    "extravagance": {
        # science.js: luxuryDemandRatio +2 — Netto-Malus.
        "global_ratio": -0.02, "estimate": True,
        "source": "science.js extravagance: luxuryDemandRatio 2",
    },
    # --- Industrie (evaluateLocks: Factory, science.js:1021 ff) ---
    "liberalism": {
        # science.js: goldCostReduction 0.2 → wie +20 % effektives Gold.
        "rate_ratio": {"gold": 0.20}, "estimate": True,
        "source": "science.js liberalism: goldCostReduction 0.2",
    },
    "communism": {
        # science.js: coal/iron/titaniumPolicyRatio 0.25 (exakte Ratensätze;
        # factoryCostReduction 0.3 unbewertet).
        "rate_ratio": {"coal": 0.25, "iron": 0.25, "titanium": 0.25},
        "estimate": False,
        "source": "science.js communism: coal/iron/titaniumPolicyRatio 0.25",
    },
    "fascism": {
        # science.js: logHouseCostReduction 0.5 — Housing-Proxy.
        "global_ratio": 0.02, "estimate": True,
        "source": "science.js fascism: logHouseCostReduction 0.5",
    },
    # --- Informationszeitalter (science.js:1075 ff) ---
    "technocracy": {
        # science.js: technocracyScienceCap 0.2 (Cap!), antimatterPolicyRatio
        # 0.0625 — Science-Cap als kleine Ratenschätzung, AM exakt.
        "rate_ratio": {"science": 0.05, "antimatter": 0.0625}, "estimate": True,
        "source": "science.js technocracy: technocracyScienceCap 0.2, antimatterPolicyRatio 0.0625",
    },
    "theocracy": {
        # science.js: faithPolicyRatio 0.2 (exakter Ratensatz).
        "rate_ratio": {"faith": 0.20}, "estimate": False,
        "source": "science.js theocracy: faithPolicyRatio 0.2",
    },
    "expansionism": {
        # science.js: unobtainiumPolicyRatio 0.15 (exakter Ratensatz).
        "rate_ratio": {"unobtainium": 0.15}, "estimate": False,
        "source": "science.js expansionism: unobtainiumPolicyRatio 0.15",
    },
}

# Referenzpreise (Culture) aus science.js — für die I-07-Bewertung von
# Alternativen, die im Snapshot (noch) nicht sichtbar sind. Exklusive
# Paare kosten im Spiel stets gleich viel („Policies with the same
# numerical cost are mutually exclusive", i18n msg.policy.exclusivity).
POLICY_REF_PRICES: dict[str, float] = {
    "liberty": 150, "tradition": 150,
    "monarchy": 1500, "authocracy": 1500, "republic": 1500,
    "diplomacy": 1600, "isolationism": 1600,
    "epicurianism": 2500, "stoicism": 2500,
    "carnivale": 3500, "extravagance": 3500,
    "knowledgeSharing": 4000, "culturalExchange": 4000,
    "zebraRelationsAppeasement": 5000, "zebraRelationsBellicosity": 5000,
    "outerSpaceTreaty": 10000, "militarizeSpace": 10000,
    "liberalism": 15000, "communism": 15000, "fascism": 15000,
    "technocracy": 150000, "theocracy": 150000, "expansionism": 150000,
}

# ------------------------------------------------------------ 13.4-Prior
# Spec-13.4-Starttabelle → Run-Typ-Kontexte (Suchraumreduktion, kein Zwang).
# Spielnamen der Referenzversion: „Epicureanism" = epicurianism (sic),
# „Zebra Appeasement" = zebraRelationsAppeasement.
_EARLY = ("tradition", "monarchy", "diplomacy", "epicurianism",
          "zebraRelationsAppeasement")
_TRADE = ("diplomacy", "liberalism", "zebraRelationsAppeasement",
          "outerSpaceTreaty")
POLICY_PRIOR: dict[str, tuple[str, ...]] = {
    # „Früher Reset" (13.4 Zeile 1):
    "FIRST_RUN": _EARLY,
    "PRICE_RATIO_RUN": _EARLY,
    "CORE_META_RUN": _EARLY,
    "CHALLENGE_RUN": _EARLY,
    # „Housing-/Paragon-Run" (Fascism/Carnivale/Arrival-orientiert):
    "PARAGON_RUN": ("fascism", "carnivale", "epicurianism", "tradition",
                    "monarchy", "diplomacy"),
    # „Handels-/Titanium-Run":
    "UNICORN_RUN": _TRADE,
    "LEVIATHAN_RUN": _TRADE,
    # „Faith" (Order-of-the-Stars-Pfad → theocracy in 1.5.0.2):
    "RELIGION_RUN": ("theocracy",) + _EARLY,
    # „Industrie"/„Unobtainium" (Communism, Expansionism):
    "RELIC_STATION_RUN": ("technocracy", "expansionism", "communism") + _TRADE,
    "SHATTER_RUN": ("technocracy", "expansionism", "communism") + _TRADE,
    "SEED_RUN": ("technocracy", "expansionism") + _TRADE,
}
DEFAULT_PRIOR: tuple[str, ...] = _EARLY


# ------------------------------------------------------------ Bewertung

def _rate_delta(snap: dict, name: str, lam: dict[str, float]) -> dict[str, float]:
    """ΔRate der Policy aus der Referenztabelle (nur Ressourcen mit
    positiver laufender Produktion — ohne Rate keine seriöse Ratio-Basis)."""
    eff = POLICY_EFFECTS.get(name)
    if not eff:
        return {}
    delta: dict[str, float] = {}
    for res, ratio in sorted(eff.get("rate_ratio", {}).items()):
        rate = A.res_rate(snap, res)
        if rate > 0:
            delta[res] = ratio * rate
    g = eff.get("global_ratio", 0.0)
    if g and lam:
        for res in sorted(lam):
            if lam[res] <= 0:
                continue
            rate = A.res_rate(snap, res)
            if rate > 0:
                delta[res] = delta.get(res, 0.0) + g * rate
    return delta


def policy_value(snap: dict, policy: dict, lam: dict[str, float],
                 horizon: float) -> float:
    """PolicyValue in Ziel-Sekunden: λ-bewerteter Ratengewinn über den
    Restplan-Horizont minus λ-bewertete Kaufkosten (Spec 13.4 / 10.2).
    Ohne Effekt-Referenz oder λ-Daten: 0 (kein Wert behauptbar)."""
    delta = _rate_delta(snap, policy["name"], lam or {})
    benefit = shadow.benefit_time(delta, lam or {}, horizon)
    cost = shadow.cost_time(policy.get("prices") or [], lam or {})
    return benefit - cost


def _alternative_stub(name: str) -> dict:
    """Pseudo-Policy für Alternativen, die der Snapshot (noch) nicht führt —
    Referenzpreis aus science.js, Effekte aus der Referenztabelle."""
    price = POLICY_REF_PRICES.get(name)
    return {"name": name,
            "prices": ([{"name": "culture", "val": price}] if price else [])}


def i07_check(snap: dict, policy: dict, lam: dict[str, float],
              horizon: float) -> tuple[bool, dict[str, float]]:
    """Invariante I-07: PolicyValue(gewählt) ≥ PolicyValue(Alternative) für
    JEDE per `blocks` ausgeschlossene Alternative, beide über denselben
    Horizont. Unbekannte Alternativen (weder Snapshot noch Referenztabelle)
    ⇒ konservativ nicht zulässig. Rückgabe: (zulässig, {alt: wert})."""
    own = policy_value(snap, policy, lam, horizon)
    by_name = {p["name"]: p for p in snap.get("policies") or []}
    alt_values: dict[str, float] = {}
    ok = True
    for alt_name in sorted(policy.get("blocks") or []):
        alt = by_name.get(alt_name)
        if alt is None:
            if alt_name not in POLICY_EFFECTS and alt_name not in POLICY_REF_PRICES:
                return False, alt_values   # nicht bewertbar → I-07 verletzt
            alt = _alternative_stub(alt_name)
        val = policy_value(snap, alt, lam, horizon)
        alt_values[alt_name] = val
        if own + EPS < val:
            ok = False
    return ok, alt_values


def best_policy(snap: dict, run_type: str, lam: dict[str, float],
                horizon: float) -> tuple[dict, float, dict[str, float]] | None:
    """Beste zulässige Policy für den aktuellen Kontext (Run-Typ).

    Suchraum = 13.4-Prior des Run-Typs ∪ exklusive Gegenstücke der
    Prior-Kandidaten (I-07: die bewertete Alternative darf gewinnen).
    Zulässig: unlocked, nicht researched, nicht blocked, bezahlbar,
    PolicyValue > 0 UND I-07 bestanden. Rückgabe: (policy, wert,
    alternativen-Werte) — deterministisch (Wert absteigend, Name)."""
    policies = snap.get("policies")
    if not policies:
        return None
    by_name = {p["name"]: p for p in policies}
    prior = POLICY_PRIOR.get(run_type, DEFAULT_PRIOR)
    names: set[str] = set(prior)
    for n in prior:
        p = by_name.get(n)
        if p:
            names.update(p.get("blocks") or [])
    scored: list[tuple[float, str, dict, dict[str, float]]] = []
    for name in sorted(names):
        p = by_name.get(name)
        if p is None or p.get("researched") or p.get("blocked") \
                or not p.get("unlocked"):
            continue
        if not A.affordable(snap, p.get("prices") or []):
            continue
        value = policy_value(snap, p, lam, horizon)
        if value <= 0:
            continue
        ok, alt_values = i07_check(snap, p, lam, horizon)
        if not ok:
            continue
        scored.append((value, name, p, alt_values))
    if not scored:
        return None
    scored.sort(key=lambda t: (-t[0], t[1]))
    value, _, pol, alt_values = scored[0]
    return pol, value, alt_values
