"""Testhelfer: baut minimale, aber vollständige Snapshots für Brain-Unit-Tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from player.state.derived import derive

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    """Golden-Fixture laden (Spec 24.1): eingefrorener Snapshot als JSON,
    deterministisch und ohne Zeitstempel. `derived` wird beim Laden frisch
    berechnet (nicht in der Datei — eine Ableitungsänderung soll die
    Fixtures nicht invalidieren, nur die Golden-Assertions)."""
    snap = json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    snap.pop("derived", None)
    return derive(snap)


def make_snap(
    resources: dict[str, dict] | None = None,
    buildings: dict[str, dict] | None = None,
    techs: dict[str, dict] | None = None,
    jobs: dict[str, int | dict] | None = None,
    free_kittens: int = 0,
    kittens: int = 0,
    max_kittens: int = 0,
    season: str = "spring",
    catnip_field_base: float = 0.0,
    crafts: list[dict] | None = None,
    races: list[dict] | None = None,
    trade_ratio: float = 0.0,
    standing_ratio: float = 0.0,
    policies: list[dict] | None = None,
    challenges: list[dict] | None = None,
    religion: dict | None = None,
    pacts: dict | None = None,
    kittens_per_sec: float = 0.0,
    pollution: dict | None = None,
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
        entry = {
            "name": name, "label": spec.get("label", name.capitalize()),
            "val": spec.get("val", 0), "on": spec.get("on", spec.get("val", 0)),
            "unlocked": spec.get("unlocked", True),
            "prices": [{"name": k, "val": v} for k, v in spec.get("prices", {}).items()],
        }
        # Effekt-Dict wie snapshot.js (#35): nur setzen, wenn der Test es
        # übergibt — ohne Key greift der Beobachtungs-Fallback (Alt-Tests).
        if spec.get("effects") is not None:
            entry["effects"] = dict(spec["effects"])
        bld_list.append(entry)
    tech_list = []
    for name, spec in (techs or {}).items():
        tech_list.append({
            "name": name, "label": spec.get("label", name.capitalize()),
            "researched": spec.get("researched", False),
            "unlocked": spec.get("unlocked", True),
            "prices": [{"name": k, "val": v} for k, v in spec.get("prices", {}).items()],
        })
    # Jobs: int (alt, ohne ratesPerKitten → Python-Fallback JOB_BASE_RATES)
    # oder dict {"value": n, "rates": {...}} → beobachtete Marginalraten
    # ratesPerKitten wie aus snapshot.js (#40).
    job_list = []
    for n, v in (jobs or {}).items():
        if isinstance(v, dict):
            entry = {"name": n, "title": n.capitalize(),
                     "value": v.get("value", 0)}
            if "rates" in v:
                entry["ratesPerKitten"] = dict(v["rates"])
            job_list.append(entry)
        else:
            job_list.append({"name": n, "title": n.capitalize(), "value": v})

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
            # Kitten-Ankunftsrate (#36, Format wie snapshot.js): Default 0
            # hält Alt-Tests bitidentisch (keine Ankünfte, keine Mehrlast).
            "kittensPerSec": kittens_per_sec,
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
    # Optionale Policy-Daten (Format wie snapshot.js `policies`): nur setzen,
    # wenn der Test sie übergibt — Alt-Tests bleiben unverändert (kein Key).
    if policies is not None:
        snap["policies"] = [{
            "name": p["name"],
            "label": p.get("label", p["name"].capitalize()),
            "researched": p.get("researched", False),
            "blocked": p.get("blocked", False),
            "unlocked": p.get("unlocked", True),
            "blocks": p.get("blocks", []),
            "prices": [{"name": k, "val": v}
                       for k, v in p.get("prices", {}).items()],
        } for p in policies]
    # Optionale Religion-Daten (Format wie snapshot.js `religion`): der Test
    # übergibt nur die Keys, die er braucht — sie werden über die Minimal-
    # Religion gelegt. Alt-Tests bleiben unverändert (kein Parameter).
    if religion is not None:
        rel = {"worship": 0, "epiphany": 0.0, "faith": 0.0,
               "transcendenceTier": 0, "upgrades": [], "ziggurat": []}
        rel.update(religion)
        snap["religion"] = rel
    # Optionale Pact-Daten (Format wie snapshot.js `pacts`): Default = Key
    # fehlt komplett (Pact-Schicht nicht erreicht, Spec 15.5 inaktiv).
    if pacts is not None:
        lst = [{
            "name": p["name"],
            "label": p.get("label", p["name"]),
            "val": p.get("val", 0), "on": p.get("on", p.get("val", 0)),
            "unlocked": p.get("unlocked", True),
            "special": p.get("special", False),
            "prices": [{"name": k, "val": v}
                       for k, v in p.get("prices", {"relic": 100}).items()],
        } for p in pacts.get("list", [])]
        snap["pacts"] = {
            "list": lst,
            "necrocorns": pacts.get("necrocorns", 0.0),
            "necrocornDeficit": pacts.get("necrocornDeficit", 0.0),
            "pactsAvailable": pacts.get("pactsAvailable", 0),
            "necrocornPerDay": pacts.get("necrocornPerDay", 0.0),
            "necrocornUpfrontCost": pacts.get("necrocornUpfrontCost", 0.0),
            "siphoning": pacts.get("siphoning", False),
            "fractured": pacts.get("fractured", False),
            "deficitPenaltyRatio": pacts.get("deficitPenaltyRatio", 1.0),
        }
    # Optionale Pollution-Daten (Format wie snapshot.js `pollution`, #35):
    # Default = Key fehlt komplett (Pollution-Term inaktiv, Fallback 0).
    if pollution is not None:
        snap["pollution"] = {
            "cathPollution": pollution.get("cathPollution", 0.0),
            "arrivalSlowdown": pollution.get("arrivalSlowdown", 0.0),
        }
    # Optionale Challenge-Daten (Format wie snapshot.js `challenges`):
    if challenges is not None:
        lst = [{
            "name": c["name"],
            "label": c.get("label", c["name"].capitalize()),
            "researched": c.get("researched", False),
            "on": c.get("on", 0),
            "unlocked": c.get("unlocked", True),
            "active": c.get("active", False),
            "pending": c.get("pending", False),
        } for c in challenges]
        snap["challenges"] = {
            "list": lst,
            "anyActive": any(c["active"] for c in lst),
            "countPending": sum(1 for c in lst if c["pending"]),
            "reservesExist": False,
        }
    return derive(snap)
