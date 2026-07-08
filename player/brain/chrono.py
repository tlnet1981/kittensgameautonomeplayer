"""Chronosphere-Zielzahl-Suche (Spec 19.1 / Anhang D) und positive
Reset-Schleife / Seed-Zulässigkeit (Spec 19.2/19.3).

    CSValue(k) = CarryoverGain(k) + ResetTimeSaving(k) − UOCost(k) − RebuildDelay(k)

Alle Terme in Sekunden. Die Suche prüft das lokale Fenster n−2 … n+3 um den
aktuellen Bestand n (Spec 19.1); strukturelle Kandidaten für Void-/Speedrun-
Schleifen folgen mit späterem Ausbau.

Bewusste Näherungen (dokumentiert statt versteckt):
- Carryover + ResetTimeSaving werden zusammen bewertet: k Chronospheres
  übertragen k·1,5 % jedes Ressourcenbestands über den Reset (CARRYOVER_PER_CS
  ist der Referenzwert der Zielversion 1.5.0.2, effects "resStasisRatio").
  Der Sekundenwert ist die gesparte Wiederbeschaffungszeit — übertragener
  Bestand ÷ aktuelle Produktionsrate (nur Ressourcen mit positiver Rate:
  was nichts produziert, kann die Projektion nicht seriös bewerten).
- UOCost: kumulierte Preise der Einheiten n+1…k (Preis-Ratio 1.25 der
  Referenzversion), bewertet über den Schattenpreis λ (falls übergeben),
  sonst ETA-basiert (Menge ÷ Rate). Unbeschaffbare Positionen ⇒ CSValue −inf.
- RebuildDelay: pauschal REBUILD_DELAY_PER_CS_S Sekunden je Chronosphere —
  jeder Bestand muss im Folgerun neu errichtet werden, bevor der Carryover
  erneut wirkt (grobe Logistik-Konstante, kein Spielwert).
"""

from __future__ import annotations

import math

from player.state import access as A

EPS = 1e-9
RATE_EPS = 1e-7

# Referenzwert v1.5.0.2: +1,5 % Ressourcen-Carryover je Chronosphere.
CARRYOVER_PER_CS = 0.015
# Preis-Ratio des Chronosphere-Gebäudes in der Referenzversion:
CS_PRICE_RATIO = 1.25
# Wiederaufbau-Näherung je Chronosphere im Folgerun (siehe Modul-Docstring):
REBUILD_DELAY_PER_CS_S = 60.0
# Suchfenster um den aktuellen Bestand (Spec 19.1: n−2 … n+3):
SEARCH_BELOW, SEARCH_ABOVE = 2, 3


def _carryover_seconds_per_cs(snap: dict) -> float:
    """Sekundenwert des Carryovers EINER Chronosphere: Wiederbeschaffungszeit
    der übertragenen 1,5 % je Ressource mit positiver Produktionsrate."""
    total = 0.0
    for r in snap.get("resources", []):
        rate = r.get("perSec", 0.0)
        value = r.get("value", 0.0)
        if rate > RATE_EPS and value > 0:
            total += (CARRYOVER_PER_CS * value) / rate
    return total


def _extra_units_cost_seconds(snap: dict, prices: list[dict], n: int, k: int,
                              lam: dict | None) -> float:
    """UOCost(k): Sekundenkosten der Einheiten n+1 … k. Bereits gebaute
    Einheiten sind versunkene Kosten (0). λ_unobtainium & Co. falls
    verfügbar, sonst ETA-basiert (Menge ÷ Rate); Rate ≈ 0 ⇒ inf."""
    if k <= n:
        return 0.0
    scale = sum(CS_PRICE_RATIO ** j for j in range(k - n))  # Preise ab nächster Einheit
    total = 0.0
    for p in prices:
        amount = p["val"] * scale
        lam_i = (lam or {}).get(p["name"], 0.0)
        if lam_i > EPS:
            total += amount * lam_i
            continue
        rate = A.res_rate(snap, p["name"])
        if rate <= RATE_EPS:
            # Position hat weder Schattenpreis noch Produktion: falls der
            # Bestand schon reicht, kostet sie keine Zeit — sonst unbezahlbar.
            if A.res_value(snap, p["name"]) + EPS >= amount:
                continue
            return math.inf
        total += amount / rate
    return total


