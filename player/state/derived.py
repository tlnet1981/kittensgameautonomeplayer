"""Abgeleitete Kennzahlen aus dem rohen Snapshot (Spec 4.2 / 7.2, vereinfacht).

Berechnet werden u. a.:
- Fill-/Depletion-Zeiten pro Ressource (Anhang D der Spielmechanik-Spec)
- Worst-Winter-Catnip-Rate und Food-Reservezeit (Sicherheitsinvariante I-01)
- Energie-Saldo
- Reset-Paragon-Projektion (max(0, kittens - 70), Jahresanteil folgt in M3)

Alle Zeiten sind reale Sekunden (bei Normal-Tickrate; das Spiel läuft
konstant mit 5 Ticks/s).
"""

from __future__ import annotations

from typing import Any

EPS = 1e-9
# Sichtbarkeitsgrenze: unterhalb gilt eine Rate praktisch als Null.
RATE_EPS = 1e-7


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

    # --- Food-Sicherheit (Invariante I-01, Spec 7.2 vereinfacht) ---
    # Worst-Case = Winter: Feldproduktion fällt auf den Winter-Modifikator.
    cal = snap.get("calendar", {})
    tps = snap.get("meta", {}).get("ticksPerSecond", 5)
    catnip = next((r for r in snap.get("resources", []) if r["name"] == "catnip"), None)
    field_base_per_sec = snap.get("effects", {}).get("catnipPerTickBase", 0.0) * tps
    cur_mod = cal.get("currentCatnipModifier", 1.0) or 1.0
    winter_mod = cal.get("winterCatnipModifier", 0.25)
    if catnip is not None:
        net_now = catnip.get("perSec", 0.0)
        # Feldanteil auf Winterniveau umrechnen, Rest (Jobs, Verbrauch) bleibt:
        worst_winter_net = net_now - field_base_per_sec * cur_mod + field_base_per_sec * winter_mod
        reserve_seconds = None
        if worst_winter_net < -RATE_EPS:
            reserve_seconds = catnip.get("value", 0.0) / (-worst_winter_net)
        d["food"] = {
            "netNowPerSec": net_now,
            "worstWinterNetPerSec": worst_winter_net,
            "reserveSeconds": reserve_seconds,  # None = Reserve wächst (sicher)
            "safe": worst_winter_net >= 0 or (reserve_seconds or 0) > 20 * 60,
        }
    else:
        d["food"] = {"netNowPerSec": 0, "worstWinterNetPerSec": 0, "reserveSeconds": None, "safe": True}

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
