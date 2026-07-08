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

from . import challenge, chrono, endgame, religion, shadow, simulate, timecrystal
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


def _space_building(snap: dict, name: str) -> dict | None:
    for planet in snap.get("space", {}).get("planets", []):
        for b in planet.get("buildings", []):
            if b.get("name") == name:
                return b
    return None


# Feste frühe Metaphysics-Reihenfolge (Spec 9.1). Hinweis: das Spec-Wort
# „Enlightenment" heißt in v1.5.0.2 „engeneering" (sic, -1 % Price Ratio).
# Nach der Price-Ratio-Kette: Chronomancy/Astromancy (Events/Starcharts)
# und Anachronomancy (TC-Schutz vor Resets — Pflicht laut Spec 9.1).
METAPHYSICS_ORDER = [
    "engeneering", "diplomacy", "goldenRatio",
    "divineProportion", "vitruvianFeline", "renaissance",
    "chronomancy", "astromancy", "anachronomancy",
]
# Aufteilung der Kette für die Run-Typ-Gates (Spec 8.2): die ersten sechs
# Perks sind die Price-Ratio-Kette (9.1) → PRICE_RATIO_RUN; die Pfad-Metas
# dahinter (Chronomancy/Astromancy/Anachronomancy) und alle weiteren im
# Snapshot offenen Perks (Megalomania, Numerology, …) → CORE_META_RUN.
PRICE_RATIO_ORDER = METAPHYSICS_ORDER[:6]
CORE_META_ORDER = METAPHYSICS_ORDER[6:]


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


def _open_extra_perks(snap: dict) -> list[dict]:
    """Im Snapshot offene (unlocked, nicht researched) Perks AUSSERHALB der
    festen 9.1-Kette — der CORE_META-Suchraum („weitere Pfad-Metas", 8.2),
    deterministisch nach (Paragon-Preis, Name) sortiert."""
    chain = set(METAPHYSICS_ORDER)
    extras = [p for p in snap.get("prestige", {}).get("perks", [])
              if p.get("unlocked") and not p.get("researched")
              and p.get("name") not in chain]
    price = lambda p: next((q["val"] for q in p.get("prices", [])  # noqa: E731
                            if q["name"] == "paragon"), 0)
    extras.sort(key=lambda p: (price(p), p["name"]))
    return extras


# ---------------------------------------------------------------- Run-Typen
# Spec 8.2: die 13 Makroplan-Kandidaten — alle aktiv wählbar. Die
# Zulässigkeit jedes Typs hängt an beobachtbaren Spielzuständen
# (_admissible_run_types); die Auswahl unter den zulässigen Typen trifft
# die Simulation (8.3), nach vollständiger Front zählt ΔlnC/Δt (6.3).
RUN_TYPES = frozenset({
    "FIRST_RUN", "PRICE_RATIO_RUN", "CORE_META_RUN", "RELIGION_RUN",
    "UNICORN_RUN", "CHALLENGE_RUN", "LEVIATHAN_RUN", "RELIC_STATION_RUN",
    "SHATTER_RUN", "PARAGON_RUN", "SEED_RUN", "POSITIVE_CS_RUN",
    "MATURE_ENDGAME_RUN",
})
ACTIVE_RUN_TYPES = frozenset(RUN_TYPES)

# SHATTER_RUN-Restzeit (dokumentierte Näherung, siehe _plan_restzeit):
# Ziel-TC-Bestand, ab dem die Engine „läuft" = Reserve + ein voller
# konservativer Batch-Vorrat (Referenzgröße, kein Spielwert):
SHATTER_RUN_TC_TARGET = timecrystal.TC_RESERVE + 15.0
# RELIC_STATION_RUN: AM-Cap-Schwelle der vollen Relic-Station-Wirkung
# (space.js:718-720: rrBoost × amMax/5000 unter 5000) und Referenzpreise
# des relicStation-Upgrades (workshop.js:1538-1550):
RELIC_STATION_AM_CAP = 5000.0
RELIC_STATION_REF_PRICES = [{"name": "antimatter", "val": 5000},
                            {"name": "eludium", "val": 100}]
