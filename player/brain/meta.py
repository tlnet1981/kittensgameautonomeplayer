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


def _tech_visible(name: str) -> Callable[[dict], bool]:
    """Tech ist im Spiel sichtbar/erforschbar (Vorgänger erforscht)."""
    return lambda snap: A.tech(snap, name) is not None


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
    # --- M2/M4: Handel, Schrift, Religion-Basis (Reihenfolge = echte
    #     Unlock-Kette der Referenzversion, siehe docs/game-api.md) ---
    Milestone("tradepost_1", "Handelsposten bauen", _bld(1, "tradepost"),
              {"kind": "build", "name": "tradepost"},
              visible=_tech("currency")),
    Milestone("engineering", "Engineering erforschen", _tech("engineering"),
              {"kind": "research", "name": "engineering"},
              visible=_tech_visible("engineering")),
    Milestone("writing", "Writing erforschen", _tech("writing"),
              {"kind": "research", "name": "writing"},
              visible=_tech_visible("writing")),
    Milestone("philosophy", "Philosophy erforschen", _tech("philosophy"),
              {"kind": "research", "name": "philosophy"},
              visible=_tech_visible("philosophy")),
    # Der ERSTE Handelspartner kommt automatisch per Emissär (Jahr 20; früher
    # mit Karma/Diplomacy-Perk, diplomacy.js:336) — kein aktives Ziel nötig.
    # Der Meilenstein wird erst kurz davor sichtbar, damit er die Kette nicht
    # blockiert; weitere Rassen findet der Kundschafter-Kandidat (tactics).
    Milestone("explore_race", "Erster Handelspartner (Emissär)",
              lambda snap: len(snap.get("diplomacy", {}).get("races", [])) > 0,
              None,
              visible=lambda snap: snap.get("calendar", {}).get("year", 0) >= 19),
    Milestone("theology", "Theology erforschen (Religion!)", _tech("theology"),
              {"kind": "research", "name": "theology"},
              visible=_tech_visible("theology")),
    Milestone("temple_1", "Ersten Tempel bauen", _bld(1, "temple"),
              {"kind": "build", "name": "temple"},
              visible=_tech("theology")),
    Milestone("hut_4", "Viertes Zuhause", _bld(4, "hut"),
              {"kind": "build", "name": "hut"},
              visible=_bld_visible("hut")),
    Milestone("amphitheatre_1", "Amphitheater bauen (Happiness)", _bld(1, "amphitheatre"),
              {"kind": "build", "name": "amphitheatre"},
              visible=_tech("construction")),
    Milestone("astronomy", "Astronomy erforschen", _tech("astronomy"),
              {"kind": "research", "name": "astronomy"},
              visible=_tech_visible("astronomy")),
    Milestone("navigation", "Navigation erforschen", _tech("navigation"),
              {"kind": "research", "name": "navigation"},
              visible=_tech_visible("navigation")),
    # --- M4: Kultur-Komfort + Weg zu Rocketry & Mond (Spec 16.1) ---
    Milestone("architecture", "Architecture erforschen", _tech("architecture"),
              {"kind": "research", "name": "architecture"},
              visible=_tech_visible("architecture")),
    Milestone("acoustics", "Acoustics erforschen", _tech("acoustics"),
              {"kind": "research", "name": "acoustics"},
              visible=_tech_visible("acoustics")),
    Milestone("drama", "Drama and Poetry erforschen (Festivals!)", _tech("drama"),
              {"kind": "research", "name": "drama"},
              visible=_tech_visible("drama")),
    Milestone("steel_tech", "Steel erforschen", _tech("steel"),
              {"kind": "research", "name": "steel"},
              visible=_tech_visible("steel")),
    Milestone("machinery", "Machinery erforschen", _tech("machinery"),
              {"kind": "research", "name": "machinery"},
              visible=_tech_visible("machinery")),
    Milestone("physics", "Physics erforschen", _tech("physics"),
              {"kind": "research", "name": "physics"},
              visible=_tech_visible("physics")),
    Milestone("steamworks_1", "Steamworks bauen (Energie!)", _bld(1, "steamworks"),
              {"kind": "build", "name": "steamworks"},
              visible=_bld_visible("steamworks")),
    Milestone("chemistry", "Chemistry erforschen (Öl!)", _tech("chemistry"),
              {"kind": "research", "name": "chemistry"},
              visible=_tech_visible("chemistry")),
    Milestone("electricity", "Electricity erforschen", _tech("electricity"),
              {"kind": "research", "name": "electricity"},
              visible=_tech_visible("electricity")),
    Milestone("oilwell_1", "Ölquelle erschließen", _bld(1, "oilWell"),
              {"kind": "build", "name": "oilWell"},
              visible=_bld_visible("oilWell")),
    Milestone("magneto_1", "Magneto bauen (Energie)", _bld(1, "magneto"),
              {"kind": "build", "name": "magneto"},
              visible=_bld_visible("magneto")),
    Milestone("archeology", "Archeology erforschen (Geologen)", _tech("archeology"),
              {"kind": "research", "name": "archeology"},
              visible=_tech_visible("archeology")),
    Milestone("industrialization", "Industrialization erforschen", _tech("industrialization"),
              {"kind": "research", "name": "industrialization"},
              visible=_tech_visible("industrialization")),
    Milestone("mechanization", "Mechanization erforschen", _tech("mechanization"),
              {"kind": "research", "name": "mechanization"},
              visible=_tech_visible("mechanization")),
    Milestone("electronics", "Electronics erforschen", _tech("electronics"),
              {"kind": "research", "name": "electronics"},
              visible=_tech_visible("electronics")),
    Milestone("rocketry", "Rocketry erforschen — der Weltraum ruft!", _tech("rocketry"),
              {"kind": "research", "name": "rocketry"},
              visible=_tech_visible("rocketry")),
    Milestone("orbital_launch", "Orbital Launch — erster Raketenstart!",
              lambda snap: _space_program_val(snap, "orbitalLaunch") >= 1,
              {"kind": "space_program", "name": "orbitalLaunch"},
              visible=_tech("rocketry")),
    Milestone("moon_mission", "Mond-Mission!",
              lambda snap: _space_program_val(snap, "moonMission") >= 1,
              {"kind": "space_program", "name": "moonMission"},
              visible=lambda snap: _space_program_val(snap, "orbitalLaunch") >= 1),
]


