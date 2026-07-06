"""Meta-Controller: Phase, Run-Typ und Meilenstein-Graph (Spec Kap. 8/9).

M1-Umfang: Run-Typ FIRST_RUN, Phase P0 mit fester, aber zustandsgeprüfter
Meilensteinliste. Die Liste ist kein starrer Build-Order-Zwang (Spec 9):
sie liefert dem taktischen Optimierer das jeweils aktive Ziel; alle
opportunistischen Aktionen (Jobs, Jagd, Crafts, günstige Upgrades) laufen
parallel über das Kandidaten-Scoring.

Ab M3 übernimmt hier die Run-Typ-Auswahl (PRICE_RATIO_RUN, ...).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from player.state import access as A


@dataclass
class Milestone:
    id: str
    label: str
    done: Callable[[dict], bool]
    # Ziel für die Taktik: {"kind": "build"|"research", "name": ...}
    target: dict[str, Any] | None = None
    # Meilenstein erst aktiv, wenn Voraussetzung sichtbar (sonst übersprungen):
    visible: Callable[[dict], bool] = lambda snap: True


def _bld(n: int, name: str) -> Callable[[dict], bool]:
    return lambda snap: A.bld_val(snap, name) >= n


def _tech(name: str) -> Callable[[dict], bool]:
    return lambda snap: A.tech_researched(snap, name)


def _bld_visible(name: str) -> Callable[[dict], bool]:
    """Gebäude ist im Spiel freigeschaltet (taucht im Snapshot auf)."""
    return lambda snap: A.building(snap, name) is not None


# ---------------------------------------------------------------- P0-Meilensteine
# Reihenfolge nach Spec 9 / Monstrous Advice: Food → Housing → Science →
# Storage → Jagd → Mining → Workshop → Metall → Akademie → Konstruktion.
P0_MILESTONES: list[Milestone] = [
    Milestone("field_1", "Erstes Catnip-Feld", _bld(1, "field"),
              {"kind": "build", "name": "field"}),
    Milestone("field_10", "Catnip-Farm (10 Felder)", _bld(10, "field"),
              {"kind": "build", "name": "field"}),
    # Holz existiert anfangs nur über „Refine catnip" — dieser Meilenstein
    # schaltet Hütte & Bibliothek im Spiel frei (Unlock-Schwellen ~1,5/7,5 Holz).
    Milestone("wood_first", "Erstes Holz veredeln",
              lambda snap: A.res_value(snap, "wood") >= 10
              or (A.building(snap, "hut") is not None and A.building(snap, "library") is not None),
              {"kind": "resource", "name": "wood", "amount": 10}),
    Milestone("hut_1", "Erste Hütte — Kitten anlocken", _bld(1, "hut"),
              {"kind": "build", "name": "hut"},
              visible=_bld_visible("hut")),
    Milestone("library_1", "Bibliothek bauen (Science!)", _bld(1, "library"),
              {"kind": "build", "name": "library"},
              visible=_bld_visible("library")),
    Milestone("calendar", "Calendar erforschen", _tech("calendar"),
              {"kind": "research", "name": "calendar"}),
    Milestone("agriculture", "Agriculture erforschen (Farmer)", _tech("agriculture"),
              {"kind": "research", "name": "agriculture"}),
    Milestone("field_15", "Felder ausbauen (15)", _bld(15, "field"),
              {"kind": "build", "name": "field"}),
    Milestone("hut_2", "Zweite Hütte", _bld(2, "hut"),
              {"kind": "build", "name": "hut"},
              visible=_bld_visible("hut")),
    Milestone("barn_1", "Erste Scheune (Storage)", _bld(1, "barn"),
              {"kind": "build", "name": "barn"},
              visible=_tech("agriculture")),
    Milestone("archery", "Archery erforschen (Jäger)", _tech("archery"),
              {"kind": "research", "name": "archery"}),
    Milestone("mining", "Mining erforschen", _tech("mining"),
              {"kind": "research", "name": "mining"}),
    Milestone("workshop_1", "Workshop bauen (Crafts!)", _bld(1, "workshop"),
              {"kind": "build", "name": "workshop"},
              visible=_tech("mining")),
    Milestone("mine_1", "Erste Mine", _bld(1, "mine"),
              {"kind": "build", "name": "mine"},
              visible=_tech("mining")),
    Milestone("hut_3", "Drittes Zuhause", _bld(3, "hut"),
              {"kind": "build", "name": "hut"},
              visible=_bld_visible("hut")),
    Milestone("metal", "Metal Working erforschen", _tech("metal"),
              {"kind": "research", "name": "metal"}),
    Milestone("smelter_1", "Schmelze bauen (Iron)", _bld(1, "smelter"),
              {"kind": "build", "name": "smelter"},
              visible=_tech("metal")),
    Milestone("animal", "Animal Husbandry erforschen", _tech("animal"),
              {"kind": "research", "name": "animal"}),
    Milestone("pasture_1", "Erste Weide (Catnip-Entlastung)", _bld(1, "pasture"),
              {"kind": "build", "name": "pasture"},
              visible=_tech("animal")),
    Milestone("math", "Mathematics erforschen", _tech("math"),
              {"kind": "research", "name": "math"}),
    Milestone("academy_1", "Akademie bauen", _bld(1, "academy"),
              {"kind": "build", "name": "academy"},
              visible=_tech("math")),
    Milestone("construction", "Construction erforschen", _tech("construction"),
              {"kind": "research", "name": "construction"}),
    Milestone("lumbermill_1", "Sägewerk bauen", _bld(1, "lumberMill"),
              {"kind": "build", "name": "lumberMill"},
              visible=_tech("construction")),
    Milestone("warehouse_1", "Lagerhaus bauen", _bld(1, "warehouse"),
              {"kind": "build", "name": "warehouse"},
              visible=_tech("construction")),
    Milestone("civil", "Civil Service erforschen", _tech("civil"),
              {"kind": "research", "name": "civil"}),
    Milestone("currency", "Currency erforschen (Handel naht)", _tech("currency"),
              {"kind": "research", "name": "currency"}),
]


@dataclass
class MetaView:
    phase: str
    run_type: str
    active: Milestone | None
    milestones: list[dict]      # fürs Cockpit: [{id,label,state}]

    @property
    def objective_label(self) -> str:
        return self.active.label if self.active else "Wirtschaft ausbauen (Frontier erschöpft in M1)"

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "runType": self.run_type,
            "objective": self.objective_label,
            "milestones": self.milestones,
        }


def evaluate(snap: dict) -> MetaView:
    """Bestimmt Phase, Run-Typ und den aktiven Meilenstein."""
    active: Milestone | None = None
    rows: list[dict] = []
    for m in P0_MILESTONES:
        if m.done(snap):
            state = "done"
        elif active is None and m.visible(snap):
            state = "active"
            active = m
        else:
            state = "pending"
        rows.append({"id": m.id, "label": m.label, "state": state})
    return MetaView(phase="P0", run_type="FIRST_RUN", active=active, milestones=rows)
