"""Meta-Controller: Phase, Run-Typ und Meilenstein-Graph (Spec Kap. 8/9).

M1-Umfang: Run-Typ FIRST_RUN, Phase P0 mit fester, aber zustandsgeprüfter
Meilensteinliste. Die Liste ist kein starrer Build-Order-Zwang (Spec 9):
sie liefert dem taktischen Optimierer das jeweils aktive Ziel; alle
opportunistischen Aktionen (Jobs, Jagd, Crafts, günstige Upgrades) laufen
parallel über das Kandidaten-Scoring.

Ab M3 übernimmt hier die Run-Typ-Auswahl (PRICE_RATIO_RUN, ...).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from player.state import access as A

from . import shadow, simulate
from .reset import FIRST_RESET_MIN_PARAGON, MIN_PARAGON_GAIN


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
    Milestone("library_1", "Bibliothek bauen (Science!)", _bld(1, "library"),
              {"kind": "build", "name": "library"},
              visible=_bld_visible("library")),
    Milestone("calendar", "Calendar erforschen", _tech("calendar"),
              {"kind": "research", "name": "calendar"}),
    Milestone("agriculture", "Agriculture erforschen (Farmer)", _tech("agriculture"),
              {"kind": "research", "name": "agriculture"}),
    Milestone("mine_1", "Erste Mine", _bld(1, "mine"),
              {"kind": "build", "name": "mine"},
              visible=_tech("mining")),
    Milestone("metal", "Metal Working erforschen", _tech("metal"),
              {"kind": "research", "name": "metal"}),
    Milestone("smelter_1", "Schmelze bauen (Iron)", _bld(1, "smelter"),
              {"kind": "build", "name": "smelter"},
              visible=_tech("metal")),
    Milestone("animal", "Animal Husbandry erforschen", _tech("animal"),
              {"kind": "research", "name": "animal"}),
    Milestone("math", "Mathematics erforschen", _tech("math"),
              {"kind": "research", "name": "math"}),
    Milestone("construction", "Construction erforschen", _tech("construction"),
              {"kind": "research", "name": "construction"}),
    Milestone("lumbermill_1", "Sägewerk bauen", _bld(1, "lumberMill"),
              {"kind": "build", "name": "lumberMill"},
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
    Milestone("solar_revolution", "Solar Revolution (globaler Multiplikator!)",
              lambda snap: any(u["name"] == "solarRevolution" and (u["on"] or u["val"])
                               for u in snap.get("religion", {}).get("upgrades", [])),
              {"kind": "religion_upgrade", "name": "solarRevolution"},
              visible=lambda snap: any(u["name"] == "solarRevolution" and u["unlocked"]
                                       for u in snap.get("religion", {}).get("upgrades", []))),
    Milestone("ziggurat_1", "Erstes Ziggurat (Unicorn-Ökonomie)", _bld(1, "ziggurat"),
              {"kind": "build", "name": "ziggurat"},
              visible=_bld_visible("ziggurat")),
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
# Nach der Price-Ratio-Kette: Chronomancy/Astromancy (Events/Starcharts)
# und Anachronomancy (TC-Schutz vor Resets — Pflicht laut Spec 9.1).
METAPHYSICS_ORDER = [
    "engeneering", "diplomacy", "goldenRatio",
    "divineProportion", "vitruvianFeline", "renaissance",
    "chronomancy", "astromancy", "anachronomancy",
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
                        "renaissance": 750, "chronomancy": 25, "astromancy": 50,
                        "anachronomancy": 125}
            return {"name": name, "label": name, "researched": False,
                    "unlocked": False,
                    "prices": [{"name": "paragon", "val": defaults[name]}]}
        if not p["researched"]:
            return p
    return None


# ---------------------------------------------------------------- Run-Typen
# Spec 8.2: die 13 Makroplan-Kandidaten. Aktiv wählbar sind in dieser
# Ausbaustufe nur FIRST_RUN, PRICE_RATIO_RUN und PARAGON_RUN — für die
# übrigen Run-Typen folgt die Zulässigkeit mit späterem Ausbau (es gibt
# für sie noch keine Zielmeilensteine und keine Bewertungsformeln).
RUN_TYPES = frozenset({
    "FIRST_RUN", "PRICE_RATIO_RUN", "CORE_META_RUN", "RELIGION_RUN",
    "UNICORN_RUN", "CHALLENGE_RUN", "LEVIATHAN_RUN", "RELIC_STATION_RUN",
    "SHATTER_RUN", "PARAGON_RUN", "SEED_RUN", "POSITIVE_CS_RUN",
    "MATURE_ENDGAME_RUN",
})
ACTIVE_RUN_TYPES = frozenset({"FIRST_RUN", "PRICE_RATIO_RUN", "PARAGON_RUN"})

# Taktische Varianten je Makroplan (Spec 8.3 Schritt 3): invest-Anteil der
# Projektions-Politik. Namen sind zugleich der deterministische Tie-Break
# (lexikografisch, Anhang C.2).
RUN_VARIANTS: tuple[tuple[str, float], ...] = (
    ("a_minimal", 0.15),            # schneller Minimalpfad
    ("b_ausgeglichen", 0.35),       # ausgeglichener Pfad
    ("c_investitionsstark", 0.60),  # investitionsstarker Pfad
)


def _admissible_run_types(snap: dict) -> list[str]:
    """Zulässigkeitsregeln wie die bisherige feste Ableitung (M3-Umfang):
    FIRST_RUN nur ohne persistenten Fortschritt; PRICE_RATIO_RUN solange
    die Metaphysics-Kette offen ist; PARAGON_RUN sonst."""
    prestige = snap.get("prestige", {})
    persistent = (prestige.get("paragon", 0) + prestige.get("burnedParagon", 0)
                  + prestige.get("karma", 0))
    any_perk = any(p["researched"] for p in prestige.get("perks", []))
    if persistent <= 0 and not any_perk:
        return ["FIRST_RUN"]
    if next_metaphysics_target(snap) is not None:
        return ["PRICE_RATIO_RUN"]
    return ["PARAGON_RUN"]


def _plan_restzeit(snap: dict, run_type: str, proj: simulate.Projection,
                   horizon: float) -> float:
    """Erwartete Restzeit bis zum Run-Ziel (Score vor F = −Restzeit, Spec 6.2).

    FIRST_RUN:       Zeit bis Reset-Paragon ≥ FIRST_RESET_MIN_PARAGON.
    PRICE_RATIO_RUN: Zeit bis der nächste Perk finanzierbar ist (paragon_now
                     + Projektion ≥ Preis) UND Metaphysics erforschbar war.
    PARAGON_RUN:     Paragonrate pro Realzeit, als Restzeit normiert über
                     die Zeit für MIN_PARAGON_GAIN Paragon (vergleichbar).
    """
    if run_type == "FIRST_RUN":
        return proj.paragon_eta(FIRST_RESET_MIN_PARAGON)
    if run_type == "PRICE_RATIO_RUN":
        perk = next_metaphysics_target(snap)
        if perk is None:
            return math.inf
        price = next((p["val"] for p in perk.get("prices", [])
                      if p["name"] == "paragon"), 0)
        paragon_now = snap.get("prestige", {}).get("paragon", 0)
        t_fund = proj.paragon_eta(price - paragon_now)
        t_tech = 0.0
        tech = A.tech(snap, "metaphysics")
        if tech and not tech["researched"]:
            t_tech = proj.eta_of(tech["prices"])
        return max(t_fund, t_tech)
    # PARAGON_RUN (Spec 20.4): erwartete Paragonrate über den Horizont
    gain = proj.paragon_projection(horizon) - proj.paragon_projection(0.0)
    if gain <= 0:
        return math.inf
    return MIN_PARAGON_GAIN / (gain / horizon)


def _score_plans(snap: dict, run_types: list[str], horizon: float) -> list[dict]:
    rows: list[dict] = []
    for rt in run_types:
        for variant, invest in RUN_VARIANTS:
            proj = simulate.project(snap, horizon, policy={"invest": invest})
            rows.append({"runType": rt, "variant": variant, "invest": invest,
                         "restzeit": _plan_restzeit(snap, rt, proj, horizon)})
    return rows


def determine_run_plan(snap: dict) -> tuple[str, str | None, dict]:
    """Run-Typ + taktische Variante per Simulation wählen (Spec 8.3).

    Für jeden zulässigen Run-Typ werden die drei Varianten a/b/c mit
    simulate.project bewertet; das Paar mit der kleinsten erwarteten
    Restzeit gewinnt, Ties lexikografisch (Anhang C.2). Reicht der
    Snapshot nicht für eine Projektion (leere Alt-Test-Snapshots),
    greift der Fallback auf die bisherige feste Ableitung.
    """
    admissible = _admissible_run_types(snap)
    if not simulate.has_projection_data(snap):
        return admissible[0], None, {"fallback": "keine Simulationsdaten — feste Ableitung"}
    horizon = shadow.run_horizon(snap)
    rows = _score_plans(snap, admissible, horizon)
    order = lambda r: (r["restzeit"], r["runType"], r["variant"])  # noqa: E731
    best = min(rows, key=order)
    # PARAGON_RUN ist ZUSÄTZLICH zulässig, wenn das Price-Ratio-Ziel im
    # Horizont unerreichbar ist (Spec 8.2 „sonst/zusätzlich") — aber nur,
    # wenn er selbst eine endliche Restzeit hat (sonst bleibt das alte
    # Verhalten: Price-Ratio-Kette hat Vorrang, solange sie offen ist).
    if admissible == ["PRICE_RATIO_RUN"] and math.isinf(best["restzeit"]):
        extra = _score_plans(snap, ["PARAGON_RUN"], horizon)
        if any(math.isfinite(r["restzeit"]) for r in extra):
            rows += extra
            best = min(rows, key=order)
    detail = {
        "horizonS": horizon,
        "scores": [{**r, "restzeit": (None if math.isinf(r["restzeit"])
                                      else round(r["restzeit"], 1))}
                   for r in rows],
    }
    return best["runType"], best["variant"], detail


def determine_run(snap: dict) -> str:
    """Run-Typ (Spec 8.2) — abwärtskompatible Sicht auf determine_run_plan."""
    return determine_run_plan(snap)[0]


@dataclass
class MetaView:
    phase: str
    run_type: str
    active: Milestone | None
    milestones: list[dict]      # fürs Cockpit: [{id,label,state}]
    next_perk: dict | None = None
    # Simulationsbasierte Planwahl (Spec 8.3) — None im Fallback:
    run_variant: str | None = None
    run_plan: dict | None = None

    @property
    def objective_label(self) -> str:
        return self.active.label if self.active else "Wirtschaft ausbauen (Frontier erschöpft in M1)"

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "runType": self.run_type,
            "runVariant": self.run_variant,
            "runPlan": self.run_plan,
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
    """Bestimmt Phase, Run-Typ (+ Variante) und den aktiven Meilenstein."""
    run_type, run_variant, run_plan = determine_run_plan(snap)
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
                    milestones=rows, next_perk=next_perk,
                    run_variant=run_variant, run_plan=run_plan)
