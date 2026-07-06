"""Bequeme Lesezugriffe auf den Snapshot (überall im Brain verwendet)."""

from __future__ import annotations

import math
from typing import Any

RATE_EPS = 1e-7


def resource(snap: dict, name: str) -> dict | None:
    for r in snap.get("resources", []):
        if r["name"] == name:
            return r
    return None


def res_value(snap: dict, name: str) -> float:
    r = resource(snap, name)
    return r["value"] if r else 0.0


def res_cap(snap: dict, name: str) -> float:
    r = resource(snap, name)
    return r.get("maxValue", 0.0) if r else 0.0


def res_rate(snap: dict, name: str) -> float:
    r = resource(snap, name)
    return r.get("perSec", 0.0) if r else 0.0


def building(snap: dict, name: str) -> dict | None:
    for b in snap.get("buildings", []):
        if b["name"] == name:
            return b
    return None


def bld_val(snap: dict, name: str) -> int:
    b = building(snap, name)
    return int(b["val"]) if b else 0


def tech(snap: dict, name: str) -> dict | None:
    for t in snap.get("science", {}).get("techs", []):
        if t["name"] == name:
            return t
    return None


def tech_researched(snap: dict, name: str) -> bool:
    t = tech(snap, name)
    return bool(t and t["researched"])


def upgrade(snap: dict, name: str) -> dict | None:
    for u in snap.get("workshop", {}).get("upgrades", []):
        if u["name"] == name:
            return u
    return None


def craft_recipe(snap: dict, name: str) -> dict | None:
    for c in snap.get("workshop", {}).get("crafts", []):
        if c["name"] == name:
            return c
    return None


def races(snap: dict) -> list[dict]:
    """Freigeschaltete Handelspartner aus der Diplomacy-Sektion."""
    return snap.get("diplomacy", {}).get("races", [])


def race(snap: dict, name: str) -> dict | None:
    for r in races(snap):
        if r["name"] == name:
            return r
    return None


def job_count(snap: dict, name: str) -> int:
    for j in snap.get("village", {}).get("jobs", []):
        if j["name"] == name:
            return int(j["value"])
    return 0


def job_unlocked(snap: dict, name: str) -> bool:
    return any(j["name"] == name for j in snap.get("village", {}).get("jobs", []))


# ------------------------------------------------------------------ Preise / ETA

def missing_for(snap: dict, prices: list[dict]) -> list[dict]:
    """Fehlende Mengen je Ressource für einen Preisvektor."""
    out = []
    for p in prices:
        have = res_value(snap, p["name"])
        if have + 1e-9 < p["val"]:
            out.append({"name": p["name"], "missing": p["val"] - have, "need": p["val"]})
    return out


def affordable(snap: dict, prices: list[dict]) -> bool:
    return not missing_for(snap, prices)


def eta_to_afford(snap: dict, prices: list[dict]) -> tuple[float, str | None]:
    """(Sekunden bis leistbar, Engpass-Ressource). math.inf wenn Rate ≤ 0.

    Prüft zusätzlich, ob das Cap die Zielmenge überhaupt zulässt —
    dann ist die ETA ebenfalls unendlich (Storage-Gate, Spec 11.3 A).
    """
    worst = 0.0
    bottleneck = None
    for m in missing_for(snap, prices):
        cap = res_cap(snap, m["name"])
        if 0 < cap < m["need"]:
            return math.inf, m["name"]        # Cap blockiert das Ziel
        rate = res_rate(snap, m["name"])
        if rate <= RATE_EPS:
            return math.inf, m["name"]
        eta = m["missing"] / rate
        if eta > worst:
            worst, bottleneck = eta, m["name"]
    return worst, bottleneck


def cap_blocks(snap: dict, prices: list[dict]) -> str | None:
    """Liefert die Ressource, deren Cap den Preisvektor unmöglich macht."""
    for p in prices:
        cap = res_cap(snap, p["name"])
        if 0 < cap < p["val"]:
            return p["name"]
    return None
