"""Sicherheitsinvarianten (Spielmechanik-Spec Kap. 7): Food-Invariante I-01.

Grundlage ist die Catnip-SAISONPROJEKTION (state/derived.py, Spec 7.2):
kritisch ist der Zustand nur, wenn der projizierte Bestands-Tiefpunkt bis
zum Ende des nächsten Winters unter die Überlebensschwelle fällt.

Design nach dem Schleifen-Bugfix: Safety ist eine **Leitplanke, kein
Monopol**. Sie liefert abgestufte Schutz-KANDIDATEN, die mit allen anderen
Aktionen konkurrieren — food-neutrale Fortschritte (Forschung kostet nur
Science!) laufen weiter. Zusätzlich blockiert sie food-schädliche Aktionen
über blocked_types/foodRisk (tactics.py):

    Schutzkandidaten (nur bei Status critical):
      6.0  Farmer zuweisen / größten Job zu Farmer umschulen (kostenlos, sofort)
      4.0  Catnip-Feld bauen — NUR wenn der Kauf die Projektion nachweislich
           verbessert (Preis senkt den Bestand, Rate hebt den Winter)
      1.2  Catnip sammeln (ehrlich schwach: ~50 Catnip pro Charge)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from player.state import access as A
from player.state.derived import CATNIP_PER_FIELD_PER_SEC, project_catnip
from . import actions
from .records import Candidate


@dataclass
class SafetyResult:
    ok: bool = True                      # False = Food-Status kritisch
    critical: bool = False
    candidates: list = field(default_factory=list)   # abgestufte Schutzaktionen
    reason: str = ""
    blocked_types: set[str] = field(default_factory=set)   # z. B. {"housing"}
    view: dict = field(default_factory=dict)                # fürs Cockpit


def check(snap: dict) -> SafetyResult:
    food = snap.get("derived", {}).get("food", {})
    status = food.get("status", "ok")
    result = SafetyResult()
    result.view = {"food": dict(food)}

    if status == "ok":
        return result

    # Warnstufe: kein Housing (neue Kitten = mehr Verbrauch im knappen Winter).
    result.blocked_types.add("housing")

    if status != "critical":
        return result

    result.ok = False
    result.critical = True
    result.reason = (f"Winter-Projektion fällt auf {food.get('projectedMin', 0):.0f} Catnip "
                     f"(Grenze {food.get('criticalFloor', 0):.0f})")
    result.candidates = _protective_candidates(snap, food)
    return result


def _protective_candidates(snap: dict, food: dict) -> list[Candidate]:
    out: list[Candidate] = []
    village = snap.get("village", {})
    free = village.get("freeKittens", 0)

    # 1. Farmer: kostenlos und wirkt sofort auf die Winterrate.
    if A.job_unlocked(snap, "farmer"):
        if free > 0:
            out.append(Candidate(
                actions.assign_job("farmer", "Farmer", amount=min(free, 2)),
                6.0, {"safety": 6.0}))
        else:
            donors = [j for j in village.get("jobs", [])
                      if j["name"] != "farmer" and j["value"] > 0]
            if donors:
                biggest = max(donors, key=lambda j: (j["value"], j["name"]))
                out.append(Candidate(
                    actions.shift_job(biggest["name"], "farmer", "Farmer", 1),
                    6.0, {"safety": 6.0}))

    # 2. Feld bauen — Wirkungsprüfung (Fix der Kauf-und-wieder-arm-Schleife):
    #    Der Kauf kostet Bestand (= Reserve), hebt aber die Winterrate.
    #    Nur bauen, wenn die Projektion NACH dem Kauf besser ist als vorher.
    field_b = A.building(snap, "field")
    if field_b and A.affordable(snap, field_b["prices"]):
        price = sum(p["val"] for p in field_b["prices"] if p["name"] == "catnip")
        after = project_catnip(snap, stock_delta=-price,
                               field_rate_delta=CATNIP_PER_FIELD_PER_SEC)
        if after["projectedMin"] > food.get("projectedMin", 0):
            out.append(Candidate(
                actions.buy_building("field", field_b["label"], field_b["val"]),
                4.0, {"safety": 4.0}))
        else:
            out.append(Candidate(
                actions.buy_building("field", field_b["label"], field_b["val"]),
                0.0, {"safety": 0.0}, feasible=False,
                reject_reason=(f"Feldkauf würde die Winter-Projektion verschlechtern "
                               f"({after['projectedMin']:.0f} < {food.get('projectedMin', 0):.0f})")))

    # 3. Sammeln: letzter Ausweg, bewusst schwach bewertet — food-neutrale
    #    Fortschritte (Forschung 1.9–3.0) gewinnen dagegen.
    out.append(Candidate(actions.gather_catnip(batch=20), 1.2, {"safety": 1.2}))
    return out