# AM-Cap je Containment Chamber (space.js:597, ohne Heatsink-Bonus —
# konservative Basis; der Snapshot-Cap hat immer Vorrang):
AM_MAX_PER_CONTAINMENT = 100.0
# SEED_RUN: erwartete Dauer eines dedizierten Seed-Runs — REFERENZSCHÄTZUNG
# (ehrlich gekennzeichnet, konservativ wie challenge.est_completion_s):
# SEED_RUN gewinnt nur, wenn die anderen Pläne schlechter scoren.
SEED_RUN_EST_S = 6 * 3600.0

# Taktische Varianten je Makroplan (Spec 8.3 Schritt 3): invest-Anteil der
# Projektions-Politik. Namen sind zugleich der deterministische Tie-Break
# (lexikografisch, Anhang C.2).
RUN_VARIANTS: tuple[tuple[str, float], ...] = (
    ("a_minimal", 0.15),            # schneller Minimalpfad
    ("b_ausgeglichen", 0.35),       # ausgeglichener Pfad
    ("c_investitionsstark", 0.60),  # investitionsstarker Pfad
)


def _religion_run_admissible(snap: dict) -> bool:
    """RELIGION_RUN-Gate (Spec 8.2/15.1-15.2): Religion-Infrastruktur steht
    (Tempel ≥ 1 oder Worship > 0) UND der transcend_value-Pfad ist positiv
    (religion.transcend_value: erreichbar, Bilanz > 0, Wiederanlauf im
    Horizont) — nur dann lohnt ein dedizierter Transcendence-/Epiphany-Run."""
    rel = snap.get("religion") if isinstance(snap.get("religion"), dict) else {}
    infra = A.bld_val(snap, "temple") >= 1 or float(rel.get("worship", 0) or 0) > 0
    if not infra:
        return False
    return bool(religion.transcend_value(snap)["worth"])


def _unicorn_run_admissible(snap: dict) -> bool:
    """UNICORN_RUN-Gate (Spec 8.2/15.3): die Ziggurat-Schicht ist sichtbar
    (Ziggurat-Gebäude im Snapshot oder religion.ziggurat-Einträge) — erst
    dann existiert die Unicorn-/Tear-/Alicorn-Ökonomie überhaupt."""
    if A.building(snap, "ziggurat") is not None:
        return True
    rel = snap.get("religion") if isinstance(snap.get("religion"), dict) else {}
    return bool(rel.get("ziggurat"))


def _admissible_run_types(snap: dict) -> list[str]:
    """Zulässige Run-Typen (Spec 8.2) aus beobachtbaren Spielzuständen.

    Die Gates bilden die 9.2-Engine-Reihenfolge als ZULÄSSIGKEITS-KASKADE
    ab (keine starre Build-Order — die Auswahl unter den zulässigen Typen
    trifft die Simulation, 8.3): Alicorn-/Leviathan-TC-Quelle (UNICORN_/
    LEVIATHAN_RUN) → Relic Stations mit voller AM-Wirkung
    (RELIC_STATION_RUN) → Resource-Retrieval-Shatter-Engine (SHATTER_RUN)
    → Paragon-/Storage-Skalierung (PARAGON_RUN) → Antimatter-/Void-Seed
    (SEED_RUN) → positive Chronosphere-Schleife (POSITIVE_CS_RUN) →
    Mature Endgame (MATURE_ENDGAME_RUN, erst nach vollständiger Front,
    endgame.frontier_complete). Jedes Gate wird erst zulässig, wenn seine
    Voraussetzungen im Snapshot stehen; frühere Typen bleiben zulässig und
    konkurrieren regulär über den Plan-Score.

    Basistypen: FIRST_RUN nur ohne persistenten Fortschritt;
    PRICE_RATIO_RUN solange die Price-Ratio-Kette (9.1, PRICE_RATIO_ORDER)
    offen ist; CORE_META_RUN, wenn die Price-Ratio-Kette fertig ist, aber
    weitere Perks offen sind (Chronomancy/Astromancy/Anachronomancy aus
    METAPHYSICS_ORDER oder Snapshot-Perks jenseits der Kette);
    PARAGON_RUN sonst.

    CHALLENGE_RUN (Spec 18): Läuft bereits eine Challenge, ist der Run
    gebunden — die Spielregeln sind für den ganzen Run geändert, das
    18.4-Reset-Gate übernimmt (nur CHALLENGE_RUN zulässig). Sonst ist
    CHALLENGE_RUN ZUSÄTZLICH zulässig, wenn eine unerledigte Challenge mit
    positivem ChallengeValue existiert (challenge.best_challenge) UND
    Challenges für den Spieler erreichbar sind (Adjustment-Bureau-Perk /
    Challenges-Tab, gamefiles/game.js:2680) — dann wäre sie nach dem
    nächsten Reset aktivierbar (pending → active, game.js:5136-5141)."""
    if challenge.active_challenge(snap) is not None:
        return ["CHALLENGE_RUN"]
    prestige = snap.get("prestige", {})
    persistent = (prestige.get("paragon", 0) + prestige.get("burnedParagon", 0)
                  + prestige.get("karma", 0))
    any_perk = any(p["researched"] for p in prestige.get("perks", []))
    target = next_metaphysics_target(snap)
    if persistent <= 0 and not any_perk:
        base = ["FIRST_RUN"]
    elif target is not None and target["name"] in PRICE_RATIO_ORDER:
        base = ["PRICE_RATIO_RUN"]
    elif target is not None or _open_extra_perks(snap):
        base = ["CORE_META_RUN"]
    else:
        base = ["PARAGON_RUN"]
    if _religion_run_admissible(snap):
        base.append("RELIGION_RUN")
    if _unicorn_run_admissible(snap):
        base.append("UNICORN_RUN")
    if challenge.challenges_available(snap) \
            and challenge.best_challenge(snap) is not None:
        base.append("CHALLENGE_RUN")
    base += _endgame_run_types(snap)
    if endgame.frontier_complete(snap):
        base.append("MATURE_ENDGAME_RUN")
    return base


