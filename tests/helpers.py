"""Testhelfer: baut minimale, aber vollständige Snapshots für Brain-Unit-Tests."""

from __future__ import annotations

from typing import Any

from player.state.derived import derive


def make_snap(
    resources: dict[str, dict] | None = None,
    buildings: dict[str, dict] | None = None,
    techs: dict[str, dict] | None = None,
    jobs: dict[str, int] | None = None,
    free_kittens: int = 0,
    kittens: int = 0,
    max_kittens: int = 0,
    season: str = "spring",
    catnip_field_base: float = 0.0,
    crafts: list[dict] | None = None,
    races: list[dict] | None = None,
    trade_ratio: float = 0.0,
    standing_ratio: float = 0.0,
) -> dict[str, Any]:
    """Erzeugt einen Snapshot im Format von driver/snapshot.js (inkl. derived)."""
    res_list = []
    for name, spec in (resources or {}).items():
        res_list.append({
            "name": name, "title": spec.get("title", name),
            "value": spec.get("value", 0.0), "maxValue": spec.get("max", 0.0),
            "craftable": spec.get("craftable", False), "unlocked": True,
            "perSec": spec.get("rate", 0.0),
        })
    bld_list = []
    for name, spec in (buildings or {}).items():
        bld_list.append({
            "name": name, "label": spec.get("label", name.capitalize()),
            "val": spec.get("val", 0), "on": spec.get("val", 0),
            "unlocked": spec.get("unlocked", True),
            "prices": [{"name": k, "val": v} for k, v in spec.get("prices", {}).items()],
        })
    tech_list = []
    for name, spec in (techs or {}).items():
        tech_list.append({
            "name": name, "label": spec.get("label", name.capitalize()),
            "researched": spec.get("researched", False),
            "unlocked": spec.get("unlocked", True),
            "prices": [{"name": k, "val": v} for k, v in spec.get("prices", {}).items()],
        })
    job_list = [{"name": n, "title": n.capitalize(), "value": v} for n, v in (jobs or {}).items()]

    season_mod = {"spring": 1.5, "summer": 1.0, "autumn": 1.0, "winter": 0.25}[season]
    snap = {
        "ready": True, "errors": [],
        "meta": {"version": "1502", "buildRevision": 3, "paused": False, "ticksPerSecond": 5},
        "calendar": {
            "year": 1,
            "season": ["spring", "summer", "autumn", "winter"].index(season),
            "seasonName": season, "day": 10, "daysPerSeason": 100,
            "weather": "normal", "cycle": 0, "cycleYear": 0, "festivalDays": 0,
            "winterCatnipModifier": 0.25, "currentCatnipModifier": season_mod,
            "seasonCatnipModifiers": [1.5, 1.0, 1.0, 0.25],
        },
        "resources": res_list,
        "village": {
            "kittens": kittens, "maxKittens": max_kittens, "freeKittens": free_kittens,
            "happiness": 1.0, "jobs": job_list, "leader": None,
            "catnipDemandPerSec": kittens * 0.85,
        },
        "buildings": bld_list,
        "science": {"techs": tech_list},
        "workshop": {"upgrades": [], "crafts": crafts or [], "craftRatio": 0},
        "energy": {"prod": 0, "cons": 0},
        "prestige": {"paragon": 0, "burnedParagon": 0, "karma": 0},
        "religion": {"faith": 0, "faithRatio": 0, "worship": 0},
        "effects": {"catnipPerTickBase": catnip_field_base / 5},
        "tabs": [],
    }
    # Optionale Diplomacy-Daten (Format wie snapshot.js): nur setzen, wenn
    # der Test races übergibt — Alt-Tests bleiben unverändert (kein Key).
    if races is not None:
        snap["diplomacy"] = {
            "undiscovered": False, "races": races,
            "standingRatio": standing_ratio, "tradeRatio": trade_ratio,
        }
    return derive(snap)