def optimal_chronosphere_count(snap: dict, lam: dict | None = None
                               ) -> tuple[int | None, dict]:
    """Optimale Chronosphere-Zahl im Fenster n−2 … n+3 (Spec 19.1).

    Rückgabe (n_target, detail); (None, …) ohne verwertbare Chronosphere-
    Daten im Snapshot — der Aufrufer fällt dann auf das Altverhalten zurück.
    Tie-Break deterministisch: bei gleichem CSValue gewinnt das kleinere k.
    """
    b = A.building(snap, "chronosphere")
    if b is None or not b.get("prices"):
        return None, {"reason": "keine Chronosphere-Daten im Snapshot — Fallback"}
    n = int(b.get("val", 0))
    carry_per_cs = _carryover_seconds_per_cs(snap)
    values: dict[int, float] = {}
    for k in range(max(0, n - SEARCH_BELOW), n + SEARCH_ABOVE + 1):
        cost = _extra_units_cost_seconds(snap, b["prices"], n, k, lam)
        if math.isinf(cost):
            values[k] = -math.inf
            continue
        values[k] = (carry_per_cs * k                    # Carryover + ResetTimeSaving
                     - cost                              # UOCost
                     - REBUILD_DELAY_PER_CS_S * k)       # RebuildDelay
    n_target = min(values, key=lambda k: (-values[k], k))
    detail = {
        "n": n,
        "nTarget": n_target,
        "carryoverPerCsS": round(carry_per_cs, 1),
        "csValues": {k: (None if math.isinf(v) else round(v, 1))
                     for k, v in values.items()},
        # Marginaler Sekundenwert der NÄCHSTEN Chronosphere (fürs Cockpit):
        "csValueNext": (None if math.isinf(values[n + 1])
                        else round(values[n + 1] - values[n], 1)),
    }
    return n_target, detail


# ================================================================ 19.2 Positive Schleife

# Ressourcen mit persists: true der Referenzversion — sie überleben den
# Reset vollständig (gamefiles/js/resources.js: sorrow 286-291; paragon/
# burnedParagon/karma sind persistente Prestige-Ressourcen; game.js:5054).
PERSISTENT_RESOURCES = frozenset({"sorrow", "paragon", "burnedParagon", "karma"})


def _has_perk(snap: dict, name: str) -> bool:
    return any(p.get("name") == name and p.get("researched")
               for p in snap.get("prestige", {}).get("perks", []))


def carryover_vector(snap: dict) -> dict[str, float]:
    """Projizierter Post-Reset-Carryover je Ressource — exakt die Fallliste
    aus game.js _resetInternal (Zeilen 5008/5040-5065):

    - saveRatio = resStasisRatio nur mit Chronospheres (0.015 × val,
      buildings.js:2049; game.js:5008),
    - timeCrystal: voll NUR mit Anachronomancy (game.js:5050-5053),
    - persists-Ressourcen: voll (game.js:5054-5055, PERSISTENT_RESOURCES),
    - craftbare außer Wood: ohne fluxCondensator verloren (game.js:5044-5047),
      mit fluxCondensator sqrt(value) × saveRatio × 100 (game.js:5062-5064),
    - sonst (nicht craftbar oder Wood): value × saveRatio; void wird
      abgerundet (game.js:5057-5061).
    Kurzlebige Pools (tears/alicorn/temporalFlux…, persists: false) fehlen
    im Ergebnis — der Snapshot markiert sie nicht, aber ihre Werte laufen
    über den saveRatio-Zweig und bleiben klein (dokumentierte Näherung:
    persists-false-Sonderfälle außer den bekannten werden nicht abgezogen).
    """
    cs = A.bld_val(snap, "chronosphere")
    save_ratio = cs * CARRYOVER_PER_CS if cs > 0 else 0.0
    anachronomancy = _has_perk(snap, "anachronomancy")
    flux_cond = A.upgrade(snap, "fluxCondensator")
    flux_cond_ok = bool(flux_cond and flux_cond.get("researched"))
    out: dict[str, float] = {}
    for r in snap.get("resources", []):
        name = r["name"]
        value = float(r.get("value", 0.0))
        if value <= 0:
            continue
        if name == "timeCrystal":
            out[name] = value if anachronomancy else 0.0
        elif name in PERSISTENT_RESOURCES:
            out[name] = value
        elif r.get("craftable") and name != "wood":
            out[name] = (math.sqrt(value) * save_ratio * 100.0
                         if flux_cond_ok else 0.0)
        else:
            carried = value * save_ratio
            if name == "void":
                carried = math.floor(carried)
            out[name] = carried
    return out