def _leviathans_tradeable(snap: dict) -> bool:
    """LEVIATHAN_RUN-Gate: Leviathans sind handelbar (diplomacy-Daten) und
    die TC-Erwartung je Trade ist positiv (Spec 8.2/14.4/17.1)."""
    if A.race(snap, "leviathans") is None:
        return False
    return timecrystal.tc_balance(snap)["leviathanTcPerTrade"] > 0


def _relic_infra_visible(snap: dict) -> bool:
    """RELIC_STATION_RUN-Gate: Space-Infrastruktur Richtung Antimatter ist
    sichtbar — Sunlifter (AM-Produktion, space.js:560-580) im Space-Snapshot
    oder Antimatter bereits als Ressource beobachtet (Spec 16.3)."""
    if A.resource(snap, "antimatter") is not None:
        return True
    for planet in snap.get("space", {}).get("planets", []):
        for b in planet.get("buildings", []):
            if b.get("name") == "sunlifter" and (b.get("unlocked") or b.get("val", 0) > 0):
                return True
    return False


def _relic_station_done(snap: dict) -> bool:
    """AM-Cap-Makroplan abgeschlossen: relicStation erforscht UND AM-Cap
    ≥ 5000 (volle Wirkung, space.js:718-720)."""
    up = A.upgrade(snap, "relicStation")
    return bool(up and up.get("researched")) \
        and A.res_cap(snap, "antimatter") >= RELIC_STATION_AM_CAP


def _endgame_run_types(snap: dict) -> list[str]:
    """Zusätzlich zulässige Endgame-Run-Typen (Spec 8.2), rein aus
    beobachtbaren Zuständen — Reihenfolge deterministisch."""
    extra: list[str] = []
    if _leviathans_tradeable(snap):
        extra.append("LEVIATHAN_RUN")
    if timecrystal.rr_level(snap) >= 1 \
            and timecrystal.tc_balance(snap)["netPositive"]:
        extra.append("SHATTER_RUN")
    if _relic_infra_visible(snap) and not _relic_station_done(snap):
        extra.append("RELIC_STATION_RUN")
    if chrono.positive_cs_check(snap)[0]:
        extra.append("POSITIVE_CS_RUN")
    if chrono.seed_run_admissible(snap)[0]:
        extra.append("SEED_RUN")
    return extra


