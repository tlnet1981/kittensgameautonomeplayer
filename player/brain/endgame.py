"""Endgame-Fähigkeitsindex C(S), Progressionsfront-Proxy und ΔlnC/Δt-Score
(Spielmechanik-Spec 1.3, 6.3, 9 [P8], Anhang D „Endgame-Score").

C(S) ist das geometrische Mittel der normalisierten persistenten Raten:

    C(S) = ( Π_i max(ε, r_i / b_i) )^(1/n)          (Spec 1.3)

über die sieben persistenten Dimensionen: Paragon/Burnt-Paragon-Wirkung,
Epiphany-/Transcendence-Wirkung, Time-Crystal-Nettoertrag, Relic-Ertrag,
Antimatter-Ertrag, Void-Ertrag und positive Chronosphere-Carryover-Leistung.

r_i sind beobachtete bzw. projizierte NACHHALTIGE Raten aus dem Snapshot
(siehe dimension_rates — fehlt die Dimension im Snapshot, zählt sie ehrlich
mit ε statt mit einem geratenen Wert); b_i sind feste Referenzraten
(REFERENCE_RATES). Die Referenzraten sind reine Normierungsgrößen: beim
geometrischen Mittel skalieren sie nur, sie ändern die Rangfolge
proportionaler Zustände nicht (Spec 1.3).

Bewusste Näherungen (dokumentiert statt versteckt):
- „Paragon-Wirkung" wird als Paragonrate des laufenden Runs gemessen
  (Reset-Paragon ÷ bisherige Run-Zeit, Formel Anhang D) — der Snapshot
  liefert keine run-übergreifende Historie.
- „Epiphany-Wirkung" als Adore-Gewinnrate: worship/1e6 · (tt+1)² ·
  bonusRatio (religion.js:1617-1621) ÷ Run-Zeit.
- „CS-Carryover-Leistung" als Carryover-Anteil je Run-Sekunde
  (k · 1,5 % je Chronosphere, chrono.CARRYOVER_PER_CS), aber nur wenn die
  positive Reset-Bedingung 19.2 nachgewiesen ist (chrono.positive_cs_check)
  — sonst ist die Schleife nicht „positiv" und die Dimension fehlt.
- endgame_score projiziert nur die Paragon-Dimension über die EV-Projektion
  (simulate.Projection.paragon_projection); alle anderen Raten gelten
  konservativ als konstant — ihr ln-Beitrag zur Differenz ist dann 0.
"""

from __future__ import annotations

import math

from player.state import access as A

from . import challenge, chrono, simulate, timecrystal

EPS = 1e-9
# ε der C(S)-Formel (Spec 1.3: „verhindert Nullwerte"):
EPS_DIM = 1e-6

# Feste Dimensionsreihenfolge (deterministisch, Spec 1.3):
DIMENSIONS: tuple[str, ...] = (
    "paragon", "epiphany", "timeCrystal", "relic",
    "antimatter", "void", "csCarryover",
)

# Referenzraten b_i — REINE NORMIERUNGSGRÖSSEN (Spec 1.3), keine Spielwerte.
# Gewählt als grobe „reifer Endgame-Zustand ≈ 1"-Anker (Sagefault-Benchmark
# Q4/Q6 als Größenordnung); beim geometrischen Mittel beeinflussen sie nur
# die Skala von C, nie die Rangfolge proportionaler Zustände:
REFERENCE_RATES: dict[str, float] = {
    "paragon": 0.01,        # ≈ 36 Paragon je Stunde Run-Zeit
    "epiphany": 1e-4,       # ≈ 0,36 Epiphany je Stunde (Adore-Rate)
    "timeCrystal": 0.01,    # ≈ 36 TC je Stunde Nettozufluss
    "relic": 0.05,          # ≈ 180 Relic je Stunde
    "antimatter": 0.02,     # ≈ 72 Antimatter je Stunde
    "void": 0.005,          # ≈ 18 Void je Stunde
    "csCarryover": 1e-4,    # ≈ 36 % Carryover-Anteil je Stunde Run-Zeit
}

# AM-Cap der vollen Relic-Station-Wirkung (space.js:718-720, wie
# meta.RELIC_STATION_AM_CAP — hier lokal, meta importiert dieses Modul):
AM_CAP_FULL_RELIC = 5000.0


# ================================================================ Dimensionen

def _positive_rate(snap: dict, res: str) -> float | None:
    """Beobachtete Netto-Rate > 0 der Ressource, sonst None (Dimension
    fehlt ehrlich — auch wenn die Ressource existiert, aber nichts fließt)."""
    if A.resource(snap, res) is None:
        return None
    rate = A.res_rate(snap, res)
    return rate if rate > EPS else None


