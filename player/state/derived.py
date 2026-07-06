"""Abgeleitete Kennzahlen aus dem rohen Snapshot (Spec 4.2 / 7.2).

Berechnet werden u. a.:
- Fill-/Depletion-Zeiten pro Ressource (Anhang D der Spielmechanik-Spec)
- Catnip-SAISONPROJEKTION (Sicherheitsinvariante I-01, Spec 7.2):
  deterministische Simulation des Catnip-Bestands bis zum Ende des nächsten
  vollständigen Winters — kritisch ist nur, was den Winter rechnerisch
  nicht überlebt. (Ersetzt die frühere pauschale „x Minuten Reserve"-Regel,
  die im Frühling absurd hohe Vorräte verlangte und den Agenten in eine
  Gather-Schleife zwang.)
- Energie-Saldo
- Reset-Paragon-Projektion (max(0, kittens - 70) + Jahre/1000)

Alle Zeiten sind reale Sekunden. Spielkonstanten: 5 Ticks/s, 10 Ticks/Tag
→ 1 Tag = 2 s, 1 Saison = 100 Tage = 200 s, 1 Jahr = 800 s.
"""

from __future__ import annotations

from typing import Any

EPS = 1e-9
# Sichtbarkeitsgrenze: unterhalb gilt eine Rate praktisch als Null.
RATE_EPS = 1e-7

SECONDS_PER_DAY = 2.0
# Fallback-Saisonmodifikatoren der Feldproduktion (Frühling..Winter):
DEFAULT_SEASON_MODS = [1.5, 1.0, 1.0, 0.25]
# Basisproduktion eines einzelnen Catnip-Felds (0.125/Tick × 5 Ticks/s):
CATNIP_PER_FIELD_PER_SEC = 0.625


def project_catnip(snap: dict, stock_delta: float = 0.0,
                   field_rate_delta: float = 0.0,
                   demand_delta: float = 0.0) -> dict[str, float]:
    """Saisonprojektion des Catnip-Bestands (Spec 7.2).

    Simuliert den Bestand segmentweise (Rest der aktuellen Saison, dann
    Folgesaisons) bis einschließlich Ende des nächsten Winters. Innerhalb
    eines Segments ist die Rate konstant → Minima liegen an Segmentgrenzen.

    Die Deltas erlauben „Was-wäre-wenn"-Prüfungen ohne Snapshot-Kopie:
    stock_delta (z. B. −Feldpreis), field_rate_delta (zusätzliche
    Feld-Basisrate in Catnip/s), demand_delta (zusätzlicher Verbrauch/s,
    z. B. durch neue Kitten).

    Rückgabe: {"projectedMin": ..., "projectedMinInSeconds": ...}
    """
    cal = snap.get("calendar", {})
    tps = snap.get("meta", {}).get("ticksPerSecond", 5)
    mods = cal.get("seasonCatnipModifiers") or DEFAULT_SEASON_MODS
    season = int(cal.get("season", 0)) % 4
    day = float(cal.get("day", 0))
    days_per_season = float(cal.get("daysPerSeason", 100)) or 100.0

    catnip = next((r for r in snap.get("resources", []) if r["name"] == "catnip"), None)
    stock = (catnip.get("value", 0.0) if catnip else 0.0) + stock_delta
    net_now = (catnip.get("perSec", 0.0) if catnip else 0.0) - demand_delta
    # field_base renormiert die BESTEHENDE Feldproduktion auf die jeweilige
    # Saison; field_rate_delta ist ZUSÄTZLICHE Basisrate (neues Feld) und
    # wirkt in jeder Saison mit deren Modifikator (nicht wegkürzbar!).
    field_base = snap.get("effects", {}).get("catnipPerTickBase", 0.0) * tps
    mod_now = mods[season] if season < len(mods) else 1.0

    # Segmentliste: Rest der aktuellen Saison + Folgesaisons, bis der
    # nächste Winter (Index 3) vollständig durchlaufen ist.
    segments: list[tuple[int, float]] = [(season, (days_per_season - day) * SECONDS_PER_DAY)]
    s = season
    while True:
        if s == 3:      # der zuletzt angehängte Abschnitt war (Rest-)Winter
            break
        s = (s + 1) % 4
        segments.append((s, days_per_season * SECONDS_PER_DAY))

    # Minimum über die ZUKÜNFTIGEN Segmentgrenzen (Raten sind pro Segment
    # konstant → Minima liegen an Grenzen). Der Ist-Bestand bei t=0 zählt
    # bewusst nicht: bei durchgehend positiver Rate verhungert niemand,
    # egal wie klein der Bestand gerade ist.
    t = 0.0
    min_stock = float("inf")
    min_t = 0.0
    for seg_season, duration in segments:
        mod = mods[seg_season] if seg_season < len(mods) else 1.0
        net = (net_now - field_base * mod_now + field_base * mod
               + field_rate_delta * mod)
        stock += net * duration
        t += duration
        if stock < min_stock:
            min_stock = stock
            min_t = t
    return {"projectedMin": min_stock, "projectedMinInSeconds": min_t}