def rebuild_cost_vector(snap: dict) -> dict[str, float] | None:
    """Wiederaufbaukosten der Chronosphere-Flotte im Folgerun: Einheiten
    1…n zum Basispreis × Preis-Ratio-Reihe (Ratio 1.25, Referenzversion).
    Der Snapshot-Preis gilt für Einheit n+1 (= Basis × 1.25^n) — daraus
    Basis und Summe. None ohne Chronosphere-Daten."""
    b = A.building(snap, "chronosphere")
    if b is None or not b.get("prices"):
        return None
    n = int(b.get("val", 0))
    if n <= 0:
        return {}
    scale = sum(CS_PRICE_RATIO ** j for j in range(n)) / CS_PRICE_RATIO ** n
    return {p["name"]: p["val"] * scale for p in b["prices"]}


def positive_cs_check(snap: dict) -> tuple[bool, dict]:
    """Vektordominanz-Test der positiven Reset-Bedingung (Spec 19.2):

        R_after_reset − R_rebuild ≻ R_before_reset

    Dokumentierte Näherung: Der Ausgangsvektor des Folgeruns ist der
    Nullvektor eines frischen Runs (der Snapshot enthält den Startvektor
    des LAUFENDEN Runs nicht). Dominanz heißt dann: der projizierte
    Carryover (carryover_vector, game.js _resetInternal) deckt in JEDER
    Wiederaufbau-Ressource die kompletten Kosten der Chronosphere-Flotte
    (rebuild_cost_vector) und lässt in mindestens EINER kritischen
    Ressource (Wiederaufbau- oder Carryover-Ressource) einen strikten
    Überschuss. Rückgabe (dominates, detail)."""
    n = A.bld_val(snap, "chronosphere")
    if n < 1:
        return False, {"reason": "keine Chronosphere — kein Carryover (19.2)"}
    rebuild = rebuild_cost_vector(snap)
    if rebuild is None:
        return False, {"reason": "keine Chronosphere-Preisdaten — Fallback"}
    carry = carryover_vector(snap)
    critical = sorted(set(rebuild) | {res for res, v in carry.items() if v > EPS})
    covers_all = all(carry.get(res, 0.0) + EPS >= need
                     for res, need in rebuild.items())
    surplus = {res: carry.get(res, 0.0) - rebuild.get(res, 0.0)
               for res in critical}
    strictly_better = any(v > EPS for v in surplus.values())
    dominates = covers_all and strictly_better
    detail = {
        "chronospheres": n,
        "carry": {k: round(v, 2) for k, v in sorted(carry.items()) if v > EPS},
        "rebuild": {k: round(v, 2) for k, v in sorted(rebuild.items())},
        "surplus": {k: round(v, 2) for k, v in sorted(surplus.items())},
        "coversRebuild": covers_all,
        "reason": ("Carryover dominiert Wiederaufbau (19.2)" if dominates else
                   "Carryover deckt den Wiederaufbau nicht in allen "
                   "kritischen Ressourcen (19.2)"),
    }
    return dominates, detail


# ================================================================ 19.3 Seed-Run