def _plan_restzeit(snap: dict, run_type: str, proj: simulate.Projection,
                   horizon: float) -> float:
    """Erwartete Restzeit bis zum Run-Ziel (Score vor F = −Restzeit, Spec 6.2).

    FIRST_RUN:       Zeit bis Reset-Paragon ≥ FIRST_RESET_MIN_PARAGON.
    PRICE_RATIO_RUN: Zeit bis der nächste Perk finanzierbar ist (paragon_now
                     + Projektion ≥ Preis) UND Metaphysics erforschbar war.
    CORE_META_RUN:   wie PRICE_RATIO_RUN, Ziel ist der nächste Pfad-Perk
                     (Chronomancy/Astromancy/Anachronomancy, 9.1) bzw. der
                     günstigste offene Perk jenseits der Kette (8.2).
    RELIGION_RUN:    Worship-Wiederanlaufzeit nach dem TAP (15.2,
                     religion.transcend_value recoveryS) — der Run ist
                     „fertig", wenn der Transcend verkraftet ist
                     (dokumentierte, konservative Näherung).
    UNICORN_RUN:     Zeit bis zum nächsten vollen Opfer-Batch (2500
                     Unicorns, religion.js:3021) über die beobachtete
                     Unicorn-Rate; ohne Ziggurat erst die ETA des ersten
                     Ziggurats (Unicorn-/Tear-Projektion, konservativ).
    PARAGON_RUN:     Paragonrate pro Realzeit, als Restzeit normiert über
                     die Zeit für MIN_PARAGON_GAIN Paragon (vergleichbar).
    MATURE_ENDGAME_RUN: hat KEINE Restzeit — sein Score ist ΔlnC/Δt
                     (Spec 6.3, siehe _score_plans); hier defensiv inf.
    CHALLENGE_RUN:   geschätzte Completion-Zeit der (aktiven bzw. besten)
                     Challenge — Referenzkonstante aus challenge.py, bewusst
                     KONSERVATIV (Stunden), damit CHALLENGE_RUN nur gewinnt,
                     wenn PRICE_RATIO/PARAGON schlechter scoren (Spec 18.2).

    Endgame-Typen (dokumentierte Näherungen — Zeit bis positiver TC-/
    Relic-Fluss über die EV-Projektion bzw. beobachtete Raten):
    LEVIATHAN_RUN:   ETA des nächsten Leviathan-Trade-Kostenvektors
                     (buys + 50 Catpower, diplomacy.js tradeImpl) über die
                     Projektion — dann fließen TC (Spec 14.4/17.1).
    SHATTER_RUN:     Zeit bis der TC-Bestand SHATTER_RUN_TC_TARGET trägt
                     (beobachtete timeCrystal-Rate; Bestand reicht → 0).
    RELIC_STATION_RUN: ETA des AM-Cap-Blocks = eta_of der relicStation-
                     Preise (Snapshot, sonst Referenz workshop.js:1538-1550).
    POSITIVE_CS_RUN: Dauer einer Schleifeniteration ≈ Wiederaufbau der
                     Chronosphere-Flotte (REBUILD_DELAY_PER_CS_S × n, 19.4).
    SEED_RUN:        Referenzschätzung SEED_RUN_EST_S (konservativ, 19.3).
    """
    if run_type == "FIRST_RUN":
        return proj.paragon_eta(FIRST_RESET_MIN_PARAGON)
    if run_type == "CHALLENGE_RUN":
        act = challenge.active_challenge(snap)
        if act is not None:
            return challenge.est_completion_s(act["name"])
        best = challenge.best_challenge(snap)
        if best is None:
            return math.inf
        return challenge.est_completion_s(best[0])
    if run_type in ("PRICE_RATIO_RUN", "CORE_META_RUN"):
        perk = next_metaphysics_target(snap)
        if perk is None:
            extras = _open_extra_perks(snap)
            perk = extras[0] if extras else None
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
    if run_type == "RELIGION_RUN":
        rec = religion.transcend_value(snap).get("recoveryS")
        return float(rec) if rec is not None else math.inf
    if run_type == "UNICORN_RUN":
        if A.bld_val(snap, "ziggurat") < 1:
            z = A.building(snap, "ziggurat")
            if z is None or not z.get("prices"):
                return math.inf
            return proj.eta_of(z["prices"])
        need = religion.UNICORN_SAC_BATCH - A.res_value(snap, "unicorns")
        if need <= 0:
            return 0.0
        rate = A.res_rate(snap, "unicorns")
        if rate <= 1e-9:
            return math.inf
        return need / rate
    if run_type == "LEVIATHAN_RUN":
        race = A.race(snap, "leviathans")
        if race is None:
            return math.inf
        costs = [{"name": "manpower", "val": 50}] \
            + [{"name": p["name"], "val": p["val"]} for p in race.get("buys", [])]
        return proj.eta_of(costs)
    if run_type == "SHATTER_RUN":
        bal = timecrystal.tc_balance(snap)
        need = SHATTER_RUN_TC_TARGET - bal["stock"]
        if need <= 0:
            return 0.0
        if bal["ratePerSec"] <= 1e-9:
            return math.inf
        return need / bal["ratePerSec"]
    if run_type == "RELIC_STATION_RUN":
        up = A.upgrade(snap, "relicStation")
        prices = (up or {}).get("prices") or RELIC_STATION_REF_PRICES
        if up and up.get("researched"):
            # Upgrade steht — es fehlt nur noch das AM-Cap: ETA der
            # nächsten Containment Chamber (space.js:582-602) als Proxy.
            cc = _space_building(snap, "containmentChamber")
            prices = (cc or {}).get("prices") or []
        return proj.eta_of(prices)
    if run_type == "POSITIVE_CS_RUN":
        n = A.bld_val(snap, "chronosphere")
        if n < 1:
            return math.inf
        return chrono.REBUILD_DELAY_PER_CS_S * n
    if run_type == "SEED_RUN":
        return SEED_RUN_EST_S
    # PARAGON_RUN (Spec 20.4): erwartete Paragonrate über den Horizont
    gain = proj.paragon_projection(horizon) - proj.paragon_projection(0.0)
    if gain <= 0:
        return math.inf
    return MIN_PARAGON_GAIN / (gain / horizon)