def _space_program_val(snap: dict, name: str) -> int:
    for p in snap.get("space", {}).get("programs", []):
        if p["name"] == name:
            return int(p.get("val", 0))
    return 0


# Feste frühe Metaphysics-Reihenfolge (Spec 9.1). Hinweis: das Spec-Wort
# „Enlightenment" heißt in v1.5.0.2 „engeneering" (sic, -1 % Price Ratio).
METAPHYSICS_ORDER = [
    "engeneering", "diplomacy", "goldenRatio",
    "divineProportion", "vitruvianFeline", "renaissance",
]


def next_metaphysics_target(snap: dict) -> dict | None:
    """Nächster unerforschter Perk der festen Reihenfolge (oder None)."""
    perks = {p["name"]: p for p in snap.get("prestige", {}).get("perks", [])}
    for name in METAPHYSICS_ORDER:
        p = perks.get(name)
        if p is None:
            # Perk noch nicht im Snapshot (nicht unlocked) — Standardpreise
            # der Referenzversion, damit die Reset-Planung rechnen kann:
            defaults = {"engeneering": 5, "diplomacy": 5, "goldenRatio": 50,
                        "divineProportion": 100, "vitruvianFeline": 250,
                        "renaissance": 750}
            return {"name": name, "label": name, "researched": False,
                    "unlocked": False,
                    "prices": [{"name": "paragon", "val": defaults[name]}]}
        if not p["researched"]:
            return p
    return None


def determine_run(snap: dict) -> str:
    """Run-Typ aus dem persistenten Zustand ableiten (Spec 8.2, M3-Umfang)."""
    prestige = snap.get("prestige", {})
    persistent = (prestige.get("paragon", 0) + prestige.get("burnedParagon", 0)
                  + prestige.get("karma", 0))
    any_perk = any(p["researched"] for p in prestige.get("perks", []))
    if persistent <= 0 and not any_perk:
        return "FIRST_RUN"
    if next_metaphysics_target(snap) is not None:
        return "PRICE_RATIO_RUN"
    return "CORE_META_RUN"   # weitere Run-Typen folgen mit M4–M7


@dataclass
class MetaView:
    phase: str
    run_type: str
    active: Milestone | None
    milestones: list[dict]      # fürs Cockpit: [{id,label,state}]
    next_perk: dict | None = None

    @property
    def objective_label(self) -> str:
        return self.active.label if self.active else "Wirtschaft ausbauen (Frontier erschöpft in M1)"

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "runType": self.run_type,
            "objective": self.objective_label,
            "milestones": self.milestones,
            "nextPerk": ({"name": self.next_perk["name"],
                          "label": self.next_perk.get("label") or self.next_perk["name"],
                          "prices": self.next_perk.get("prices", [])}
                         if self.next_perk else None),
        }


def _perk_milestones(snap: dict, next_perk: dict | None) -> list[Milestone]:
    """Zusätzliche Meilensteine für Price-Ratio-Runs (Metaphysics-Kauf)."""
    if next_perk is None:
        return []
    out = [Milestone("metaphysics", "Metaphysics erforschen",
                     _tech("metaphysics"),
                     {"kind": "research", "name": "metaphysics"},
                     visible=_tech("philosophy"))]
    label = next_perk.get("label") or next_perk["name"]
    out.append(Milestone(f"perk_{next_perk['name']}", f"Metaphysics: {label} kaufen",
                         lambda s: False,   # erledigt sich über next_perk-Wechsel
                         {"kind": "perk", "name": next_perk["name"]},
                         visible=_tech("metaphysics")))
    return out


def evaluate(snap: dict) -> MetaView:
    """Bestimmt Phase, Run-Typ und den aktiven Meilenstein."""
    run_type = determine_run(snap)
    next_perk = next_metaphysics_target(snap)
    milestones = list(P0_MILESTONES)
    # Phasen (Spec Kap. 9): P0 Erstwirtschaft, P1 Price-Ratio, P2 Core Meta & Space
    phase = "P0"
    if run_type == "PRICE_RATIO_RUN":
        phase = "P1"
        milestones = milestones + _perk_milestones(snap, next_perk)
    if A.tech_researched(snap, "rocketry"):
        phase = "P2"

    active: Milestone | None = None
    rows: list[dict] = []
    for m in milestones:
        if m.done(snap):
            state = "done"
        elif active is None and m.visible(snap):
            state = "active"
            active = m
        else:
            state = "pending"
        rows.append({"id": m.id, "label": m.label, "state": state})
    return MetaView(phase=phase, run_type=run_type, active=active,
                    milestones=rows, next_perk=next_perk)
