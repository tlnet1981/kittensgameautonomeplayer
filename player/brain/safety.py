"""Sicherheitsinvarianten (Spielmechanik-Spec Kap. 7, M1: Food-Invariante I-01).

Safety hat Vorrang vor Nutzenoptimierung (Grundentscheidung G-04):
Wenn die Worst-Winter-Catnip-Reserve unter den Sicherungshorizont fällt,
wird ausschließlich die Schutzaktion ausgeführt und Housing blockiert.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from player.state import access as A
from . import actions


# Sicherungshorizont (Spec 7.2, vereinfacht): unter dieser Worst-Winter-Reserve
# greift die Schutzlogik. Kalibrierung: ein kompletter Winter dauert ~200 s
# Realzeit — 5 Minuten Reserve decken also mehr als einen vollen Winter ab.
RESERVE_FLOOR_SECONDS = 5 * 60
# Oberhalb dieser Reserve gilt Food als "komfortabel" — Housing wieder erlaubt.
RESERVE_COMFORT_SECONDS = 10 * 60


@dataclass
class SafetyResult:
    ok: bool = True
    action: actions.Action | None = None      # Schutzaktion (hat höchste Priorität)
    reason: str = ""
    blocked_types: set[str] = field(default_factory=set)   # z. B. {"housing"}
    view: dict = field(default_factory=dict)                # fürs Cockpit


def check(snap: dict) -> SafetyResult:
    food = snap.get("derived", {}).get("food", {})
    reserve = food.get("reserveSeconds")
    worst_net = food.get("worstWinterNetPerSec", 0.0)
    result = SafetyResult()
    result.view = {
        "food": {
            "reserveSeconds": reserve,
            "worstWinterNetPerSec": worst_net,
            "floor": RESERVE_FLOOR_SECONDS,
            "status": "ok",
        }
    }

    # Reserve None bedeutet: Worst-Winter-Netto ist positiv -> sicher.
    if reserve is None:
        return result

    if reserve < RESERVE_COMFORT_SECONDS:
        # Vorwarnstufe: kein Housing mehr (neue Kitten würden Verbrauch erhöhen).
        result.blocked_types.add("housing")
        result.view["food"]["status"] = "warn"

    if reserve < RESERVE_FLOOR_SECONDS:
        result.ok = False
        result.view["food"]["status"] = "critical"
        result.reason = (f"Worst-Winter-Catnip-Reserve nur {reserve / 60:.1f} min "
                         f"(Grenze {RESERVE_FLOOR_SECONDS / 60:.0f} min)")
        result.action = _protective_action(snap)
    return result


def _protective_action(snap: dict) -> actions.Action | None:
    """Wählt die beste Schutzaktion: Farmer aufstocken oder Felder bauen."""
    village = snap.get("village", {})
    free = village.get("freeKittens", 0)

    # 1. Freie Kitten zum Farmer machen (falls Job freigeschaltet).
    if A.job_unlocked(snap, "farmer") and free > 0:
        return actions.assign_job("farmer", "Farmer", amount=min(free, 2))

    # 2. Kitten aus dem größten Nicht-Farmer-Job abziehen.
    if A.job_unlocked(snap, "farmer"):
        jobs = [j for j in village.get("jobs", []) if j["name"] != "farmer" and j["value"] > 0]
        if jobs:
            biggest = max(jobs, key=lambda j: j["value"])
            return actions.shift_job(biggest["name"], "farmer", "Farmer", amount=1)

    # 3. Freie Kitten sind food-neutral (sie essen sowieso) — auf den
    #    strategischen Fluchtweg setzen: Holz → Library → Agriculture → Farmer.
    #    (Einmalige Maßnahme; danach greifen die Feld-Schritte weiter.)
    if free > 0 and A.job_unlocked(snap, "woodcutter"):
        return actions.assign_job("woodcutter", "Woodcutter", amount=free)

    # 4. Kein Farmer-Job (noch keine Agriculture): Catnip-Feld bauen, wenn leistbar.
    field_b = A.building(snap, "field")
    if field_b and A.affordable(snap, field_b["prices"]):
        return actions.buy_building("field", field_b["label"], field_b["val"])

    # 5. Letzter Ausweg: Catnip von Hand sammeln.
    return actions.gather_catnip(batch=20)