# ---------------------------------------------------------------- Risiko (6.2)
# Risikoterme der Planbewertung vor F (Spec 6.2):
#     Score(plan) = −E[T_F] − κ·P(fatal) − μ·E[irreversible loss]
# DETERMINISTISCHE PROXYS, KEIN CVaR (das 5.4-Zufallsmodell bräuchte echte
# Ergebnisverteilungen — die haben wir nicht; dokumentierte Näherung):
# - P(fatal) ∈ {0, 1}: 1, wenn die EV-Projektion die Food-Invariante I-01
#   im Horizont verletzt (Projection.food_fatal) — Food ist unser einziger
#   fataler Pfad; sonst 0.
# - E[irreversible loss]: Wiederbeschaffungszeit der Bestände, die ein im
#   Horizont geplanter Reset laut Carryover-Fallliste (chrono.carryover_
#   vector, game.js _resetInternal) verlieren würde.
# κ dominiert jede Restzeit im Horizontfenster (HORIZON_MAX = 4 h =
# 14 400 s), bleibt aber endlich (deterministisch vergleichbar); μ ist
# bewusst schwach — der Verlustterm wirkt als Tie-Breaker (6.2 Satz 2).
KAPPA_FATAL_S = 1_000_000.0
MU_IRREVERSIBLE_LOSS = 0.1
# Run-Typen, deren Ziel ein Reset ist (nur dort steht im Horizont ein
# geplanter Reset an, der nicht-persistente Bestände verliert):
RESET_ENDING_RUN_TYPES = frozenset({
    "FIRST_RUN", "PRICE_RATIO_RUN", "CORE_META_RUN", "PARAGON_RUN",
    "CHALLENGE_RUN", "SEED_RUN", "POSITIVE_CS_RUN",
})


def _irreversible_loss_seconds(snap: dict) -> float:
    """E[irreversible loss]-Proxy in Sekunden: Bestand minus Carryover je
    Ressource (Fallliste chrono.carryover_vector), bewertet über die
    Wiederbeschaffungszeit Verlust ÷ beobachtete Rate. λ liegt auf der
    Meta-Ebene nicht vor — die ETA-Bewertung ist dieselbe dokumentierte
    Näherung wie chrono._carryover_seconds_per_cs; Ressourcen ohne
    Produktionsrate werden nicht bewertet (ehrlich: keine seriöse Basis)."""
    carry = chrono.carryover_vector(snap)
    total = 0.0
    for r in snap.get("resources", []):
        value = float(r.get("value", 0.0))
        rate = float(r.get("perSec", 0.0))
        if value <= 0 or rate <= chrono.RATE_EPS:
            continue
        lost = value - carry.get(r["name"], 0.0)
        if lost > 0:
            total += lost / rate
    return total