def derive(snap: dict[str, Any]) -> dict[str, Any]:
    """Reichert den Snapshot in-place um `derived` an und gibt ihn zurück."""
    d: dict[str, Any] = {}

    # --- Ressourcen: Zeit bis Cap / bis leer ---
    res_derived: dict[str, dict[str, Any]] = {}
    for r in snap.get("resources", []):
        net = r.get("perSec", 0.0)
        cap = r.get("maxValue", 0.0)
        val = r.get("value", 0.0)
        fill_time = None
        depletion_time = None
        if net > RATE_EPS and cap > 0 and val < cap:
            fill_time = (cap - val) / net
        if net < -RATE_EPS:
            depletion_time = val / (-net)
        res_derived[r["name"]] = {
            "fillTime": fill_time,
            "depletionTime": depletion_time,
            "pctFull": (val / cap) if cap > 0 else None,
        }
    d["resources"] = res_derived

    # --- Food-Sicherheit (Invariante I-01, Spec 7.2: Saisonprojektion) ---
    cal = snap.get("calendar", {})
    tps = snap.get("meta", {}).get("ticksPerSecond", 5)
    catnip = next((r for r in snap.get("resources", []) if r["name"] == "catnip"), None)
    field_base_per_sec = snap.get("effects", {}).get("catnipPerTickBase", 0.0) * tps
    cur_mod = cal.get("currentCatnipModifier", 1.0) or 1.0
    winter_mod = cal.get("winterCatnipModifier", 0.25)
    demand = snap.get("village", {}).get("catnipDemandPerSec", 0.0) or 0.0
    if catnip is not None:
        net_now = catnip.get("perSec", 0.0)
        # Anzeige-Kennzahl (wie fühlt sich der Winter an):
        worst_winter_net = net_now - field_base_per_sec * cur_mod + field_base_per_sec * winter_mod
        proj = project_catnip(snap)
        # Schwellen: kritisch, wenn der projizierte Tiefpunkt die Population
        # nicht mehr ~30 s trägt; Warnstufe (Housing-Sperre) bei < ~120 s.
        # Ohne Kitten (demand = 0) kann niemand verhungern → immer ok.
        critical_floor = max(50.0, 30.0 * demand)
        warn_floor = max(150.0, 120.0 * demand)
        if demand <= RATE_EPS:
            status = "ok"
        else:
            status = ("critical" if proj["projectedMin"] < critical_floor
                      else "warn" if proj["projectedMin"] < warn_floor else "ok")
        d["food"] = {
            "netNowPerSec": net_now,
            "worstWinterNetPerSec": worst_winter_net,
            "demandPerSec": demand,
            "projectedMin": proj["projectedMin"],
            "projectedMinInSeconds": proj["projectedMinInSeconds"],
            "criticalFloor": critical_floor,
            "warnFloor": warn_floor,
            "status": status,
            "safe": status == "ok",
        }
    else:
        d["food"] = {"netNowPerSec": 0, "worstWinterNetPerSec": 0, "demandPerSec": 0,
                     "projectedMin": 0, "projectedMinInSeconds": 0,
                     "criticalFloor": 50, "warnFloor": 150, "status": "ok", "safe": True}

    # --- Energie (Invariante I-04, relevant ab Space) ---
    energy = snap.get("energy", {})
    d["energy"] = {
        "prod": energy.get("prod", 0),
        "cons": energy.get("cons", 0),
        "balance": energy.get("prod", 0) - energy.get("cons", 0),
    }

    # --- Reset-Paragon-Projektion (Anhang D) ---
    village = snap.get("village", {})
    kittens = village.get("kittens", 0)
    year = cal.get("year", 0)
    d["resetParagon"] = max(0, kittens - 70) + year // 1000

    snap["derived"] = d
    return snap
