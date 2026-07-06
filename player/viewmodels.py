"""View-Models für das Cockpit (Cockpit-Spec Kap. 22.1, reduziert).

Das Frontend rendert ausschließlich diese Strukturen — es greift nie direkt
auf Spiel- oder Engine-Interna zu. Alle Werte sind JSON-serialisierbar.
"""

from __future__ import annotations

import time
from typing import Any

SEASON_LABELS = {"spring": "Frühling", "summer": "Sommer", "autumn": "Herbst", "winter": "Winter"}


def status_vm(snap: dict, agent_state: str, version_guard: dict | None, run_info: dict | None = None) -> dict:
    cal = snap.get("calendar", {})
    village = snap.get("village", {})
    return {
        "agentState": agent_state,
        "versionGuard": version_guard or {},
        "calendar": {
            "year": cal.get("year"),
            "season": SEASON_LABELS.get(cal.get("seasonName", ""), cal.get("seasonName", "?")),
            "day": cal.get("day"),
            "cycle": cal.get("cycle"),
        },
        "kittens": village.get("kittens", 0),
        "maxKittens": village.get("maxKittens", 0),
        "paragon": snap.get("prestige", {}).get("paragon", 0),
        "resetParagon": snap.get("derived", {}).get("resetParagon", 0),
        "run": run_info or {"type": "FIRST_RUN", "phase": "P0", "objective": None},
        "generatedAt": time.time(),
    }


def economy_vm(snap: dict) -> dict:
    derived = snap.get("derived", {}).get("resources", {})
    rows = []
    for r in snap.get("resources", []):
        dr = derived.get(r["name"], {})
        rows.append({
            "name": r["name"],
            "title": r["title"],
            "value": r["value"],
            "maxValue": r["maxValue"],
            "perSec": r["perSec"],
            "craftable": r["craftable"],
            "fillTime": dr.get("fillTime"),
            "depletionTime": dr.get("depletionTime"),
            "pctFull": dr.get("pctFull"),
        })
    food = snap.get("derived", {}).get("food", {})
    energy = snap.get("derived", {}).get("energy", {})
    return {"resources": rows, "food": food, "energy": energy}


def population_vm(snap: dict) -> dict:
    v = snap.get("village", {})
    return {
        "kittens": v.get("kittens", 0),
        "maxKittens": v.get("maxKittens", 0),
        "freeKittens": v.get("freeKittens", 0),
        "happiness": v.get("happiness", 1.0),
        "jobs": v.get("jobs", []),
        "leader": v.get("leader"),
    }


def systems_vm(snap: dict) -> dict:
    """SystemDomainVM (Spec 22.1): Space, Handel, Religion — wächst mit M4–M6."""
    space = snap.get("space", {})
    return {
        "space": {
            "programs": [{"name": p["name"], "label": p["label"], "val": p["val"]}
                         for p in space.get("programs", [])],
            "planets": [{"label": pl["label"],
                         "buildings": [{"label": b["label"], "val": b["val"]}
                                       for b in pl.get("buildings", []) if b["val"] > 0]}
                        for pl in space.get("planets", [])],
        },
        "races": [r["title"] for r in snap.get("diplomacy", {}).get("races", [])],
        "energy": snap.get("derived", {}).get("energy", {}),
        "faith": snap.get("religion", {}),
    }


def health_vm(agent_state: str, snapshot_age: float | None, errors: list[str]) -> dict:
    return {
        "agentState": agent_state,
        "snapshotAge": snapshot_age,
        "dataFresh": snapshot_age is not None and snapshot_age < 5.0,
        "errors": errors[-10:],
    }