def _score_plans(snap: dict, run_types: list[str], horizon: float) -> list[dict]:
    """Plan-Scores je (Run-Typ, Variante) — Umschaltung 6.2 ↔ 6.3:

    Vor der Front (Spec 6.2): score = −Restzeit − κ·P(fatal) − μ·Verlust.
    Nach der Front (endgame.frontier_complete) und IMMER für
    MATURE_ENDGAME_RUN (Spec 6.3): score = E[ΔlnC/Δt] über die
    EV-Projektion (endgame.endgame_score) statt −Restzeit."""
    frontier_done = endgame.frontier_complete(snap)
    loss_cache: dict[str, float] = {}
    rows: list[dict] = []
    for rt in run_types:
        for variant, invest in RUN_VARIANTS:
            proj = simulate.project(snap, horizon, policy={"invest": invest})
            row: dict = {"runType": rt, "variant": variant, "invest": invest}
            if rt == "MATURE_ENDGAME_RUN" or frontier_done:
                row["restzeit"] = math.inf   # 6.3: keine Restzeit-Metrik
                row["score"] = endgame.endgame_score(snap, horizon, proj=proj)
                row["scoreMode"] = "6.3"
            else:
                rz = _plan_restzeit(snap, rt, proj, horizon)
                fatal = 1.0 if proj.food_fatal() else 0.0
                loss = 0.0
                if rt in RESET_ENDING_RUN_TYPES and rz <= horizon:
                    loss = loss_cache.setdefault(rt, _irreversible_loss_seconds(snap))
                row["restzeit"] = rz
                row["pFatal"] = fatal
                row["irrevLossS"] = round(loss, 1)
                row["score"] = (-rz - KAPPA_FATAL_S * fatal
                                - MU_IRREVERSIBLE_LOSS * loss)
                row["scoreMode"] = "6.2"
            rows.append(row)
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
    # Auswahl: maximaler Score (6.2: −Restzeit − Risikoterme; 6.3: ΔlnC/Δt).
    # Tie-Breaks deterministisch (Anhang C.2); im 6.3-Modus ist
    # MATURE_ENDGAME_RUN der kanonische Träger der Zielfunktion (Spec 8.2)
    # und gewinnt Gleichstände gegen andere Typen.
    order = lambda r: (-r["score"],                                  # noqa: E731
                       0 if r["runType"] == "MATURE_ENDGAME_RUN" else 1,
                       r["runType"], r["variant"])
    best = min(rows, key=order)
    # PARAGON_RUN ist ZUSÄTZLICH zulässig, wenn das Price-Ratio-Ziel im
    # Horizont unerreichbar ist (Spec 8.2 „sonst/zusätzlich") — aber nur,
    # wenn er selbst eine endliche Restzeit hat (sonst bleibt das alte
    # Verhalten: Price-Ratio-Kette hat Vorrang, solange sie offen ist).
    # Auch mit zusätzlich zulässigem CHALLENGE_RUN bleibt der Fallback:
    # PARAGON konkurriert dann regulär gegen die Challenge-Restzeit.
    if "PRICE_RATIO_RUN" in admissible and "PARAGON_RUN" not in admissible \
            and all(math.isinf(r["restzeit"]) for r in rows
                    if r["runType"] == "PRICE_RATIO_RUN"):
        extra = _score_plans(snap, ["PARAGON_RUN"], horizon)
        if any(math.isfinite(r["restzeit"]) for r in extra):
            rows += extra
            best = min(rows, key=order)
    detail = {
        "horizonS": horizon,
        "scoreMode": rows[0]["scoreMode"] if rows else "6.2",
        "scores": [{**r,
                    "restzeit": (None if math.isinf(r["restzeit"])
                                 else round(r["restzeit"], 1)),
                    "score": (None if math.isinf(r["score"])
                              else round(r["score"], 6))}
                   for r in rows],
    }
    return best["runType"], best["variant"], detail


def determine_run(snap: dict) -> str:
    """Run-Typ (Spec 8.2) — abwärtskompatible Sicht auf determine_run_plan."""
    return determine_run_plan(snap)[0]