def dimension_rates(snap: dict) -> dict[str, float | None]:
    """Nachhaltige Raten r_i je Dimension aus dem Snapshot (None = Dimension
    nicht beobachtbar → zählt in C(S) mit ε, Spec 1.3)."""
    elapsed = max(simulate.run_elapsed_seconds(snap), 1.0)
    out: dict[str, float | None] = {}

    # Paragon/Burnt-Paragon-Wirkung: Reset-Paragonrate des laufenden Runs
    # (max(0, kittens−70) + year//1000, Anhang D / derived.resetParagon):
    rp = snap.get("derived", {}).get("resetParagon")
    out["paragon"] = (rp / elapsed) if isinstance(rp, (int, float)) and rp > 0 else None

    # Epiphany-/Transcendence-Wirkung: Adore-Gewinnrate (religion.js:1617-1621).
    rel = snap.get("religion") if isinstance(snap.get("religion"), dict) else {}
    worship = float(rel.get("worship", 0.0) or 0.0)
    if worship > 0:
        from . import religion as _religion   # Paket-intern (Formel-Reuse)
        tier = int(rel.get("transcendenceTier", 0) or 0)
        gain = _religion._adore_gain(worship, tier, _religion._transcendence_on(snap))
        out["epiphany"] = gain / elapsed if gain > EPS else None
    else:
        out["epiphany"] = None

    # TC-Netto: nur die beobachtete Nettorate (tc_balance 17.1); Potenziale
    # (Alicorn-Bestand, Leviathan-Trades) sind keine nachhaltigen Raten:
    tc_rate = timecrystal.tc_balance(snap)["ratePerSec"]
    out["timeCrystal"] = tc_rate if tc_rate > EPS else None

    out["relic"] = _positive_rate(snap, "relic")
    out["antimatter"] = _positive_rate(snap, "antimatter")
    out["void"] = _positive_rate(snap, "void")

    # Positive CS-Carryover-Leistung: Carryover-Anteil je Run-Sekunde, nur
    # bei nachgewiesener positiver Reset-Bedingung (19.2):
    cs = A.bld_val(snap, "chronosphere")
    if cs >= 1 and chrono.positive_cs_check(snap)[0]:
        out["csCarryover"] = cs * chrono.CARRYOVER_PER_CS / elapsed
    else:
        out["csCarryover"] = None
    return out


def capability_index(snap: dict, rates: dict[str, float | None] | None = None) -> float:
    """C(S) = geometrisches Mittel von max(ε, r_i/b_i) (Spec 1.3).

    rates: optionale Überschreibung der Dimensionsraten (endgame_score
    nutzt das für die projizierten Raten); None-Einträge bzw. fehlende
    Dimensionen zählen mit ε — ehrlich statt geraten."""
    if rates is None:
        rates = dimension_rates(snap)
    log_sum = 0.0
    for dim in DIMENSIONS:
        r = rates.get(dim)
        factor = EPS_DIM
        if isinstance(r, (int, float)) and r > 0:
            factor = max(EPS_DIM, r / REFERENCE_RATES[dim])
        log_sum += math.log(factor)
    return math.exp(log_sum / len(DIMENSIONS))


# ================================================================ Front (6.1/1.3)

def frontier_complete(snap: dict) -> bool:
    """Proxy „endliche Progressionsfront F erfüllt" (Spec 1.3/6.1) —
    prüfbare, KONSERVATIVE Liste (fehlende Daten ⇒ False, der Agent darf
    keine spätere Phase als operational markieren, Kap. 9):

    1. Metaphysics: alle im Snapshot gelisteten Perks researched UND die
       feste Kette meta.METAPHYSICS_ORDER vollständig (9.1).
    2. Challenges: Liste vorhanden und jeder Nicht-IronWill-Erstabschluss
       registriert (researched, 18.1/6.1).
    3. Religion: Solar Revolution aktiv und Transcendence-Tier ≥ 1 (15.1/15.2).
    4. Space/Relic: relicStation researched und AM-Cap ≥ 5000 — volle
       Relic-Wirkung (space.js:718-720, workshop.js:1538-1550).
    5. Time: Resource Retrieval ≥ 1 — Shatter-Engine operational (17.2).
    """
    from . import meta as _meta   # lazy: meta importiert endgame (kein Zyklus)
    perks = snap.get("prestige", {}).get("perks", [])
    if not perks or not all(p.get("researched") for p in perks):
        return False
    researched = {p["name"] for p in perks if p.get("researched")}
    if not set(_meta.METAPHYSICS_ORDER) <= researched:
        return False
    todo = [c for c in challenge.challenge_list(snap)
            if c.get("name") not in challenge.EXCLUDED]
    if not todo or not all(c.get("researched") for c in todo):
        return False
    rel = snap.get("religion") if isinstance(snap.get("religion"), dict) else {}
    solar = any(u.get("name") == "solarRevolution" and (u.get("on") or u.get("val"))
                for u in rel.get("upgrades", []))
    if not solar or int(rel.get("transcendenceTier", 0) or 0) < 1:
        return False
    up = A.upgrade(snap, "relicStation")
    if not (up and up.get("researched")):
        return False
    if A.res_cap(snap, "antimatter") < AM_CAP_FULL_RELIC:
        return False
    return timecrystal.rr_level(snap) >= 1


# ================================================================ Score (6.3)

def endgame_score(snap: dict, horizon: float,
                  proj: "simulate.Projection | None" = None) -> float:
    """E[Δln C / Δt] über die EV-Projektion (Spec 6.3 / Anhang D).

    Dokumentierte Näherung: Nur die Paragon-Dimension wird über die
    Projektion fortgeschrieben (paragon_projection: Kitten-Ankünfte und
    Jahresfortschritt); alle anderen Raten gelten konservativ als konstant
    und tragen 0 zur ln-Differenz bei. Ohne Projektionsdaten: 0.0."""
    if horizon <= EPS:
        return 0.0
    if proj is None:
        if not simulate.has_projection_data(snap):
            return 0.0
        proj = simulate.project(snap, horizon)
    rates_now = dimension_rates(snap)
    rates_later = dict(rates_now)
    elapsed = max(simulate.run_elapsed_seconds(snap), 1.0)
    p_later = proj.paragon_projection(horizon)
    if p_later > 0:
        rates_later["paragon"] = p_later / (elapsed + horizon)
    c_now = capability_index(snap, rates=rates_now)
    c_later = capability_index(snap, rates=rates_later)
    return (math.log(c_later) - math.log(c_now)) / horizon
