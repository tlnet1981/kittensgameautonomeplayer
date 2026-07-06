"""Chronosphere-Zielzahl-Suche (Spec 19.1 / Anhang D).

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