# ---------------------------------------------------------------- Phasen (Kap. 9)
# Operationale AUSTRITTSkriterien je Phase (Tabelle Kap. 9) als prüfbare
# Snapshot-Bedingungen. Die Phase ist die ERSTE, deren Austrittskriterium
# nicht erfüllt ist — konservativ: wo Kriterien Late-Game-Daten bräuchten,
# die der Snapshot (noch) nicht liefert, bleibt das Kriterium unerfüllt und
# der Agent in der niedrigsten zutreffenden Phase („keine spätere Phase als
# operational markieren", Kap. 9).

def _perks_researched(snap: dict, names: list[str]) -> bool:
    perks = {p["name"]: p for p in snap.get("prestige", {}).get("perks", [])}
    return all(bool(perks.get(n, {}).get("researched")) for n in names)


def _solar_revolution_on(snap: dict) -> bool:
    return any(u.get("name") == "solarRevolution" and (u.get("on") or u.get("val"))
               for u in snap.get("religion", {}).get("upgrades", []))


def _p0_exit(snap: dict) -> bool:
    """P0 Erstwirtschaft → P1: „erster Reset wirtschaftlich" vollzogen —
    persistenter Fortschritt (Paragon/Karma/Perk) ist beobachtbar. Die
    Teilkriterien der Tabelle (Food-/Wood-/Mineral-/Science-Kette,
    Workshops, Apocrypha) sind Voraussetzungen dieses Resets und damit im
    Proxy enthalten (dokumentierte Vereinfachung)."""
    prestige = snap.get("prestige", {})
    persistent = (prestige.get("paragon", 0) + prestige.get("burnedParagon", 0)
                  + prestige.get("karma", 0))
    return persistent > 0 or any(p.get("researched")
                                 for p in prestige.get("perks", []))


def _p1_exit(snap: dict) -> bool:
    """P1 Price-Ratio → P2: die sechs Price-Ratio-Metas (9.1) erworben."""
    return _perks_researched(snap, PRICE_RATIO_ORDER)


def _p2_exit(snap: dict) -> bool:
    """P2 Core Meta & Space → P3: Pfad-Metas inkl. Anachronomancy erworben
    (9.1: „Anachronomancy vor TC-Reset") und stabile UO-Produktion."""
    return _perks_researched(snap, CORE_META_ORDER) \
        and A.res_rate(snap, "unobtainium") > 0


def _p3_exit(snap: dict) -> bool:
    """P3 Religion & Unicorn → P4: Solar Revolution aktiv und die
    Unicorn-Basis (Ziggurat) steht."""
    return _solar_revolution_on(snap) and A.bld_val(snap, "ziggurat") >= 1


def _p4_exit(snap: dict) -> bool:
    """P4 Leviathan TC → P5: Leviathan-Kontakt mit positiver TC-Erwartung
    aus UO-Trades (14.4/17.1)."""
    return _leviathans_tradeable(snap)


def _p5_exit(snap: dict) -> bool:
    """P5 Relic & Shatter → P6: 5000er-AM-Cap + Relic Station (16.3/17.4),
    RR-Aufbau und positive TC-Bilanz (17.1)."""
    return _relic_station_done(snap) and timecrystal.rr_level(snap) >= 1 \
        and timecrystal.tc_balance(snap)["netPositive"]


def _p6_exit(snap: dict) -> bool:
    """P6 Challenge & Paragon Scale → P7: alle Erstabschlüsse registriert
    (18.1; Iron Will hat Sonderregeln und zählt nicht)."""
    todo = [c for c in challenge.challenge_list(snap)
            if c.get("name") not in challenge.EXCLUDED]
    return bool(todo) and all(c.get("researched") for c in todo)


def _p7_exit(snap: dict) -> bool:
    """P7 Seed & Positive CS → P8: positive Chronosphere-Rekonstruktion
    nachgewiesen (19.2) und die endliche Front vollständig (6.3-Gate)."""
    return chrono.positive_cs_check(snap)[0] and endgame.frontier_complete(snap)


PHASE_EXITS: tuple = (_p0_exit, _p1_exit, _p2_exit, _p3_exit,
                      _p4_exit, _p5_exit, _p6_exit, _p7_exit)