def seed_progress(snap: dict) -> dict:
    """Fortschritt zur Seed-Basis (Spec 19.3, #38/#42) — EINE Definition
    für die SEED_RUN-Restzeit (meta) und den Reset-Trigger (reset):

    Seed-Basis = die erste GANZE Carryover-Einheit des Seed-Trägers
    überlebt den Reset. Referenzmechanik game.js _resetInternal:
    saveRatio = Chronospheres × 0.015 (resStasisRatio, buildings.js:2049;
    game.js:5008); Void wird beim Carryover ABGERUNDET (game.js:5057-5061)
    — erst floor(value·s) ≥ 1 trägt also wirklich etwas hinüber.
    Antimatter läuft über denselben value×saveRatio-Zweig (nicht craftbar).

    Je Träger (void bevorzugt — das eigentliche Seed-Gut; sonst
    antimatter): Zielbestand der nächsten ganzen Einheit
    target = (floor(value·s)+1)/s, ETA über die BEOBACHTETE Rate
    (need/rate wie UNICORN/SHATTER — Void/AM sind nicht in
    simulate.TRACKED); Rate ≈ 0 → inf, ohne Chronosphere → inf
    (saveRatio 0, nichts überlebt). Rückgabe:
    {"basisReached", "nextUnitEtaS", "detail"} — deterministisch."""
    cs = A.bld_val(snap, "chronosphere")
    save_ratio = cs * CARRYOVER_PER_CS if cs > 0 else 0.0
    detail: dict = {"chronospheres": cs, "saveRatio": round(save_ratio, 4)}
    if save_ratio <= 0:
        detail["reason"] = "keine Chronosphere — kein Seed-Carryover (19.3)"
        return {"basisReached": False, "nextUnitEtaS": math.inf,
                "detail": detail}
    basis_reached = False
    etas: list[float] = []
    for res in ("void", "antimatter"):
        value = A.res_value(snap, res)
        carried_units = math.floor(value * save_ratio)
        if carried_units >= 1:
            basis_reached = True
        target = (carried_units + 1) / save_ratio
        rate = A.res_rate(snap, res)
        eta = (target - value) / rate if rate > 1e-9 else math.inf
        etas.append(eta)
        detail[res] = {"value": round(value, 2),
                       "carriedUnits": carried_units,
                       "nextUnitEtaS": (round(eta, 1)
                                        if math.isfinite(eta) else None)}
    next_eta = min(etas) if etas else math.inf
    detail["reason"] = ("Seed-Basis erreicht: ganze Carryover-Einheit "
                        "überlebt den Reset (19.3)" if basis_reached else
                        "Seed-Basis offen: noch keine ganze Carryover-"
                        "Einheit (19.3)")
    return {"basisReached": basis_reached, "nextUnitEtaS": next_eta,
            "detail": detail}


def seed_run_admissible(snap: dict) -> tuple[bool, dict]:
    """SEED_RUN-Zulässigkeit (Spec 19.3, konservative Kriterien —
    dokumentiert): Void-Farming ist ein EIGENER MacroPlan und wird nie
    beiläufig eingebaut. Zulässig nur, wenn

    1. mindestens eine Chronosphere steht (Carryover-Träger des Seeds) UND
    2. ein Seed-Ziel beobachtbar erreichbar ist: Void-Bestand > 0,
       Antimatter-Bestand > 0 oder ein freigeschaltetes voidspace-Upgrade
       im Snapshot (time.voidspace, time.js voidspaceUpgrades).
    """
    cs = A.bld_val(snap, "chronosphere")
    void_v = A.res_value(snap, "void")
    am_v = A.res_value(snap, "antimatter")
    vsu = any(u.get("unlocked") for u in
              snap.get("time", {}).get("voidspace", []))
    ok = cs >= 1 and (void_v > 0 or am_v > 0 or vsu)
    detail = {
        "chronospheres": cs,
        "void": void_v,
        "antimatter": am_v,
        "voidspaceUnlocked": vsu,
        "reason": ("Seed-Ziele erreichbar (19.3)" if ok else
                   "Seed-Kriterien nicht erfüllt: Chronosphere ≥ 1 und "
                   "Void/AM/voidspace-Zugang nötig (19.3)"),
    }
    return ok, detail