def determine_phase(snap: dict) -> str:
    """Makrophase P0…P8 (Kap. 9): erste Phase mit unerfülltem Austritt."""
    for i, exit_check in enumerate(PHASE_EXITS):
        if not exit_check(snap):
            return f"P{i}"
    return "P8"


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
    # Nächstes offenes Forschungsziel hinter dem aktiven Meilenstein
    # (für die Soll-Allokation 12.2; None wenn aktiv schon Forschung ist):
    next_research: dict | None = None
    # Alle offenen (active+pending) Meilenstein-Targets in Listenreihenfolge
    # — Basis des Pfad-Preisvektors (Spec 10.2/11.1, tactics.path_targets).
    # None bei manuell konstruierten Test-MetaViews (Fallback: nur aktives Ziel).
    open_targets: list[dict] | None = None

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


def _am_cap_milestones(snap: dict) -> list[Milestone]:
    """AM-Cap-Makroplan (Spec 16.3/17.4) als ZUSAMMENHÄNGENDER Meilenstein-
    Block des RELIC_STATION_RUN: erst AM-Cap 5000 über Containment Chambers
    (100 AM-Cap je Einheit, space.js:582-602 — der Snapshot-Cap der
    Ressource hat Vorrang), dann das relicStation-Upgrade (workshop.js:
    1538-1550, 5000 AM + 100 Eludium). Unter AM-Cap 5000 skaliert der
    Beacon-Relic-Ertrag mit amMax/5000 herunter (space.js:718-720) — darum
    ist der Cap das erste Ziel. Halbfertige Cap-Investitionen außerhalb
    dieses Runs vermeidet der Block, weil er NUR im RELIC_STATION_RUN in
    die Meilensteinliste kommt (16.3)."""
    return [
        Milestone("am_cap_5000", "Antimatter-Cap 5000 (Containment Chambers)",
                  lambda s: A.res_cap(s, "antimatter") >= RELIC_STATION_AM_CAP,
                  {"kind": "space_build", "name": "containmentChamber"},
                  visible=lambda s: _space_building(s, "containmentChamber") is not None),
        Milestone("relic_station", "Relic Station erforschen (Workshop)",
                  lambda s: bool((A.upgrade(s, "relicStation") or {}).get("researched")),
                  {"kind": "workshop_upgrade", "name": "relicStation"},
                  visible=lambda s: A.upgrade(s, "relicStation") is not None),
    ]


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
    # Phase aus den operationalen Austrittskriterien (Kap. 9) — unabhängig
    # vom Run-Typ; das Cockpit erbt sie über MetaView.phase.
    phase = determine_phase(snap)
    if run_type in ("PRICE_RATIO_RUN", "CORE_META_RUN"):
        milestones = milestones + _perk_milestones(snap, next_perk)
    if run_type == "RELIC_STATION_RUN":
        # AM-Cap-Makroplan als zusammenhängendes Ziel (Spec 16.3/17.4):
        milestones = milestones + _am_cap_milestones(snap)

    active: Milestone | None = None
    next_research: dict | None = None
    rows: list[dict] = []
    open_targets: list[dict] = []
    for m in milestones:
        if m.done(snap):
            state = "done"
        elif active is None and m.visible(snap):
            state = "active"
            active = m
        else:
            state = "pending"
            # Nächstes offenes Forschungsziel HINTER dem aktiven Meilenstein:
            # fließt in die Soll-Allokation ein (12.2), damit Science nie
            # den Wert 0 hat, nur weil das Sofortziel ein Gebäude ist
            # (Nutzer-Fund: alle 6 Kitten als Woodcutter).
            if (next_research is None and m.target
                    and m.target.get("kind") == "research"):
                next_research = m.target
        if state in ("active", "pending") and m.target:
            # Offene Targets NICHT verwerfen: sie bilden den Pfad-Preisvektor
            # (Spec 10.2/11.1) — nähere Ziele wiegen dort mehr (Rang-Diskont).
            open_targets.append(m.target)
        rows.append({"id": m.id, "label": m.label, "state": state})
    if active is not None and active.target \
            and active.target.get("kind") == "research":
        next_research = None   # das aktive Ziel IST schon Forschung
    return MetaView(phase=phase, run_type=run_type, active=active,
                    milestones=rows, next_perk=next_perk,
                    run_variant=run_variant, run_plan=run_plan,
                    next_research=next_research, open_targets=open_targets)
