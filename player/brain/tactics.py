"""Taktischer Optimierer: Kandidaten + transparentes NetValue-Scoring.

Umsetzung von Spielmechanik-Spec Kap. 10–12 in vereinfachter Form:
- Engpass = Ressource mit der größten Zeit-bis-leistbar am aktiven Meilenstein
  (Schattenpreis-light: genau diese Ressource hat gerade Wert)
- Jede mögliche Aktion wird als Candidate mit additiven Score-Komponenten
  bewertet; die Komponenten sind im Cockpit einzeln sichtbar
- WAIT ist reguläre Aktion mit Grund und Weckbedingung (G-05)
- Deterministisches Tie-Breaking über die Action-ID (Anhang C.2)

Die Gewichte sind Heuristiken, keine exakte MPC-Lösung — bewusste
Vereinfachung (siehe docs/brain.md). Sie sind so gestaffelt, dass gilt:
Safety > Meilenstein > Jobs/Engpass > Unlocks > Cap-Schutz > Ökonomie > WAIT.
"""

from __future__ import annotations

import math
from typing import Any

from player.state import access as A
from player.state.derived import CATNIP_PER_FIELD_PER_SEC, project_catnip
from . import actions, chrono, frontier, policy, religion, shadow, timecrystal
from .records import Candidate

# Verbrauch eines Kittens (0,85 Catnip/Tick × 5 Ticks/s), Fallback für die
# Pro-Kopf-Rechnung, solange keine Kitten existieren:
CATNIP_PER_KITTEN_PER_SEC = 4.25

# Welcher Job produziert welche Ressource? (M1-Umfang)
RESOURCE_JOB = {
    "catnip": "farmer",
    "wood": "woodcutter",
    "minerals": "miner",
    "science": "scholar",
    "manpower": "hunter",
    "gold": "geologist",
    "coal": "geologist",
    "faith": "priest",
}

# Produktions-/Nutzwert-Zuordnung von Gebäuden (für generische Ökonomie-Werte).
BUILDING_PRODUCES = {
    "field": "catnip",
    "pasture": "catnip",        # senkt Verbrauch — wirkt wie Produktion
    "mine": "minerals",
    "lumberMill": "wood",
    "library": "science",
    "academy": "science",
    "observatory": "starchart",  # erhöht Astro-Event-Ertrag & Science
    "biolab": "science",
    "smelter": "iron",
    "calciner": "iron",
    "quarry": "minerals",
    "oilWell": "oil",
    "accelerator": "uranium",
    "reactor": "uranium",
}
HOUSING_BUILDINGS = {"hut", "logHouse", "mansion"}
STORAGE_BUILDINGS = {"barn", "warehouse", "harbor"}
# Energie-Erzeuger (Spec 16.4): bei Defizit priorisiert.
ENERGY_PRODUCERS = {"steamworks", "magneto", "solarFarm", "hydroPlant", "reactor"}
# Gebäude, die der generische Ökonomie-Score überhaupt anfasst
# (mint/brewery seit #35: echte Effekt-NetValues statt Whitelist-Skip):
ECONOMY_WHITELIST = (set(BUILDING_PRODUCES) | HOUSING_BUILDINGS | STORAGE_BUILDINGS
                     | ENERGY_PRODUCERS
                     | {"workshop", "unicornPasture", "amphitheatre", "tradepost",
                        "temple", "factory", "chapel", "aqueduct", "ziggurat",
                        "chronosphere", "mint", "brewery"})

# Craft-Rezepte zur Cap-Verlust-Vermeidung: Input-Ressource -> Craft-Name.
CAP_RELIEF_CRAFTS = {
    "wood": "beam",
    "minerals": "slab",
    "iron": "plate",
    "culture": "manuscript",
}

WAIT_SCORE = 0.01

# Reine Anzeige-Komponenten (Sekundenwerte der Schattenpreis-/CS-Rechnung) —
# sie fließen NICHT additiv in den Score ein; netValue/optionValue gehen
# normiert ein (siehe _score).
SHADOW_INFO_KEYS = ("costTime", "benefitTime", "netValue", "optionValue",
                    "jobScore", "csValue", "pollutionCost",
                    "tradeValue", "huntValue", "praiseValue",
                    "storageB", "storageC", "leaderValue", "policyValue",
                    "tapValue", "pactValue",
                    "rrValue", "furnaceValue", "shatterValue", "voidValue",
                    "tfValue", "potential", "savingFor", "allocDeficit")
# Normierung: 60 s NetValue ≙ 1 Scorepunkt, geklemmt auf ±1.2 — genug, um
# Ökonomie-Käufe (0.6) zu kippen, aber nie Safety/Meilenstein (3.0+).
NET_VALUE_SCALE = 60.0
NET_VALUE_CLAMP = 1.2
# Mindest-Zielzeitgewinn (JobScore-Differenz), ab dem sich eine
# Umschulung lohnt (Anti-Thrashing, Spec 12.2 Schritt 7):
REBALANCE_GAIN_MIN = 1.0
# Feste Job-Reihenfolge für deterministische Auswertung/Tie-Breaks:
JOB_ORDER = ("woodcutter", "farmer", "scholar", "miner",
             "hunter", "geologist", "priest")


def _score(comp: dict[str, float]) -> float:
    """Score aus Komponenten: Sekundenwerte (SHADOW_INFO_KEYS) zählen nicht
    additiv; netValue (Kaufregel 10.3) und optionValue (Optionswert 8.4)
    gehen normiert und geklemmt ein."""
    s = sum(v for k, v in comp.items() if k not in SHADOW_INFO_KEYS)
    for key in ("netValue", "optionValue"):
        if key in comp:
            s += max(-NET_VALUE_CLAMP, min(NET_VALUE_CLAMP,
                                           comp[key] / NET_VALUE_SCALE))
    return s


def fmt_duration(sec: float | None) -> str:
    if sec is None or not math.isfinite(sec):
        return "∞"
    if sec < 90:
        return f"{sec:.0f}s"
    return f"{sec / 60:.0f}:{sec % 60:02.0f} min"


# ================================================================ Engpass

def bottleneck_info(snap: dict, target: dict | None) -> dict | None:
    """Engpass am aktiven Meilenstein-Ziel (Spec 10.1, vereinfacht)."""
    prices = _target_prices(snap, target)
    if not prices:
        return None
    missing = A.missing_for(snap, prices)
    if not missing:
        return {"resource": None, "etaSeconds": 0, "missing": [], "affordable": True}
    eta, res = A.eta_to_afford(snap, prices)
    return {
        "resource": res,
        "etaSeconds": None if math.isinf(eta) else eta,
        "missing": missing,
        "affordable": False,
        "capBlocked": A.cap_blocks(snap, prices),
    }


# Referenz-Erstpreise für Zielgebäude, die das Spiel per unlockRatio erst
# ab einem Ressourcenanteil anzeigt (buildings.js 1.5.0.2: Mine erscheint
# z. B. erst ab 15 % ihres Holzpreises). Ohne Fallback wäre der Engpass
# null, sobald das Ziel unsichtbar ist — Jobs/Refine/Wait fielen aus
# (Live-Fund: Ziel „Erste Mine" bei 0 Holz).
# Referenz-Science-Preis für noch unsichtbare Forschungsziele in der
# Soll-Allokation (Größenordnung P0/P1-Techs; nur Gewichtung, kein Kauf):
REFERENCE_RESEARCH_SCIENCE = 500.0

REFERENCE_BUILD_PRICES: dict[str, list[dict]] = {
    "mine": [{"name": "wood", "val": 100}],
    "workshop": [{"name": "wood", "val": 100}, {"name": "minerals", "val": 400}],
    "smelter": [{"name": "minerals", "val": 200}],
    "tradepost": [{"name": "wood", "val": 500}, {"name": "minerals", "val": 200},
                  {"name": "gold", "val": 10}],
}


def _target_prices(snap: dict, target: dict | None) -> list[dict] | None:
    if not target:
        return None
    if target["kind"] == "build":
        b = A.building(snap, target["name"])
        if b and b.get("prices"):
            return b["prices"]
        return REFERENCE_BUILD_PRICES.get(target["name"])
    if target["kind"] == "research":
        t = A.tech(snap, target["name"])
        return t["prices"] if (t and not t["researched"]) else None
    if target["kind"] == "resource":
        # Ressourcen-Ziel (z. B. „10 Holz beschaffen"): wirkt wie ein Preisvektor.
        return [{"name": target["name"], "val": target["amount"]}]
    if target["kind"] == "perk":
        for p in snap.get("prestige", {}).get("perks", []):
            if p["name"] == target["name"] and not p["researched"]:
                return p["prices"]
        return None
    if target["kind"] == "space_program":
        for p in snap.get("space", {}).get("programs", []):
            if p["name"] == target["name"]:
                return p["prices"]
        return None
    if target["kind"] == "space_build":
        _, b = _space_building_entry(snap, target["name"])
        return b["prices"] if b else None
    if target["kind"] == "workshop_upgrade":
        u = A.upgrade(snap, target["name"])
        return u["prices"] if (u and not u.get("researched")) else None
    if target["kind"] == "religion_upgrade":
        for u in snap.get("religion", {}).get("upgrades", []):
            if u["name"] == target["name"] and not (u["noStackable"] and (u["on"] or u["val"])):
                return u["prices"]
        return None
    return None


def _space_building_entry(snap: dict, name: str) -> tuple[dict | None, dict | None]:
    """(Planet, Gebäude) eines Space-Gebäudes aus space.planets."""
    for planet in snap.get("space", {}).get("planets", []):
        for b in planet.get("buildings", []):
            if b["name"] == name:
                return planet, b
    return None, None


def _target_obj(snap: dict, target: dict | None) -> dict | None:
    if not target:
        return None
    if target["kind"] == "build":
        return A.building(snap, target["name"])
    if target["kind"] == "research":
        return A.tech(snap, target["name"])
    if target["kind"] == "perk":
        return next((p for p in snap.get("prestige", {}).get("perks", [])
                     if p["name"] == target["name"]), None)
    if target["kind"] == "space_program":
        return next((p for p in snap.get("space", {}).get("programs", [])
                     if p["name"] == target["name"]), None)
    if target["kind"] == "space_build":
        return _space_building_entry(snap, target["name"])[1]
    if target["kind"] == "workshop_upgrade":
        return A.upgrade(snap, target["name"])
    if target["kind"] == "religion_upgrade":
        return next((u for u in snap.get("religion", {}).get("upgrades", [])
                     if u["name"] == target["name"]), None)
    return None


# ================================================================ Kandidaten

def generate(snap: dict, meta_view, safety_result, *,
             horizon_scale: float = 1.0,
             relax_whitelist: bool = False,
             run_horizon_s: float | None = None) -> tuple[list[Candidate], dict | None]:
    """Erzeugt alle Kandidaten inkl. Scores; gibt (candidates, bottleneck) zurück.

    horizon_scale/relax_whitelist werden NUR von der Deadlock-Auflösung
    (resolve_deadlock, Spec 22.3) gesetzt: Horizontverdopplung der λ-/
    Payback-Bewertung bzw. Aufhebung der ECONOMY_WHITELIST-Suchraum-
    Heuristik. Sicherheitsinvarianten (blocked_types, foodRisk, Storage-
    Gates 11.3, Kaufregel 10.3) bleiben dabei UNVERÄNDERT.

    run_horizon_s (#39, Spec 10.4/6.4): erwartete Restlaufzeit bis zum
    GEPLANTEN Reset (reset.evaluate["etaSeconds"], vom Loop durchgereicht)
    — das Payback-Gate prüft dann gegen den echten Plan statt gegen die
    2×Spielzeit-Heuristik. Nach unten auf HORIZON_PLANNED_MIN geflöort
    (Anti-Deadlock), nach oben UNGEKLEMMT (6.4: lange Runs planen lang).
    None/∞ → run_horizon-Heuristik als Fallback."""
    target = meta_view.active.target if meta_view.active else None
    bn = bottleneck_info(snap, target)
    cands: list[Candidate] = []
    blocked = safety_result.blocked_types
    banking = _kitten_banking_mode(snap, bn)
    reserved = _reserved_resource(snap, bn, banking)

    # Schattenpreise EINMAL pro Zyklus über den PFAD-Preisvektor (#34,
    # Spec 10.2/11.1): aktives Ziel + Housing + offene Meilensteine,
    # rang-diskontiert. goal_prices bleibt der Sofortziel-Vektor für
    # Bottleneck/Sparlogik. Ohne Pfad bleiben die Dicts leer → die
    # Schwellen-Fallbacks der Kandidaten greifen (Sicherheitsnetz).
    goal_prices = _target_prices(snap, target)
    lam, lam_rate = path_lambdas(snap, meta_view)
    if run_horizon_s is not None and math.isfinite(run_horizon_s):
        base_horizon = max(run_horizon_s, shadow.HORIZON_PLANNED_MIN)
    else:
        base_horizon = shadow.run_horizon(snap)
    horizon = base_horizon * max(1.0, horizon_scale)

    _milestone_candidate(snap, target, bn, cands, blocked)
    _job_candidates(snap, bn, cands, lam_rate, goal_prices,
                    getattr(meta_view, 'next_research', None))
    _gather_candidates(snap, target, bn, cands)
    _research_candidates(snap, target, cands, lam, lam_rate)
    _building_candidates(snap, target, bn, cands, blocked, reserved, banking,
                         lam, horizon, relax_whitelist, lam_rate)
    if banking:
        _banking_candidates(snap, cands)
    _energy_candidates(snap, cands, lam, horizon)
    _leader_candidate(snap, cands, lam, goal_prices, horizon)
    _upgrade_candidates(snap, cands, lam, lam_rate)
    _policy_candidates(snap, meta_view.run_type, cands, lam, horizon)
    _hunt_candidate(snap, cands, lam)
    _craft_candidates(snap, target, bn, cands, lam)
    _trade_candidates(snap, bn, cands, lam)
    _praise_candidate(snap, cands, lam, horizon)
    _festival_candidate(snap, cands)
    _religion_candidates(snap, target, cands)
    _religion_ev_candidates(snap, cands, lam, horizon)
    _space_building_candidates(snap, target, bn, cands, lam)
    _time_candidates(snap, cands, lam, horizon, meta_view.run_type)
    _tempus_fugit_candidate(snap, cands, lam, horizon)
    _wait_candidate(snap, bn, cands, meta_view)
    # Sparlogik = DelayPenalty der Kaufregel 10.3 (Live-Fund: Library #3
    # wurde vom Holz gekauft, auf das eigentlich für Hütte #3 zu sparen war):
    _apply_saving_rule(snap, cands)

    # Deterministisch sortieren: Score absteigend, dann Action-ID (C.2).
    cands.sort(key=lambda c: (-c.score, c.action.id))
    return cands, bn


# Sparfenster (Nutzer-Fund „er spart nie auf die Hütte"): Die Spec kennt
# für die DelayPenalty (10.3) gar kein Fenster — dieses ist nur ein
# Anti-Einfrier-Schutz. 180 s waren viel zu eng: Früh liefert ein einzelner
# Woodcutter ~0,27 Holz/s, Hütte #3 (78 Holz) liegt damit bei ~290 s und
# wurde nie zum Sparziel — der Agent kaufte stattdessen Libraries vom
# Sparholz. 10 min decken alle Frühspiel-Sparziele; Käufe OHNE
# Ressourcenkonflikt (z. B. Felder für Catnip) laufen währenddessen weiter.
SAVING_HORIZON_S = 600.0


def _apply_saving_rule(snap: dict, cands: list[Candidate]) -> None:
    """DelayPenalty der Kaufregel 10.3 („Sparen"): Existiert ein noch
    unbezahlbarer Kandidat mit höherem Wert (`potential`) und endlicher
    Bezahlbarkeits-ETA ≤ SAVING_HORIZON_S, dann werden billigere machbare
    Käufe, die dessen fehlende Ressourcen verbrauchen, um die verursachte
    Verzögerung bestraft (delay/60 s, Clamp wie netValue). Fällt ihr Score
    dadurch unter 0, wartet der Agent — er spart. Kandidaten, die selbst
    wertvoller als das Sparziel sind (Meilenstein 3.0, Safety 10.0, höheres
    potential), bleiben unberührt."""
    targets = []
    for c in cands:
        if c.feasible or c.eta_seconds is None or not math.isfinite(c.eta_seconds):
            continue
        pot = c.components.get("potential", 0.0)
        if pot <= 0 and "milestone" in c.components:
            pot = 3.0   # unbezahlbares Meilensteinziel ist immer Sparziel
        if pot > 0 and c.eta_seconds <= SAVING_HORIZON_S:
            targets.append((pot, c))
    if not targets:
        return
    targets.sort(key=lambda t: (-t[0], t[1].eta_seconds, t[1].action.id))
    potential, target = targets[0]
    deltas_t = (target.action.predicted or {}).get("deltas", {})
    needed = {r: -v for r, v in deltas_t.items() if v < 0}
    if not needed:
        return
    for c in cands:
        if not c.feasible or c.action.type == "WAIT" or c.score >= potential:
            continue
        pred = c.action.predicted or {}
        if pred.get("stochastic"):
            continue
        delay = 0.0
        for r, v in pred.get("deltas", {}).items():
            if v >= 0 or r not in needed:
                continue
            rate = A.res_rate(snap, r)
            delay = max(delay, (-v) / rate if rate > 0
                        else NET_VALUE_CLAMP * NET_VALUE_SCALE)
        if delay > 0:
            # Ein Kauf, der das Sparziel verzögert, darf seinen Score nicht
            # aus dem eigenen netValue finanzieren: das Sparziel ist die
            # priorisierte Verwendung der Ressource (10.3). Ohne diese
            # Neutralisierung würde jeder Pfad-netValue am +Clamp (#34)
            # die DelayPenalty (−Clamp) strukturell überstimmen und der
            # Agent spart nie (genau der Live-Fund „Library #3 vom Sparholz").
            nv_bonus = max(0.0, min(NET_VALUE_CLAMP,
                                    c.components.get("netValue", 0.0)
                                    / NET_VALUE_SCALE))
            c.components["delayPenalty"] = -(min(NET_VALUE_CLAMP,
                                                 delay / NET_VALUE_SCALE)
                                             + nv_bonus)
            c.components["savingFor"] = 0.0   # Anzeige-Marker (Sparziel aktiv)
            c.score = _score(c.components)
    # WAIT nennt das Sparziel (Weckbedingung fürs Cockpit):
    for c in cands:
        if c.action.type == "WAIT":
            c.action.exec_spec["reason"] = (
                f"Spare auf {target.action.label} "
                f"(~{fmt_duration(target.eta_seconds)}) — "
                + c.action.exec_spec.get("reason", ""))
            break


def _reserved_resource(snap: dict, bn: dict | None, banking: bool = False) -> str | None:
    """Opportunitätskosten-Regel (Spec 10.2, vereinfacht):

    Ist der Engpass nur über eine Konversion lösbar (z. B. Wood ganz früh
    ausschließlich über „Refine catnip", solange es keine Woodcutter gibt),
    dann ist die Input-Ressource der Konversion reserviert — Ökonomie-Käufe,
    die sie verbrauchen, würden den Engpass verlängern und werden bestraft.
    Im Kitten-Bootstrap (Banking-Modus) ist Catnip ebenfalls reserviert:
    der Vorrat ist die Eintrittskarte für die erste Hütte.
    """
    if banking:
        return "catnip"
    if bn and bn.get("resource") == "wood" and A.job_count(snap, "woodcutter") == 0 \
            and A.res_rate(snap, "wood") <= 0.001:
        return "catnip"
    return None


def _kitten_banking_mode(snap: dict, bn: dict | None) -> bool:
    """Kitten-Bootstrap (fehlendes Glied der Engpasskette, Spec 12.1):

    Der Meilenstein-Engpass ist eine Job-Ressource (z. B. Science → Scholar),
    aber es existieren NOCH KEINE Kitten. Dann ist die effektive Aufgabe:
    Housing leistbar machen — d. h. Felder ausbauen und eine Catnip-Bank
    ansparen, bis die Saisonprojektion neue Kitten trägt. In diesem Modus:
    Felder = Engpasslöser, Catnip = reserviert (kein Refine-Abfluss außer
    für das Housing-Holz selbst), Housing bekommt einen Engpass-Bonus.
    """
    if snap.get("village", {}).get("kittens", 0) > 0:
        return False
    if not bn or not bn.get("resource"):
        return False
    return bn["resource"] in RESOURCE_JOB


# ---------------------------------------------------------------- Meilenstein

def _milestone_candidate(snap, target, bn, cands, blocked) -> None:
    obj = _target_obj(snap, target)
    if not obj or not target:
        return
    prices = _target_prices(snap, target)
    if prices is None:
        return

    if target["kind"] == "build":
        act = actions.buy_building(target["name"], obj["label"], obj["val"],
                                   prices=prices)
        if target["name"] in HOUSING_BUILDINGS and "housing" in blocked:
            cands.append(Candidate(act, 0.0, {"milestone": 0.0}, feasible=False,
                                   reject_reason="Food-Sicherheit blockiert Housing (I-01)"))
            return
    elif target["kind"] == "perk":
        if not obj.get("unlocked"):
            cands.append(Candidate(actions.buy_perk(target["name"], obj.get("label") or target["name"]),
                                   0.0, {"milestone": 0.0}, feasible=False,
                                   reject_reason="Perk noch nicht freigeschaltet (Metaphysics/Vorgänger fehlt)"))
            return
        act = actions.buy_perk(target["name"], obj.get("label") or target["name"],
                               prices=prices)
    elif target["kind"] == "space_program":
        act = actions.space_program(target["name"], obj.get("label") or target["name"],
                                    prices=prices)
    elif target["kind"] == "space_build":
        # Space-Gebäude als Meilenstein-Ziel (AM-Cap-Makroplan 16.3):
        # gleiche Action-Form wie _space_building_candidates (Panel = Planet).
        planet, b = _space_building_entry(snap, target["name"])
        deltas = actions.price_deltas(prices)
        act = actions.Action(
            id=f"space_bld:{target['name']}", type="BUY_BUILDING",
            label=f"Baue {b['label']} ({planet['label']}, Nr. {b['val'] + 1})",
            exec_spec={"kind": "click_button", "tab": "Space",
                       "panel": planet["label"], "title": b["label"], "batch": 1},
            expected=f"{b['label']} auf {b['val'] + 1}",
            predicted={"deltas": deltas, "stochastic": False} if deltas else None,
        )
    elif target["kind"] == "workshop_upgrade":
        act = actions.buy_upgrade(target["name"], obj.get("label") or target["name"],
                                  prices=prices)
        act = actions.buy_religion_upgrade(target["name"], obj.get("label") or target["name"],
                                           prices=prices)
    else:
        act = actions.research(target["name"], obj["label"], prices=prices)

    if A.affordable(snap, prices):
        comp = {"milestone": 3.0}
        if target["kind"] == "build":
            # Auch Meilenstein-Bauten geben in der Food-Krise kein Catnip aus;
            # sinnvolle Felder kommen dann als geprüfte Schutzaktion (safety.py).
            _apply_food_risk(snap, comp, prices)
        cands.append(Candidate(act, sum(comp.values()), comp))
    else:
        eta = bn.get("etaSeconds") if bn else None
        miss = ", ".join(f"{m['missing']:.0f} {m['name']}" for m in (bn or {}).get("missing", []))
        reason = f"noch nicht bezahlbar: fehlen {miss} (~{fmt_duration(eta)})"
        if bn and bn.get("capBlocked"):
            reason = f"Cap von {bn['capBlocked']} blockiert das Ziel — Storage nötig (11.3 A)"
        cands.append(Candidate(act, 0.0, {"milestone": 0.0}, feasible=False,
                               reject_reason=reason, eta_seconds=eta))


# ---------------------------------------------------------- Pfad-λ (#34)

# Kappung des Pfad-Preisvektors: ab Rang 12 ist das Rang-Gewicht
# 1/(1+k) ≤ 1/13 ≈ 8 % — vernachlässigbar gegen die vorderen Ziele, und
# die λ-Rechnung bleibt billig (2 ETA-Auswertungen je Preisposition).
PATH_MAX_TARGETS = 12


def path_targets(snap, meta_view) -> list[dict]:
    """Pfad-Preisvektor (#34, Spec 10.2/11.1): Liste von
    {"prices": [...], "weight": shadow.path_weight(rang), "label": ...}.

    Rangordnung (deterministisch, Diskontwahl in shadow.path_weight
    dokumentiert):
    - Rang 0: aktives Meilensteinziel (w = 1).
    - Rang 1: nächste Housing-Stufe, sofern die Kapazität voll ist —
      Kitten sind die Dauerressource des GANZEN Pfads, darum immer „nah"
      (gleiche Logik wie _allocation_prices; der Pfadvektor ist deren
      Obermenge).
    - Rang 2…: alle offenen Meilensteine des Runs (meta_view.open_targets)
      in Listenreihenfolge. Unauflösbare Targets (unsichtbar) werden
      übersprungen; für das ERSTE unauflösbare Forschungsziel greift der
      REFERENCE_RESEARCH_SCIENCE-Fallback (gleiche Falle wie 12.2: Science
      darf nie den Wert 0 haben, solange Forschung ansteht).
    Kappung bei PATH_MAX_TARGETS aufgelösten Einträgen."""
    out: list[dict] = []
    active_target = meta_view.active.target if meta_view.active else None
    active_prices = _target_prices(snap, active_target)
    if active_prices:
        out.append({"prices": active_prices, "weight": shadow.path_weight(0),
                    "label": "active"})
    village = snap.get("village", {})
    if village.get("maxKittens", 0) <= village.get("kittens", 0):
        for name in sorted(HOUSING_BUILDINGS):
            b = A.building(snap, name)
            if b and b.get("unlocked") and b.get("prices"):
                if not (active_target and active_target.get("kind") == "build"
                        and active_target.get("name") == name):
                    out.append({"prices": b["prices"],
                                "weight": shadow.path_weight(len(out)),
                                "label": f"housing:{name}"})
                break
    research_fallback_used = False
    for target in (getattr(meta_view, "open_targets", None) or []):
        if len(out) >= PATH_MAX_TARGETS:
            break
        if target == active_target:
            continue
        prices = _target_prices(snap, target)
        if not prices:
            if target.get("kind") == "research" and not research_fallback_used:
                # Ziel noch unsichtbar → Referenzpreis (einmal reicht: weitere
                # unsichtbare Forschung hätte dieselbe Science-Position).
                prices = [{"name": "science", "val": REFERENCE_RESEARCH_SCIENCE}]
                research_fallback_used = True
            else:
                continue
        out.append({"prices": prices, "weight": shadow.path_weight(len(out)),
                    "label": f"{target.get('kind')}:{target.get('name')}"})
    return out


def path_lambdas(snap, meta_view) -> tuple[dict, dict]:
    """(λ, λ_rate) über den Pfad-Preisvektor — der EINE λ-Satz des Zyklus."""
    pt = path_targets(snap, meta_view)
    if not pt:
        return {}, {}
    return (shadow.path_shadow_prices(snap, pt),
            shadow.path_rate_shadow_prices(snap, pt))


def lambda_top(lam: dict, lam_rate: dict, n: int = 8) -> list[dict]:
    """λ-Topliste fürs Cockpit (#34): die n wertvollsten Ressourcen des
    Pfads, deterministisch sortiert (−λ, Name), Werte gerundet."""
    rows = [{"name": name, "lam": round(val, 2),
             "lamRate": round(lam_rate.get(name, 0.0), 2)}
            for name, val in lam.items() if val > 0]
    rows.sort(key=lambda r: (-r["lam"], r["name"]))
    return rows[:n]


# ---------------------------------------------------------------- Jobs

def _allocation_prices(snap, goal_prices, next_research=None) -> list[dict] | None:
    """Preisvektor für die Soll-Allokation (12.2): Meilensteinziel PLUS die
    nächste Housing-Stufe PLUS das nächste offene Forschungsziel — sonst
    wäre eine Pfad-Ressource „wertlos", nur weil das Sofortziel sie nicht
    braucht (Nutzer-Funde: null Woodcutter im ganzen Run; danach alle 6
    Kitten als Woodcutter, weil das Holz-Ziel Science den Wert 0 gab).
    Hinweis (#34): der λ-Pfadvektor (path_targets) ist eine Obermenge
    hiervon; die Allokation behält bewusst ihren schlanken Vektor."""
    prices = list(goal_prices or [])
    village = snap.get("village", {})
    if village.get("maxKittens", 0) <= village.get("kittens", 0):
        for name in sorted(HOUSING_BUILDINGS):
            b = A.building(snap, name)
            if b and b.get("unlocked") and b.get("prices"):
                prices.extend(b["prices"])
                break
    if next_research:
        t = A.tech(snap, next_research.get("name"))
        if t and not t.get("researched") and t.get("prices"):
            prices.extend(t["prices"])
        elif not t:
            # Forschungsziel noch unsichtbar (gleiche Falle wie bei der
            # Mine/unlockRatio): Referenzpreis, damit Science in der
            # Allokation nie den Wert 0 hat, solange Forschung ansteht.
            prices.append({"name": "science",
                           "val": REFERENCE_RESEARCH_SCIENCE})
    return prices or None


def _min_farmers(snap, village) -> int:
    """Kleinste Farmerzahl, mit der die Saisonprojektion über der
    Warnschwelle bleibt (Food-Invariante I-01 als Allokations-Untergrenze)."""
    farmers_now = A.job_count(snap, "farmer")
    if not A.job_unlocked(snap, "farmer"):
        return 0
    happiness = village.get("happiness", 1.0) or 1.0
    rate = shadow.JOB_BASE_RATES["farmer"]["catnip"] * happiness
    demand = snap.get("derived", {}).get("food", {}).get("demandPerSec", 0.0)
    warn_floor = max(150.0, 120.0 * demand)
    total = int(village.get("kittens", 0) or 0)
    for f in range(0, total + 1):
        after = project_catnip(snap, demand_delta=(farmers_now - f) * rate)
        if after["projectedMin"] >= warn_floor:
            return f
    return farmers_now


def _job_candidates(snap, bn, cands, lam_rate=None, goal_prices=None,
                    next_research=None) -> None:
    village = snap.get("village", {})
    free = village.get("freeKittens", 0)
    food = snap.get("derived", {}).get("food", {})
    food_tight = food.get("status", "ok") != "ok"

    # Soll-Allokation (Spec 12.2, iterativ): Ziel + nächste Housing-Stufe
    # bestimmen, wie die Kitten verteilt sein SOLLTEN. Freie Kitten füllen
    # die größten Defizite; ohne freie Kitten wird pro Zyklus höchstens
    # ein Kitten vom größten Überschuss zum größten Defizit umgeschult.
    # Sie läuft auch in der WARNSTUFE (Live-Fund: sonst friert bei „warn"
    # die gesamte Umschulung ein und die Deadlock-Meldung feuert) — die
    # Food-Untergrenze steckt in min_farmers; nur bei „critical" hat die
    # Safety das Monopol.
    alloc = {}
    if food.get("status", "ok") != "critical":
        alloc_prices = _allocation_prices(snap, goal_prices, next_research)
        if alloc_prices:
            alloc = shadow.target_allocation(snap, alloc_prices,
                                             _min_farmers(snap, village))

    if free <= 0:
        if alloc:
            # Die Soll-Allokation ist die EINZIGE Umschul-Instanz, sobald
            # sie rechnen kann — die Legacy-Regeln (Engpass-Tausch, Cap-
            # Rebalance, Farmer-Freigabe) würden sonst gegen sie arbeiten
            # (Flattern). Sie bleiben Fallback ohne Preisdaten.
            _allocation_shift_candidate(snap, cands, village, food_tight, alloc)
        else:
            _job_rebalance_candidate(snap, bn, cands, village, food_tight,
                                     lam_rate)
        return

    # Mindestfarmer-/Food-Leitplanke hat VORRANG vor jeder λ-Bewertung:
    if food_tight and A.job_unlocked(snap, "farmer"):
        cands.append(Candidate(
            actions.assign_job("farmer", "Farmer", 1), 2.6,
            {"jobValue": 1.6, "safety": 1.0},
        ))
        return

    # Freies Kitten → größtes Allokations-Defizit (12.2 Schritt 4):
    if alloc:
        deficits = sorted(((alloc[j] - A.job_count(snap, j), j) for j in alloc),
                          key=lambda t: (-t[0], shadow.ALLOC_JOB_ORDER.index(t[1])))
        if deficits and deficits[0][0] > 0:
            job = deficits[0][1]
            label = next((j["title"] for j in village.get("jobs", [])
                          if j["name"] == job), job)
            cands.append(Candidate(actions.assign_job(job, label, 1), 2.4,
                                   {"jobValue": 2.4, "allocDeficit": 0.0}))
            return

    # JobScore-Zuweisung (Spec 12.2): freies Kitten dem Job mit dem
    # höchsten positiven Zielzeitgewinn pro Sekunde. Ohne λ-Daten (leere
    # Preise / keine Rate) Fallback: Engpass-Mapping, dann Balance.
    job = None
    src = None
    job_sc = 0.0
    if lam_rate:
        scored = [(shadow.job_score(snap, j, lam_rate), j)
                  for j in JOB_ORDER if A.job_unlocked(snap, j)]
        scored = [(s, j) for s, j in scored if s > 1e-9]
        if scored:
            scored.sort(key=lambda t: (-t[0], t[1]))   # deterministisch
            job_sc, job = scored[0]
            src = "JobScore"
    if not job:
        src = "Engpass"
        if bn and bn.get("resource"):
            job = RESOURCE_JOB.get(bn["resource"])
        if not job or not A.job_unlocked(snap, job):
            src = "Balance"
            unlocked = [j for j in JOB_ORDER if A.job_unlocked(snap, j)]
            if unlocked:
                job = min(unlocked, key=lambda j: (A.job_count(snap, j), unlocked.index(j)))
    if job:
        label = next((j["title"] for j in village.get("jobs", []) if j["name"] == job), job)
        comp = {"jobValue": 2.4}
        if src == "JobScore":
            comp["jobScore"] = job_sc          # Sekundenwert, nur Anzeige
        cands.append(Candidate(actions.assign_job(job, label, 1), 2.4, comp))
        if src == "Engpass":
            cands[-1].components["bottleneck"] = 0.0  # nur Anzeige-Marker


def _allocation_shift_candidate(snap, cands, village, food_tight,
                                alloc: dict[str, int]) -> bool:
    """Konvergenz zur Soll-Allokation (12.2 Schritt 7): ein Kitten vom
    größten Überschuss-Job zum größten Defizit-Job — nur ganze Defizite
    (inhärente Hysterese). Farmer-Hysterese-Band (Anti-Flattern,
    Nutzer-Fund „4. Kitten springt Farmer↔Woodcutter"): Ein Farmer wird
    nur abgezogen, wenn die Projektion OHNE ihn die 1.5-fache Warnschwelle
    hält — zwischen 1.0× (Untergrenze zieht Farmer an) und 1.5× passiert
    bewusst nichts."""
    deficits = sorted(((alloc[j] - A.job_count(snap, j), j) for j in alloc),
                      key=lambda t: (-t[0], shadow.ALLOC_JOB_ORDER.index(t[1])))
    surpluses = sorted(((A.job_count(snap, j) - alloc[j], j) for j in alloc),
                       key=lambda t: (-t[0], shadow.ALLOC_JOB_ORDER.index(t[1])))
    if not deficits or not surpluses:
        return False
    d_count, d_job = deficits[0]
    if d_count < 1:
        return False
    for s_count, s_job in surpluses:
        if s_count < 1 or s_job == d_job:
            continue
        if s_job == "farmer":
            if food_tight or not _farmer_release_safe(snap, village):
                continue
        label = next((j["title"] for j in village.get("jobs", [])
                      if j["name"] == d_job), d_job)
        cands.append(Candidate(
            actions.shift_job(s_job, d_job, label, 1), 2.2,
            {"jobValue": 1.2, "allocDeficit": 0.0}))
        return True
    return False


def _farmer_release_safe(snap, village) -> bool:
    """Hysterese-Band der Farmer-Freigabe: Projektion mit einem Farmer
    weniger muss die FARMER_RELEASE_MARGIN-fache Warnschwelle halten."""
    happiness = village.get("happiness", 1.0) or 1.0
    rate = shadow.JOB_BASE_RATES["farmer"]["catnip"] * happiness
    after = project_catnip(snap, demand_delta=rate)
    demand = snap.get("derived", {}).get("food", {}).get("demandPerSec", 0.0)
    warn_floor = max(150.0, 120.0 * demand)
    return after["projectedMin"] >= warn_floor * FARMER_RELEASE_MARGIN


def _job_rebalance_candidate(snap, bn, cands, village, food_tight,
                             lam_rate=None) -> None:
    """Lokale Tauschoperation (Spec 12.2 Schritt 7): Der Engpass-Job ist
    komplett unbesetzt und es gibt keine freien Kitten → ein Kitten aus dem
    größten anderen Job umschulen. `job_count == 0` verhindert Thrashing
    (höchstens ein Tausch-Kandidat pro Zyklus). Mit λ-Daten zusätzlich:
    der Tausch muss sich lohnen — JobScore(Ziel) − JobScore(Spender) >
    REBALANCE_GAIN_MIN; ohne λ-Daten bleibt das bisherige Verhalten."""
    if bn and bn.get("resource"):
        job = RESOURCE_JOB.get(bn["resource"])
        if job and A.job_unlocked(snap, job) and A.job_count(snap, job) == 0:
            donors = [j for j in village.get("jobs", [])
                      if j["name"] != job and j["value"] > 0
                      and not (j["name"] == "farmer" and food_tight)]
            if donors:
                biggest = max(donors, key=lambda j: (j["value"], j["name"]))
                comp = {"jobValue": 1.2, "bottleneck": 1.0}
                ok = True
                if lam_rate:
                    gain = shadow.job_score(snap, job, lam_rate)
                    loss = shadow.job_score(snap, biggest["name"], lam_rate)
                    ok = gain - loss > REBALANCE_GAIN_MIN
                    comp["jobScore"] = gain - loss   # Sekundenwert, nur Anzeige
                if ok:
                    label = next((j["title"] for j in village.get("jobs", [])
                                  if j["name"] == job), job)
                    cands.append(Candidate(
                        actions.shift_job(biggest["name"], job, label, 1), 2.2, comp))
                    return

    # Cap-Rebalance (Spec 11.1: Ressourcen mit λ=0 dürfen am Cap stehen —
    # aber kein Kitten darf für eine VOLLE Ressource arbeiten). Live-Fund:
    # beide Kitten Scholars bei Science am Cap, niemand fällt Holz. Läuft
    # auch ohne Engpass-Daten (bn null, wenn das Zielgebäude per
    # unlockRatio noch unsichtbar ist). Ein Tausch pro Zyklus.
    if _cap_rebalance_candidate(snap, cands, village, food_tight, lam_rate):
        return

    # Farmer-Freigabe (Nutzer-Fund: Winter-Notfarmer blieben nach der
    # Gefahr sitzen — die Zuweisung wurde nie reevaluiert). Zurückschulen,
    # wenn die Saisonprojektion auch mit einem Farmer WENIGER deutlich
    # über der Warnschwelle bliebe (Marge 1.5 gegen Saisonwechsel-Flattern).
    _farmer_release_candidate(snap, cands, village, food_tight, lam_rate)


FARMER_RELEASE_MARGIN = 1.5


def _farmer_release_candidate(snap, cands, village, food_tight,
                              lam_rate=None) -> None:
    if food_tight or A.job_count(snap, "farmer") <= 0:
        return
    happiness = village.get("happiness", 1.0) or 1.0
    farmer_rate = shadow.JOB_BASE_RATES["farmer"]["catnip"] * happiness
    # Was-wäre-wenn: ein Farmer weniger = weniger Catnip-Produktion
    # (als Mehrverbrauch modelliert, gleiche Projektionsmechanik wie I-01):
    after = project_catnip(snap, demand_delta=farmer_rate)
    food = snap.get("derived", {}).get("food", {})
    demand = food.get("demandPerSec", 0.0)
    warn_floor = max(150.0, 120.0 * demand)
    if after["projectedMin"] < warn_floor * FARMER_RELEASE_MARGIN:
        return
    targets = [t for t in JOB_ORDER if t != "farmer" and A.job_unlocked(snap, t)]
    if not targets:
        return
    if lam_rate:
        scored = sorted(((shadow.job_score(snap, t, lam_rate), t) for t in targets),
                        key=lambda x: (-x[0], x[1]))
        if scored[0][0] <= 1e-9:
            return   # kein Job mit positivem Grenzwert — Farmer schadet nicht
        target_job = scored[0][1]
    else:
        target_job = min(targets, key=lambda t: (A.job_count(snap, t),
                                                 JOB_ORDER.index(t)))
    label = next((j["title"] for j in village.get("jobs", [])
                  if j["name"] == target_job), target_job)
    cands.append(Candidate(
        actions.shift_job("farmer", target_job, label, 1), 2.0,
        {"jobValue": 1.2, "foodSafe": 0.8}))


def _cap_rebalance_candidate(snap, cands, village, food_tight,
                             lam_rate=None) -> bool:
    """Kitten aus einem Job abziehen, dessen Ertragsressource(n) voll sind
    (Produktion läuft ins Cap = wertlos), hin zum besten nicht-vollen Job."""
    def _capped(res: str) -> bool:
        cap = A.res_cap(snap, res)
        return cap > 0 and A.res_value(snap, res) >= cap * 0.975

    donors = []
    for j in sorted(village.get("jobs", []), key=lambda j: j["name"]):
        name, count = j["name"], j["value"]
        outputs = shadow.JOB_BASE_RATES.get(name)
        if count <= 0 or not outputs:
            continue
        if name == "farmer" and food_tight:
            continue
        if all(_capped(res) for res in outputs):
            donors.append(j)
    if not donors:
        return False
    donor = max(donors, key=lambda j: (j["value"], j["name"]))
    # Bester Zieljob: JobScore, sonst dünnster freigeschalteter Basisjob —
    # in beiden Fällen keiner, dessen Ertrag selbst schon voll ist.
    targets = [t for t in JOB_ORDER
               if t != donor["name"] and A.job_unlocked(snap, t)
               and not all(_capped(r) for r in shadow.JOB_BASE_RATES.get(t, {}))]
    if not targets:
        return False
    if lam_rate:
        scored = sorted(((shadow.job_score(snap, t, lam_rate), t) for t in targets),
                        key=lambda x: (-x[0], x[1]))
        target_job = scored[0][1]
    else:
        target_job = min(targets, key=lambda t: (A.job_count(snap, t),
                                                 JOB_ORDER.index(t)))
    label = next((j["title"] for j in village.get("jobs", [])
                  if j["name"] == target_job), target_job)
    cands.append(Candidate(
        actions.shift_job(donor["name"], target_job, label, 1), 2.2,
        {"jobValue": 1.2, "capLoss": 1.0}))
    return True


# ---------------------------------------------------------------- Sammeln/Veredeln

def _gather_candidates(snap, target, bn, cands) -> None:
    # Catnip von Hand: nur sinnvoll, solange Catnip der Engpass ist
    # (ganz früh oder wenn die Felder noch nicht tragen).
    fields = A.bld_val(snap, "field")
    catnip_bottleneck = bn and bn.get("resource") == "catnip"
    if fields < 1:
        cands.append(Candidate(actions.gather_catnip(10), 2.5,
                               {"milestone": 1.5, "bottleneck": 1.0}))
    elif catnip_bottleneck and A.res_rate(snap, "catnip") < 2.0:
        cands.append(Candidate(actions.gather_catnip(10), 0.8, {"bottleneck": 0.8}))

    # Cap-Ventil (11.4, werterhaltender Craft — Live-Fund: 55 Felder
    # produzieren ins volle Catnip-Cap, 0 Holz): Catnip ≥ 92 % Cap und
    # Holz hat Platz → Refine unabhängig vom Engpass. Score capLoss wie
    # die übrigen Cap-Schutz-Kandidaten.
    catnip_val = A.res_value(snap, "catnip")
    cat_cap = A.res_cap(snap, "catnip")
    wood_cap = A.res_cap(snap, "wood")
    if (cat_cap > 0 and catnip_val >= 0.92 * cat_cap and catnip_val >= 100
            and (wood_cap <= 0 or A.res_value(snap, "wood") < wood_cap * 0.99)):
        batch = max(1, min(5, int(catnip_val // 100)))
        comp = {"capLoss": 1.5}
        cands.append(Candidate(actions.refine_catnip(batch), _score(comp), comp))
        return   # kein zweiter Refine-Kandidat aus dem Engpass-Zweig nötig

    # Refine: Holz aus Catnip, solange es keine/kaum Woodcutter gibt.
    wood_needed = bn and bn.get("resource") == "wood"
    if wood_needed and A.job_count(snap, "woodcutter") == 0:
        if catnip_val >= 100:
            missing_wood = next((m["missing"] for m in bn.get("missing", []) if m["name"] == "wood"), 0)
            batch = max(1, min(5, int(catnip_val // 100), math.ceil(missing_wood)))
            comp = {"bottleneck": 2.0}
            _apply_food_risk(snap, comp, [{"name": "catnip", "val": 100 * batch}])
            cands.append(Candidate(actions.refine_catnip(batch), sum(comp.values()), comp))
        else:
            # Konversions-Input reicht noch nicht (Live-Deadlock-Fund):
            # Refine als sichtbar-abgelehnter Kandidat MIT endlicher ETA
            # plus aktives Sammeln — sonst stünde hier nur WAIT und die
            # Deadlock-Erkennung schlüge fälschlich an (22.3).
            eta = _conversion_eta(snap, bn)
            cands.append(Candidate(
                actions.refine_catnip(1), 0.0, {"bottleneck": 0.0},
                feasible=False,
                reject_reason=(f"fehlen {100 - catnip_val:.0f} catnip für Refine "
                               f"(~{fmt_duration(eta)})")))
            comp = {"bottleneck": 0.3}
            _apply_food_risk(snap, comp, [{"name": "catnip", "val": 10}])
            score = sum(comp.values())
            if score > 0:
                cands.append(Candidate(actions.gather_catnip(10), score, comp))


# ---------------------------------------------------------------- Forschung

# OptionValue-Referenztabelle (Spec 8.4/13.3): Rate-Effekte der wichtigsten
# Frühspiel-Techs aus der Referenzversion — diese Techs liegen zugleich auf
# dem Meilensteinpfad (meta.P0_MILESTONES) bzw. öffnen eine neue
# Progressionsschicht (13.3-Klassen). ΔRate = Produktion des ERSTEN
# freigeschalteten Trägers (1 Job / 1 Gebäude, ×5 Ticks/s):
# - agriculture → Farmer-Job (science.js:31-34 unlocks jobs:["farmer"];
#   village.js:27-33 modifiers catnip 1/Tick) → 5.0/s
# - archery     → Hunter-Job (science.js:44-47; village.js:56-62
#   manpower 0.06/Tick) → 0.3/s
# - mining      → Mine + Miner (science.js:56-59 buildings:["mine"];
#   village.js:67-73 minerals 0.05/Tick) → 0.25/s
# - metal       → Smelter (science.js:68-70 buildings:["smelter"];
#   buildings.js:1019 ironPerTickAutoprod 0.02/Tick) → 0.1/s
# - construction→ Lumber Mill (science.js:124-127 buildings inkl.
#   "lumberMill"; ≈ 1 Woodcutter-Äquivalent, village.js:15-21
#   wood 0.018/Tick) → 0.09/s
TECH_OPTION_RATE_EFFECTS: dict[str, dict[str, float]] = {
    "agriculture": {"catnip": 5.0},
    "archery": {"manpower": 0.3},
    "mining": {"minerals": 0.25},
    "metal": {"iron": 0.1},
    "construction": {"wood": 0.09},
}

# Analog für die frühen Workshop-Upgrades: (Job, Ressource, Ratio) —
# workshop.js:10-15 mineralHoes catnipJobRatio 0.5; :24-29 ironHoes 0.3;
# :37-42 mineralAxes woodJobRatio 0.7; :51-56 ironAxes 0.5. ΔRate =
# Ratio × Jobbesetzung × Basisrate (shadow.JOB_BASE_RATES).
UPGRADE_OPTION_JOB_RATIO: dict[str, tuple[str, str, float]] = {
    "mineralHoes": ("farmer", "catnip", 0.5),
    "ironHoes": ("farmer", "catnip", 0.3),
    "mineralAxes": ("woodcutter", "wood", 0.7),
    "ironAxes": ("woodcutter", "wood", 0.5),
}


def _option_value(lam_rate, rate_delta: dict[str, float]) -> float:
    """OptionValue(m) = E[T_F | ohne m] − E[T_F | mit m] (Spec 8.4) als
    dokumentierte Näherung: die Projektion MIT dem Unlock-Effekt verkürzt
    die Ziel-ETA um Σ λ_rate_i · ΔRate_i Sekunden (λ_rate = Zielzeitgewinn
    pro dauerhafter Einheit/s, shadow.rate_shadow_prices). Nur Rate-Effekte
    aus der gamefiles-Referenz; 0.0 ohne λ_rate-Daten → Fallback fester
    Unlock-Score."""
    if not lam_rate or not rate_delta:
        return 0.0
    return sum(lam_rate.get(res, 0.0) * dr for res, dr in rate_delta.items())


def _research_candidates(snap, target, cands, lam=None, lam_rate=None) -> None:
    target_name = target.get("name") if target and target["kind"] == "research" else None
    affordable_techs = []
    for t in snap.get("science", {}).get("techs", []):
        if t["researched"] or not t["unlocked"] or t["name"] == target_name:
            continue
        if A.affordable(snap, t["prices"]):
            affordable_techs.append(t)
    # Unlock-first-Regel (13.3): Forschung ist fast immer wertvoll.
    # Determinismus: billigste zuerst, dann Name.
    affordable_techs.sort(key=lambda t: (sum(p["val"] for p in t["prices"]), t["name"]))
    for t in affordable_techs[:2]:
        comp = {"unlock": 1.9}
        # Sekundenkosten transparent machen — Unlocks werden aber nie durch
        # die Payback-Regel gesperrt (Spec 10.4):
        ct = shadow.cost_time(t["prices"], lam) if lam else 0.0
        if ct > 1e-9:
            comp["costTime"] = ct
        # Optionswert (8.4): kein Pauschalbonus — Techs der Referenztabelle
        # bekommen die berechnete Ziel-ETA-Verkürzung als Sekundenwert, der
        # normiert in den Score eingeht; sonst bleibt der feste Unlock-Score.
        ov = _option_value(lam_rate, TECH_OPTION_RATE_EFFECTS.get(t["name"], {}))
        if ov > 1e-9:
            comp["optionValue"] = ov
        cands.append(Candidate(actions.research(t["name"], t["label"], prices=t["prices"]),
                               _score(comp), comp))


# ---------------------------------------------------------------- Gebäude

def _banking_candidates(snap, cands) -> None:
    """Kitten-Bootstrap-Zusatzkandidaten: Holz für das Housing selbst.

    Catnip ist im Banking-Modus reserviert — mit einer Ausnahme: das Holz,
    das das billigste Housing-Gebäude selbst kostet, darf veredelt werden
    (sonst wäre die Hütte nie leistbar)."""
    hut = A.building(snap, "hut")
    if hut is None:
        return
    wood_needed = sum(p["val"] for p in hut["prices"] if p["name"] == "wood")
    wood_have = A.res_value(snap, "wood")
    missing = wood_needed - wood_have
    if missing <= 0 or A.res_value(snap, "catnip") < 100:
        return
    batch = max(1, min(5, int(A.res_value(snap, "catnip") // 100), math.ceil(missing)))
    cands.append(Candidate(actions.refine_catnip(batch), 1.5,
                           {"bottleneck": 1.5}))


def _building_candidates(snap, target, bn, cands, blocked, reserved=None,
                         banking=False, lam=None, horizon=None,
                         relax_whitelist=False, lam_rate=None) -> None:
    target_name = target.get("name") if target and target["kind"] == "build" else None
    prices_target = _target_prices(snap, target)
    cap_blocked_res = A.cap_blocks(snap, prices_target) if prices_target else None
    horizon = horizon if horizon is not None else shadow.HORIZON_MIN

    for b in snap.get("buildings", []):
        name = b["name"]
        if name == target_name or not b["unlocked"]:
            continue
        # ECONOMY_WHITELIST ist eine reine SUCHRAUM-Heuristik — die
        # Deadlock-Auflösung (22.3) darf sie aufheben (relax_whitelist);
        # alle Sicherheits-Gates weiter unten bleiben unverändert.
        if name not in ECONOMY_WHITELIST and not relax_whitelist:
            continue
        if not A.affordable(snap, b["prices"]):
            # Unbezahlbares Housing ist ein SPARZIEL (Kaufregel 10.3,
            # DelayPenalty): als infeasible-Kandidat mit potential + ETA
            # listen, damit _apply_saving_rule billigere Käufe bestraft,
            # die das Sparziel verzögern würden (Live-Fund: Library #3
            # verbrauchte das Holz für Hütte #3).
            if name in HOUSING_BUILDINGS:
                comp, reject = _housing_eval(snap, name, b, blocked,
                                             lam, lam_rate, horizon)
                if not reject:
                    eta, _res = A.eta_to_afford(snap, b["prices"])
                    if math.isfinite(eta):
                        comp["potential"] = _score(comp)
                        cands.append(Candidate(
                            actions.buy_building(name, b["label"], b["val"],
                                                 prices=b["prices"]),
                            0.0, comp, feasible=False,
                            reject_reason=(f"Sparziel: noch nicht bezahlbar "
                                           f"(~{fmt_duration(eta)})"),
                            eta_seconds=eta))
            continue

        energy_deficit = snap.get("derived", {}).get("energy", {}).get("balance", 0) < 0

        comp: dict[str, float] = {}
        if name in ENERGY_PRODUCERS and energy_deficit:
            # Energie-Defizit drosselt Produktion global — Erzeuger vorziehen (16.4).
            comp["energy"] = 2.0
        elif name in STORAGE_BUILDINGS:
            # Storage-Regel 11.3: zulässig nur, wenn mindestens eine der
            # Bedingungen A–D erfüllt ist (siehe _storage_eval).
            comp, reject = _storage_eval(snap, name, b, bn, cap_blocked_res,
                                         lam, horizon)
            if reject:
                cands.append(Candidate(
                    actions.buy_building(name, b["label"], b["val"], prices=b["prices"]), 0.0,
                    dict(comp), feasible=False, reject_reason=reject))
                continue
        elif name in HOUSING_BUILDINGS:
            comp, reject = _housing_eval(snap, name, b, blocked,
                                         lam, lam_rate, horizon)
            if reject:
                cands.append(Candidate(
                    actions.buy_building(name, b["label"], b["val"], prices=b["prices"]), 0.0,
                    dict(comp), feasible=False, reject_reason=reject))
                continue
            if banking:
                comp["bottleneck"] = 1.0   # Kitten SIND der Engpass (Bootstrap)
        elif banking and name == "field":
            # Kitten-Bootstrap: Felder heben die Projektion Richtung
            # Housing-Schwelle — aber nur kaufen, wenn der Kauf die
            # Projektion tatsächlich verbessert (gleiche Prüfung wie Safety).
            price = sum(p["val"] for p in b["prices"] if p["name"] == "catnip")
            food = snap.get("derived", {}).get("food", {})
            after = project_catnip(snap, stock_delta=-price,
                                   field_rate_delta=CATNIP_PER_FIELD_PER_SEC)
            if after["projectedMin"] > food.get("projectedMin", 0):
                comp["bottleneck"] = 1.8
            else:
                cands.append(Candidate(
                    actions.buy_building(name, b["label"], b["val"], prices=b["prices"]), 0.0,
                    {"bottleneck": 0.0}, feasible=False,
                    reject_reason="Feldkauf würde die Catnip-Bank fürs Housing schwächen"))
                continue
        elif BUILDING_PRODUCES.get(name) and bn and BUILDING_PRODUCES[name] == bn.get("resource"):
            comp["bottleneck"] = 1.8   # produziert genau den Engpass
        elif name == "workshop" and A.bld_val(snap, "workshop") == 0:
            comp["unlock"] = 1.7       # erste Werkstatt schaltet Crafts frei
        elif name == "amphitheatre" and snap.get("village", {}).get("happiness", 1.0) < 1.0:
            comp["happiness"] = 1.2    # unglückliche Kitten produzieren weniger
        elif name == "chronosphere":
            # CS-Zielzahl-Suche (Spec 19.1): kaufen nur, solange der Bestand
            # unter der optimalen Zahl liegt — nicht mehr opportunistisch.
            n_target, cs_detail = chrono.optimal_chronosphere_count(snap, lam=lam)
            if n_target is None:
                comp["economy"] = 1.2  # Fallback: keine CS-Daten → Altverhalten
            elif b["val"] >= n_target:
                cands.append(Candidate(
                    actions.buy_building(name, b["label"], b["val"], prices=b["prices"]), 0.0,
                    {"economy": 0.0}, feasible=False,
                    reject_reason=(f"Chronosphere-Zielzahl {n_target} erreicht "
                                   f"(CS-Suche 19.1, Bestand {b['val']})")))
                continue
            else:
                comp["economy"] = 1.2  # Carryover über Resets (Spec 19.1)
                if cs_detail.get("csValueNext") is not None:
                    comp["csValue"] = cs_detail["csValueNext"]  # Sekundenwert, Anzeige
        else:
            comp["economy"] = 0.6      # generischer Ausbau

        # --- Schattenpreis-Ökonomie (Spec 10.2–10.4) für Produktionsgebäude:
        # Sekundenwerte als transparente Komponenten; NetValue fließt über
        # _score normiert ein. Safety-/Unlock-/Energie-/Storage-/Housing-
        # Käufe und der Banking-Modus bleiben unberührt (Vorrangregeln).
        # Seit #35 zählt jedes Gebäude mit Effekt-Daten (Snapshot) oder
        # BUILDING_PRODUCES-Fallback — Steamworks/Magneto/Factory/
        # Tradepost/Mint/Brewery bekommen echte NetValues statt economy 0.6.
        # Eligibility statt „ΔRate nicht leer": auch ein LEERES Delta muss
        # durchs Payback-Gate (nutzlose Produktionsgebäude, Benefit 0).
        lam_eligible = (lam and not banking
                        and not any(k in comp for k in ("storage", "energy", "housing"))
                        and (b.get("effects") or name in BUILDING_PRODUCES))
        if lam_eligible:
            rate_delta = _building_rate_delta(snap, b)
            cost_t = shadow.cost_time(b["prices"], lam)
            ben_t = shadow.benefit_time(rate_delta, lam, horizon)
            # Pollution als Zeitkostenterm (#35): verlangsamte Kitten-
            # Ankünfte, λ-bewertet (siehe _pollution_cost_time).
            poll_cost = _pollution_cost_time(snap, b.get("effects") or {},
                                             horizon, lam_rate)
            if cost_t > 1e-9 or abs(ben_t) > 1e-9 or poll_cost > 1e-9:
                comp["costTime"] = cost_t
                comp["benefitTime"] = ben_t
                if poll_cost > 1e-9:
                    comp["pollutionCost"] = poll_cost
                comp["netValue"] = shadow.net_value(ben_t, cost_t + poll_cost)
                # Payback-Gate (10.4): NUR reine Produktions-/Ökonomiekäufe.
                # Engpasslöser gelten als zwingende Dependency des Ziels.
                # Netto-negativer Nutzen (z. B. Steamworks-coalRatioGlobal
                # −80 %) → payback() liefert bei ≤ 0 sauber inf → Ablehnung.
                if "bottleneck" not in comp and cost_t > 1e-9:
                    pb = shadow.payback(cost_t + poll_cost, ben_t / horizon)
                    if pb > horizon:
                        cands.append(Candidate(
                            actions.buy_building(name, b["label"], b["val"], prices=b["prices"]),
                            0.0, dict(comp), feasible=False,
                            reject_reason=(f"Payback {fmt_duration(pb)} > "
                                           f"Run-Horizont {fmt_duration(horizon)} "
                                           f"(Payback-Regel 10.4)")))
                        continue

        # Opportunitätskosten: Kauf verbraucht die für den Engpass reservierte
        # Ressource (z. B. Catnip, das eigentlich zu Holz veredelt werden muss).
        # Die Strafe drückt generische Käufe unter Null — und Aktionen mit
        # negativem NetValue werden nie ausgeführt (Kaufregel 10.3).
        if reserved and any(p["name"] == reserved for p in b["prices"]) \
                and "bottleneck" not in comp and "storage" not in comp:
            comp["opportunity"] = -0.7

        # foodRisk (I-01): In der Food-Krise gibt niemand Catnip für
        # Nicht-Schutz-Käufe aus. (Das geprüfte Schutz-Feld kommt separat
        # aus safety.py und trägt diese Strafe nicht.)
        _apply_food_risk(snap, comp, b["prices"])

        score = _score(comp)
        cands.append(Candidate(actions.buy_building(name, b["label"], b["val"], prices=b["prices"]), score, comp))


def _building_rate_delta(snap, b: dict) -> dict[str, float]:
    """Multi-Ressourcen-ΔRate des nächsten Exemplars in Einheiten/s (#35).

    Mit Snapshot-Effekten (b["effects"], buildings.js buildingsData):
    echte Bewertung über _rate_delta_from_effects — Produktion UND
    Verbrauch, mehrressourcig. Ohne Effekte (Alt-Fixtures) das
    Bestandsverhalten als Fallback:
    - field: bekannte Basisrate × aktueller Saisonmodifikator
    - pasture: senkt den Verbrauch um 0,5 % des Catnip-Bedarfs
    - sonst: beobachtete Netto-Rate / Gebäudeanzahl; erstes Exemplar ohne
      Bestandsdaten ≈ +10 % der laufenden Produktion (Ratio-Gebäude).
    Leeres Dict → benefit_time = 0, der Aufrufer-Fallback greift."""
    if b.get("effects"):
        return _rate_delta_from_effects(snap, b)
    name = b["name"]
    if name == "field":
        mod = snap.get("calendar", {}).get("currentCatnipModifier", 1.0) or 1.0
        return {"catnip": CATNIP_PER_FIELD_PER_SEC * mod}
    if name == "pasture":
        demand = snap.get("derived", {}).get("food", {}).get("demandPerSec", 0.0)
        return {"catnip": 0.005 * demand} if demand > 0 else {}
    produces = BUILDING_PRODUCES.get(name)
    if not produces:
        return {}
    val = A.bld_val(snap, name)
    rate = A.res_rate(snap, produces)
    if rate <= 0:
        return {}
    if val >= 1:
        return {produces: rate / val}
    return {produces: rate * 0.1}


# Effekt-Suffixe der PerTick-Klasse (buildings.js-Namenskonvention), längste
# zuerst — Werte sind PRO EINHEIT und PRO TICK (×TPS für Einheiten/s);
# Con-Werte sind im Spiel bereits negativ (z. B. Mint goldPerTickCon −0.005).
_PER_TICK_SUFFIXES = ("PerTickAutoprod", "PerTickProd", "PerTickCon",
                      "PerTickBase", "PerTick")
# Effekte, die hier bewusst NICHT als ΔRate zählen (Doppelzählung/eigene
# Bewertungspfade — Begründungen in _rate_delta_from_effects):
_RATE_DELTA_SKIP = frozenset({
    "energyConsumption", "energyProduction",       # Energie-Regel 16.4
    "cathPollutionPerTickProd", "cathPollutionPerTickCon",  # Pollution-Term
    "tradeRatio", "standingRatio",   # bereits in der Trade-EV 14.1 bewertet
                                     # (diplomacy.tradeRatio/standingRatio)
    "festivalRatio", "festivalArrivalRatio",        # Festival separat (15.x)
    "unhappinessRatio", "maxKittensRatio", "magnetoBoostRatio",
})


def _rate_delta_from_effects(snap, b: dict) -> dict[str, float]:
    """Übersetzt das Effekt-Dict eines Gebäudes (pro Einheit, buildings.js)
    in ΔRate je Ressource in Einheiten/s (#35, Spec 13.1/13.2).

    Mapping (dokumentierte Näherungen):
    - <res>PerTickProd/Con/Base/Autoprod/PerTick → ×TPS direkt;
      catnipPerTickBase zusätzlich × currentCatnipModifier (das Spiel
      skaliert die Feld-Basisrate mit der Saison, calendar.js).
    - <res>DemandRatio (negativ) → (−v) × Bedarf: Catnip-Bedarf aus
      derived.food.demandPerSec (Pasture buildings.js catnipDemandRatio
      −0.005), sonst beobachteter Nettoverbrauch als Bedarfsproxy.
    - <res>Ratio generisch → v × max(0, beobachtete Rate): Ratio wirkt im
      Spiel auf die BASIS-Produktion, beobachtet wird die Netto-Rate —
      konservative Näherung (LumberMill woodRatio 0.1).
    - coalRatioGlobal → NUR beim ersten Exemplar (on == 0): das Spiel
      staffelt diesen Effekt nicht mit der Gebäudezahl (buildings.js
      getEffect: `if (effectName == "coalRatioGlobal") effect = effectValue`).
    - magnetoRatio → globaler Produktionsboost: v × Rate über alle nicht
      craftbaren Ressourcen mit positiver Rate (Breitband-Näherung an
      game.js getAutoProductionRatio).
    - happiness (Prozentpunkte, village.js updateHappines:
      `happiness += getEffect("happiness")`) → (v/100) × dieselbe
      Globalschleife (Produktion ~linear in Happiness, Näherung).
    - craftRatio → v × Rate über craftbare Ressourcen mit positiver Rate
      (nur der beobachtbare Autocraft-Durchsatz; der Nutzen für MANUELLE
      Crafts bleibt dokumentiert unbewertet).
    - <res>Max → skip: Storage bewertet die Storage-Regel 11.3
      (_storage_eval liest b["effects"] direkt).
    - Skip-Liste _RATE_DELTA_SKIP: Energie (16.4), Pollution (eigener
      Zeitkostenterm), Trade/Standing (Trade-EV 14.1), Festival (15.x)."""
    effects = b.get("effects") or {}
    tps = snap.get("meta", {}).get("ticksPerSecond", 5)
    dr: dict[str, float] = {}

    def _add(res: str, delta: float) -> None:
        if abs(delta) > 1e-12 and A.resource(snap, res) is not None:
            dr[res] = dr.get(res, 0.0) + delta

    def _global_production(factor: float, craftable: bool) -> None:
        for r in snap.get("resources", []):
            if bool(r.get("craftable")) != craftable:
                continue
            rate = r.get("perSec", 0.0)
            if rate > 0:
                _add(r["name"], factor * rate)

    mod = snap.get("calendar", {}).get("currentCatnipModifier", 1.0) or 1.0
    for key in sorted(effects):
        v = effects[key]
        if not isinstance(v, (int, float)) or v == 0 or key in _RATE_DELTA_SKIP:
            continue
        if key.endswith("Max"):
            continue                      # Storage → Regel 11.3
        matched = False
        for suffix in _PER_TICK_SUFFIXES:
            if key.endswith(suffix):
                res = key[: -len(suffix)]
                season = mod if key == "catnipPerTickBase" else 1.0
                _add(res, v * tps * season)
                matched = True
                break
        if matched:
            continue
        if key.endswith("DemandRatio"):
            res = key[: -len("DemandRatio")]
            if res == "catnip":
                demand = snap.get("derived", {}).get("food", {}).get("demandPerSec", 0.0)
            else:
                demand = max(0.0, -A.res_rate(snap, res))
            _add(res, -v * demand)        # v ist negativ → Ersparnis positiv
            continue
        if key == "coalRatioGlobal":
            if b.get("on", 0) == 0:
                _add("coal", v * max(0.0, A.res_rate(snap, "coal")))
            continue
        if key == "magnetoRatio":
            _global_production(v, craftable=False)
            continue
        if key == "happiness":
            _global_production(v / 100.0, craftable=False)
            continue
        if key == "craftRatio":
            _global_production(v, craftable=True)
            continue
        if key.endswith("Ratio"):
            res = key[: -len("Ratio")]
            _add(res, v * max(0.0, A.res_rate(snap, res)))
            continue
    return {res: val for res, val in dr.items() if abs(val) > 1e-12}


# --------------------------------------------------------- Pollution (#35)

# Pollution-Wirkung auf Kitten-Ankünfte (buildings.js
# calculatePollutionEffects, Level-2-Regime — dort beginnt der Slowdown):
#   pollutionArrivalSlowdown = 1 + 1.68e-8 · (cathPollution − POL_LBASE·100/2)
# mit POL_LBASE = getPollutionLevelBase() = 1e7 → Schwelle 5e8. Höhere
# Level (3/4) sind log10-basiert und steiler — die lineare Steigung ist
# also eine KONSERVATIVE Untergrenze. village.js teilt kittensPerTick
# durch den Slowdown (> 1).
POLLUTION_SLOWDOWN_SLOPE = 1.68e-8
POLLUTION_THRESHOLD = 1e7 * 100 / 2       # = 5e8


def _pollution_cost_time(snap, effects: dict, horizon: float,
                         lam_rate: dict | None) -> float:
    """Zeitkosten der Pollution eines Gebäudekaufs in Ziel-Sekunden (#35).

    Linearisierung um den aktuellen Zustand: das neue Exemplar emittiert
    p = cathPollutionPerTickProd × TPS Pollution/s; oberhalb der Schwelle
    wächst der Arrival-Slowdown linear (Steigung s. o.), die relative
    Ankunftsrate sinkt ≈ um ΔSlowdown. Verlorene Ankünfte über den
    Horizont: kps · slope · p · H²/2 (Pollution akkumuliert linear).
    Wert je verlorenem Kitten: bester Job-Grenzwert × H (wie
    _housing_eval). Ehrlich 0, wenn: Pollution unter der Schwelle (im
    Spiel wirkungslos auf Ankünfte), keine pollution-Sektion im Snapshot,
    keine Ankunftsrate oder keine λ-Daten."""
    p_tick = effects.get("cathPollutionPerTickProd", 0.0)
    if not p_tick or not lam_rate or not horizon:
        return 0.0
    pollution = snap.get("pollution", {}).get("cathPollution", 0.0)
    if pollution < POLLUTION_THRESHOLD:
        return 0.0
    kps = float(snap.get("village", {}).get("kittensPerSec", 0.0) or 0.0)
    if kps <= 0:
        return 0.0
    tps = snap.get("meta", {}).get("ticksPerSecond", 5)
    best_js = max((shadow.job_score(snap, j, lam_rate) for j in JOB_ORDER
                   if A.job_unlocked(snap, j)), default=0.0)
    if best_js <= 0:
        return 0.0
    lost_kittens = kps * POLLUTION_SLOWDOWN_SLOPE * (p_tick * tps) * horizon ** 2 / 2.0
    return lost_kittens * best_js * horizon


def _apply_food_risk(snap, comp: dict, prices: list[dict]) -> None:
    """foodRisk-Komponente (I-01): Bei kritischer Winter-Projektion drückt
    ein Catnip-Preis den Kandidaten unter Null (Kaufregel 10.3 filtert ihn)."""
    if snap.get("derived", {}).get("food", {}).get("status") != "critical":
        return
    if any(p["name"] == "catnip" for p in prices):
        comp["foodRisk"] = -3.0


# Housing-Kapazitätszuwachs pro Gebäude (Spec 12.1 KittenArrival-Basis):
HOUSING_CAPACITY = {"hut": 2, "logHouse": 1, "mansion": 1}


def _housing_eval(snap, name: str, b: dict, blocked,
                  lam=None, lam_rate=None, horizon=None) -> tuple[dict, str | None]:
    """HousingValue-Logik nach Spec 12.1 (deterministisch vereinfacht).

    Liefert (Score-Komponenten, Ablehnungsgrund|None). Regeln:
    1. Bedarfs-Gate: nur bauen, wenn die Kapazität voll ist — ungenutzte
       Plätze haben keinen Produktionswert (12.1). maxKittens == 0 gilt
       als voll → die erste Hütte entsteht dynamisch ohne Meilenstein.
    2. Food-Gate: die Saisonprojektion muss die MEHRLAST der neuen Kitten
       tragen (ersetzt die frühere Pauschalsperre).
    3. Score: Basis 1.6 (Kitten = Arbeiter am Engpass) + 0.4 Paragon-
       Grenzwert ab 68 Kitten + dynamischer KittenValue (12.1): der beste
       verfügbare Job-Grenzwert × Horizont als benefitTime/netValue —
       neue Kitten sind Arbeiter, ihr Wert steht damit im Score.
    """
    village = snap.get("village", {})
    kittens = village.get("kittens", 0)
    max_kittens = village.get("maxKittens", 0)
    comp: dict[str, float] = {"housing": 1.6}
    if kittens >= 68:
        comp["paragon"] = 0.4
    # KittenValue (12.1): ExpectedKittenArrivals × Produktionswert des
    # besten Jobs − Zeitkosten des Kaufs, alles in Ziel-Sekunden.
    if lam_rate and horizon:
        best_js = max((shadow.job_score(snap, j, lam_rate) for j in JOB_ORDER
                       if A.job_unlocked(snap, j)), default=0.0)
        if best_js > 0:
            capacity = HOUSING_CAPACITY.get(name, 1)
            arrival = float(village.get("kittensPerSec", 0.0) or 0.0)
            if arrival > 1e-9:
                # Echte ExpectedKittenArrivals (#41): die Slots füllen sich
                # SEQUENZIELL mit der Ankunftsrate (village.js sim.update:
                # nextKittenProgress += kittensPerTick, ein Spawn je
                # Überlauf) — Slot i arbeitet nur die Restzeit H − i/Rate.
                work_s = sum(max(0.0, horizon - i / arrival)
                             for i in range(1, capacity + 1))
            else:
                # Fallback ohne Snapshot-Rate: Sofort-Vollbelegung
                # (Bestandsverhalten, bewusst optimistisch).
                work_s = capacity * horizon
            comp["benefitTime"] = best_js * work_s
            comp["costTime"] = shadow.cost_time(b["prices"], lam or {})
            comp["netValue"] = shadow.net_value(comp["benefitTime"],
                                                comp["costTime"])

    # 1. Bedarfs-Gate
    if max_kittens > kittens:
        return comp, (f"ungenutzte Housing-Kapazität ({kittens}/{max_kittens}) — "
                      f"neue Plätze haben keinen Wert (12.1)")

    # 2. Food-Gate über die Saisonprojektion. Bewusst konservativ trotz
    # bekannter Ankunftsrate (#41): die Sicherheitsinvariante I-01 rechnet
    # worst-case (Kapazität sofort voll), nicht erwartungstreu.
    food = snap.get("derived", {}).get("food", {})
    if "housing" in blocked:
        return comp, "Food-Warnstufe blockiert Housing (I-01)"
    capacity_add = HOUSING_CAPACITY.get(name, 1)
    demand = food.get("demandPerSec", 0.0)
    per_kitten = (demand / kittens) if kittens > 0 else CATNIP_PER_KITTEN_PER_SEC
    price_catnip = sum(p["val"] for p in b["prices"] if p["name"] == "catnip")
    after = project_catnip(snap, stock_delta=-price_catnip,
                           demand_delta=capacity_add * per_kitten)
    warn_floor_after = max(150.0, 120.0 * (demand + capacity_add * per_kitten))
    if after["projectedMin"] < warn_floor_after:
        return comp, (f"{capacity_add} neue Kitten würden den Winter kippen "
                      f"(Projektion {after['projectedMin']:.0f} < {warn_floor_after:.0f})")

    return comp, None


def _storage_relieves(snap, storage_name, cap_blocked_res) -> bool:
    if not cap_blocked_res:
        return False
    relief_map = {
        "barn": {"catnip", "wood", "minerals", "iron"},
        "warehouse": {"wood", "minerals", "iron"},
        "harbor": {"catnip", "wood", "minerals", "iron", "coal", "gold"},
    }
    return cap_blocked_res in relief_map.get(storage_name, set())


# Cap-Zuwachs je Storage-Gebäude — REFERENZWERTE Kittens Game 1.5.0.2
# (buildings.js effects "…Max"). Seit #35 exportiert snapshot.js das
# `effects`-Dict pro Gebäude — die echten "…Max"-Einträge haben Vorrang,
# die Tabelle bleibt Fallback für Alt-Fixtures
# (_storage_cap_gains liest zuerst den Snapshot).
STORAGE_CAP_GAINS: dict[str, dict[str, float]] = {
    "barn": {"catnip": 5000, "wood": 200, "minerals": 250, "iron": 50},
    "warehouse": {"wood": 150, "minerals": 200, "iron": 25, "coal": 30,
                  "gold": 5, "titanium": 10},
    "harbor": {"catnip": 2500, "wood": 700, "minerals": 950, "iron": 150,
               "coal": 100, "gold": 25, "titanium": 50},
}
# Offline-/Batch-Puffer (11.3 C): ein Entscheidungs-/Snapshot-Intervall,
# gleicher Referenzpuffer wie HUNT_CAP_BUFFER_S / PRAISE_CAP_BUFFER_S.
STORAGE_CAP_BUFFER_S = 60.0


def _storage_cap_gains(b: dict) -> dict[str, float]:
    """Cap-Zuwachs des nächsten Exemplars je Ressource. Bevorzugt echte
    Snapshot-Effekte ("…Max"-Einträge), sonst die Referenztabelle."""
    effects = b.get("effects") or {}
    gains = {k[:-3]: float(v) for k, v in effects.items()
             if k.endswith("Max") and isinstance(v, (int, float)) and v > 0}
    if gains:
        return gains
    return STORAGE_CAP_GAINS.get(b["name"], {})


def _storage_carryover_value(snap, gains: dict[str, float],
                             lam: dict[str, float]) -> float:
    """Bedingung 11.3 B: zusätzlicher Carryover-Wert in Ziel-Sekunden.

    Nur mit Chronospheres (sonst existiert kein Carryover): der Cap-Zuwachs
    der gelagerten Ressourcen × Carryover-Anteil (k × 1,5 % je Chronosphere,
    Referenzwert wie chrono.CARRYOVER_PER_CS) × λ. Zählt nur Ressourcen,
    die im Snapshot existieren — ein Cap für nie Gelagertes trägt nichts."""
    cs = A.bld_val(snap, "chronosphere")
    if cs <= 0 or not lam:
        return 0.0
    frac = cs * chrono.CARRYOVER_PER_CS
    total = 0.0
    for res in sorted(gains):
        if A.resource(snap, res) is None:
            continue
        total += gains[res] * frac * lam.get(res, 0.0)
    return total


def _storage_overflow_value(snap, gains: dict[str, float], lam: dict[str, float],
                            horizon: float) -> float:
    """Bedingung 11.3 C: bewerteter Cap-Verlust in Ziel-Sekunden.

    Läuft eine Ressource mit λ > 0 innerhalb des Puffers (60 s, wie beim
    Hunt-/Praise-Cap-Timing) über ihr Cap, verfällt ab dann die Produktion:
    Verlust = Überlaufrate × λ × Horizont-Anteil nach dem Cap-Zeitpunkt.
    Storage verhindert das nur für Ressourcen, deren Cap es anhebt."""
    total = 0.0
    for res in sorted(gains):
        lam_i = lam.get(res, 0.0)
        if lam_i <= 0.0:
            continue
        r = A.resource(snap, res)
        if not r or r.get("maxValue", 0) <= 0:
            continue
        rate = r.get("perSec", 0.0)
        if rate <= A.RATE_EPS:
            continue
        cap_time = (r["maxValue"] - r["value"]) / rate
        if cap_time >= STORAGE_CAP_BUFFER_S:
            continue
        total += lam_i * rate * max(0.0, horizon - cap_time)
    return total


def _storage_challenge_requires(snap, gains: dict[str, float]) -> bool:
    """Bedingung 11.3 D: eine Challenge-/Cryo-Bedingung verlangt das Cap.

    Der Snapshot liefert derzeit KEINE Challenge-Sektion — das Gate ist
    dokumentiert inaktiv (kein Fake) und greift automatisch, sobald ein
    Snapshot `challenges.activeRequiresCap` (Liste von Ressourcennamen,
    deren Cap gebraucht wird) mitbringt."""
    required = snap.get("challenges", {}).get("activeRequiresCap") or []
    return any(res in gains for res in required)


def _storage_eval(snap, name: str, b: dict, bn, cap_blocked_res,
                  lam, horizon) -> tuple[dict, str | None]:
    """Storage-Zulässigkeit nach Spec 11.3: (Komponenten, Ablehnungsgrund|None).

    Reihenfolge deterministisch A → D → B → C → Nähe-Cap-Heuristik; die
    erste erfüllte Bedingung bestimmt die Komponenten. B/C tragen ihren
    Sekunden-Nettowert als Anzeige-Komponente (storageB/storageC)."""
    comp: dict[str, float] = {}
    # A: Cap blockiert das Meilenstein-Ziel.
    if _storage_relieves(snap, name, cap_blocked_res):
        comp["storage"] = 2.2
        return comp, None
    gains = _storage_cap_gains(b)
    # D: Challenge-/Cryo-Bedingung verlangt das Cap (harte Anforderung).
    if _storage_challenge_requires(snap, gains):
        comp["storage"] = 2.2
        return comp, None
    if lam:
        cost_t = shadow.cost_time(b["prices"], lam)
        # B: zusätzlicher Carryover-Wert übersteigt die Baukosten.
        carry = _storage_carryover_value(snap, gains, lam)
        if carry > cost_t and carry > 1e-9:
            comp["storage"] = 1.0
            comp["storageB"] = carry - cost_t   # Sekundenwert, nur Anzeige
            return comp, None
        # C: verhinderter Cap-Verlust übersteigt die Baukosten.
        overflow = _storage_overflow_value(snap, gains, lam, horizon)
        if overflow > cost_t and overflow > 1e-9:
            comp["storage"] = 1.0
            comp["storageC"] = overflow - cost_t   # Sekundenwert, nur Anzeige
            return comp, None
    # Bestandsheuristik (Teil von A, „Engpass > 90 % voll"):
    if _bottleneck_near_cap(snap, bn):
        comp["storage"] = 1.0
        return comp, None
    return {}, ("keine Storage-Bedingung erfüllt (11.3 A–D): kein Cap blockiert "
                "das Ziel (A), Carryover-Gewinn unter Baukosten (B), kein "
                "bewerteter Cap-Verlust im Puffer (C), keine Challenge "
                "verlangt das Cap (D)")


def _bottleneck_near_cap(snap, bn) -> bool:
    if not bn or not bn.get("resource"):
        return False
    r = A.resource(snap, bn["resource"])
    if not r or not r.get("maxValue"):
        return False
    return r["value"] / r["maxValue"] > 0.9


# ---------------------------------------------------------------- Energie (16.4)

# Lebenswichtige Gebäude (Housing/Food) werden NIE gedrosselt (16.4 Schritt 3:
# „bis harte Anforderungen erfüllt sind" — Housing/Food SIND harte Anforderungen):
ENERGY_VITAL_BUILDINGS = HOUSING_BUILDINGS | {"field", "pasture", "aqueduct"}
# Anti-Flattern (Hysterese): Wieder anschalten erst, wenn der Überschuss den
# Verbrauch der Einheit um diese Marge übersteigt — sonst würde derselbe
# Verbraucher im nächsten Zyklus sofort wieder abgeschaltet.
ENERGY_REACTIVATE_MARGIN = 1.0


def _energy_unit_value(snap, b: dict, lam, horizon: float) -> float:
    """λ-bewerteter Produktionsbeitrag EINER aktiven Einheit in Ziel-Sekunden
    (16.4 Schritt 2: marginale Output-Einbuße beim Abschalten)."""
    if not lam:
        return 0.0
    return shadow.benefit_time(_building_rate_delta(snap, b), lam, horizon)


def _energy_candidates(snap, cands, lam, horizon) -> None:
    """Energie-Drosselung nach Spec 16.4 (Schritte 2, 3 und 5).

    Defizit: unter den aktiven, nicht lebenswichtigen Verbrauchern
    (on > 0, energyConsumption > 0) den mit dem KLEINSTEN Zielbeitrag pro
    Energieeinheit abschalten. Überschuss: abgeschaltete Einheiten (on < val)
    in absteigender Grenznutzen-Reihenfolge reaktivieren — aber nur mit
    Hysterese (Überschuss > Einheitsverbrauch + Marge, Anti-Flattern).
    Fallbacks: ohne Energie-Felder im Snapshot oder (beim Abschalten) ohne
    λ-Daten entsteht kein Kandidat — Altverhalten (nur Erzeuger-Vorrang)."""
    balance = snap.get("derived", {}).get("energy", {}).get("balance", 0)
    consumers = [b for b in snap.get("buildings", [])
                 if (b.get("energyConsumption") or 0) > 0
                 and b["name"] not in ENERGY_VITAL_BUILDINGS]
    if balance < 0:
        if not lam:
            return   # keine λ-Daten → kein Zielbeitrag bestimmbar (Fallback)
        active = [b for b in consumers if b.get("on", 0) > 0]
        if not active:
            return
        # Kleinster Zielbeitrag je Energieeinheit zuerst; Tie-Break Name:
        b = min(active, key=lambda x: (
            _energy_unit_value(snap, x, lam, horizon)
            / x["energyConsumption"], x["name"]))
        comp = {"energyRelief": 1.5}
        cands.append(Candidate(
            actions.toggle_building(b["name"], b["label"], on=False),
            _score(comp), comp))
        return
    # Reaktivierung nur bei echtem Überschuss inkl. Hysterese-Marge:
    reactivatable = [b for b in consumers
                     if b.get("on", 0) < b.get("val", 0)
                     and balance > b["energyConsumption"] + ENERGY_REACTIVATE_MARGIN]
    if not reactivatable:
        return
    # Größter Zielbeitrag zuerst (Grenznutzen-Reihenfolge, 16.4 Schritt 5);
    # ohne λ-Daten sind alle Beiträge 0 → deterministisch nach Name.
    b = min(reactivatable, key=lambda x: (
        -_energy_unit_value(snap, x, lam, horizon), x["name"]))
    comp = {"energyRelief": 1.0}
    cands.append(Candidate(
        actions.toggle_building(b["name"], b["label"], on=True),
        _score(comp), comp))


# ---------------------------------------------------------------- Leader (12.3)

# Leader-Trait-Effekte — REFERENZWERTE Kittens Game 1.5.0.2 (village.js
# Traits + deren Verbraucher in workshop/science/religion/diplomacy).
# Gekennzeichnete Konstanten: der Snapshot liefert keine Trait-Effektdaten.
#   manager      +50 %  Jagd-Ertrag
#   merchant     +3 %   Handelsertrag
#   engineer     +5 %   Craft-Ausbeute (alle Rezepte)
#   scientist    −5 %   Science-Preise (Forschung)
#   wise         −10 %  Religion-Preise (Faith/Gold)
#   chemist      +7,5 % Craft-Ausbeute Chemie (Kerosene/Eludium)
#   metallurgist +10 %  Craft-Ausbeute Metall (Plate/Steel/Gear/Alloy)
#   none         kein Effekt
LEADER_TRAIT_BONUS: dict[str, float] = {
    "manager": 0.5, "merchant": 0.03, "engineer": 0.05, "scientist": 0.05,
    "wise": 0.1, "chemist": 0.075, "metallurgist": 0.1,
}
LEADER_TRAIT_RESOURCES: dict[str, tuple[str, ...]] = {
    "manager": ("furs", "ivory", "unicorns"),
    "scientist": ("science",),
    "wise": ("faith", "gold"),
    "chemist": ("kerosene", "eludium"),
    "metallurgist": ("plate", "steel", "gear", "alloy"),
}
# Wechselschwelle in Ziel-Sekunden: der Wechselgewinn muss die Wechsel- und
# Interaktionskosten bis zum nächsten Replanning übersteigen (Spec 12.3);
# zwei Entscheidungsintervalle als Anti-Flattern-Marge.
LEADER_SWITCH_MIN_S = 120.0


def _leader_trait_resources(snap, trait: str | None) -> tuple[str, ...]:
    """Adressierte Ressourcen eines Traits; engineer/merchant dynamisch aus
    dem Snapshot (alle Craft-Produkte bzw. alle Trade-Angebote)."""
    if trait == "engineer":
        return tuple(sorted(c["name"] for c in
                            snap.get("workshop", {}).get("crafts", [])))
    if trait == "merchant":
        return tuple(sorted({s["name"] for r in A.races(snap)
                             for s in r.get("sells", [])}))
    return LEADER_TRAIT_RESOURCES.get(trait or "", ())


def _leader_trait_value(snap, trait: str | None, lam, goal_prices,
                        horizon: float) -> float:
    """Prognostizierte Zielzeitverkürzung eines Traits in Sekunden (12.3).

    Heuristik: Bonus × λ-bewertete Menge der adressierten Ressourcen.
    Menge = fehlende Zielmenge (steht die Ressource im aktiven Preisvektor —
    Rabatte/Boni wirken auf die teuerste laufende Aktivität), sonst die
    laufende Produktion über den Horizont. Ohne λ-Daten: 0."""
    bonus = LEADER_TRAIT_BONUS.get(trait or "", 0.0)
    if bonus <= 0.0 or not lam:
        return 0.0
    total = 0.0
    for res in _leader_trait_resources(snap, trait):
        lam_i = lam.get(res, 0.0)
        if lam_i <= 0.0:
            continue
        need = next((max(0.0, p["val"] - A.res_value(snap, res))
                     for p in (goal_prices or []) if p["name"] == res), None)
        amount = (need if need is not None
                  else max(0.0, A.res_rate(snap, res)) * horizon)
        total += bonus * lam_i * amount
    return total


def _leader_candidate(snap, cands, lam, goal_prices, horizon) -> None:
    """Leader-Wahl (Spec 12.3): Trait mit der größten Zielzeitverkürzung.

    Kandidat nur, wenn (a) kein Leader gesetzt ist (Erstwahl) oder (b) der
    Wechselgewinn die Schwelle LEADER_SWITCH_MIN_S übersteigt. Ohne
    Census-Daten im Snapshot: kein Kandidat (Fallback = Altverhalten)."""
    village = snap.get("village", {})
    census = village.get("census") or []
    if not census:
        return
    scored = [(_leader_trait_value(snap, k.get("trait"), lam, goal_prices,
                                   horizon), k) for k in census]
    # Deterministisch: größter Wert, dann echte Traits vor "none", dann Index.
    scored.sort(key=lambda t: (
        -t[0], 0 if (t[1].get("trait") or "none") != "none" else 1,
        t[1].get("index", 0)))
    best_val, best = scored[0]
    leader = village.get("leader")
    comp: dict[str, float] = {"leader": 1.2}
    if leader:
        if best.get("isLeader"):
            return   # der beste Kandidat führt bereits
        gain = best_val - _leader_trait_value(snap, leader.get("trait"), lam,
                                              goal_prices, horizon)
        if gain <= LEADER_SWITCH_MIN_S:
            return   # Wechsel lohnt die Interaktionskosten nicht (12.3)
        comp["leaderValue"] = gain          # Sekundenwert, nur Anzeige
    elif best_val > 0:
        comp["leaderValue"] = best_val      # Sekundenwert, nur Anzeige
    trait = best.get("trait") or "none"
    label = f"{best.get('name') or 'Kitten'} ({trait})"
    cands.append(Candidate(
        actions.set_leader(best.get("index", 0), label), _score(comp), comp))


# ---------------------------------------------------------------- Upgrades

def _upgrade_candidates(snap, cands, lam=None, lam_rate=None) -> None:
    ups = [u for u in snap.get("workshop", {}).get("upgrades", [])
           if u["unlocked"] and not u["researched"] and A.affordable(snap, u["prices"])]
    ups.sort(key=lambda u: (sum(p["val"] for p in u["prices"]), u["name"]))
    for u in ups[:2]:
        comp = {"unlock": 1.4}
        # Sekundenkosten nur als Transparenz — Unlocks unterliegen nicht der
        # Payback-Regel (Spec 10.4):
        ct = shadow.cost_time(u["prices"], lam) if lam else 0.0
        if ct > 1e-9:
            comp["costTime"] = ct
        # Optionswert (8.4) für die Referenz-Upgrades: ΔRate = Ratio ×
        # Jobbesetzung × Basisrate (UPGRADE_OPTION_JOB_RATIO, workshop.js).
        job_ratio = UPGRADE_OPTION_JOB_RATIO.get(u["name"])
        if job_ratio is not None:
            job, res, ratio = job_ratio
            base = shadow.JOB_BASE_RATES.get(job, {}).get(res, 0.0)
            ov = _option_value(lam_rate,
                               {res: ratio * A.job_count(snap, job) * base})
            if ov > 1e-9:
                comp["optionValue"] = ov
        cands.append(Candidate(actions.buy_upgrade(u["name"], u["label"], prices=u["prices"]),
                               _score(comp), comp))


# ---------------------------------------------------------------- Policies (13.4)

def _policy_candidates(snap, run_type, cands, lam, horizon) -> None:
    """Policy-Kandidat (Spec 13.4 + I-07): höchstens EINE Policy pro Zyklus
    (Chargenregel 10.5 — Policies sind irreversibel, keine Batches).

    Kandidat wird nur die aktuell beste unblockierte, bezahlbare Policy mit
    positivem PolicyValue, die die I-07-Prüfung besteht (PolicyValue ≥ Wert
    jeder ausgeschlossenen Alternative über den Restplan-Horizont — die
    Auswahl inkl. 13.4-Prior liegt in brain/policy.py). Ohne policies-Daten
    im Snapshot oder ohne λ-Daten entsteht kein Kandidat (Fallback)."""
    best = policy.best_policy(snap, run_type, lam, horizon)
    if best is None:
        return
    pol, value, alt_values = best
    alt_txt = ", ".join(f"{n}: {v:.0f}s" for n, v in sorted(alt_values.items()))
    act = actions.select_policy(pol["name"], pol.get("label") or pol["name"],
                                prices=pol.get("prices"))
    if alt_txt:
        act.expected += f" — Alternativen bewertet: {alt_txt}"
    comp = {"policy": 1.5, "policyValue": value}   # policyValue: s-Wert, Anzeige
    cands.append(Candidate(act, _score(comp), comp))


# ---------------------------------------------------------------- Jagd

# Jagd-Ergebnisverteilung (Spec 14.2) — Referenzwerte Kittens Game 1.5.0.2,
# village.js sendHuntersInternal, je 100 Catpower („Squad", ohne huntRatio-
# Bonus aus Upgrades — der fehlt im Snapshot, konservativ Faktor 1.0):
#   Furs:     immer, Menge rand(80) + 40          → E = 79.5
#   Ivory:    P = 0.45 (rand(100) < 45), rand(50) + 25 → E = 49.5
#   Unicorns: P = 0.005 (rand(1000) < 5), Menge 1
HUNT_MANPOWER_COST = 100
HUNT_FURS_EV = 79.5
HUNT_IVORY_CHANCE = 0.45
HUNT_IVORY_EV = 49.5
HUNT_UNICORN_CHANCE = 0.005
# EV-Timing (14.2): Cap-Puffer ≈ ein Entscheidungsintervall — droht Cap-
# Verlust vorher, ist JETZT jagen besser als auf den größeren Batch warten.
HUNT_CAP_BUFFER_S = 60.0
# Batch-Vorteil des Wartens ≈ eine gesparte Aktion; erst wenn die λ-bewertete
# Beute mehr Ziel-Sekunden bringt, lohnt die sofortige Jagd (Skala wie netValue).
HUNT_VALUE_MIN_S = NET_VALUE_SCALE
# Fallback-Schwelle ohne λ-Daten (Bestandsverhalten): jagen ab 85 % Füllstand.
HUNT_FILL_FALLBACK = 0.85


def _hunt_action(squads: int) -> "actions.Action":
    """Jagd-Aktion mit stochastischer EV-Prognose (G-10: nur Vorzeichen-/
    Größenordnungscheck; Unicorns bewusst nicht prognostiziert, P=0,5 %)."""
    act = actions.hunt()
    if squads >= 1:
        act.predicted = {"deltas": {
            "manpower": -float(squads * HUNT_MANPOWER_COST),
            "furs": squads * HUNT_FURS_EV,
        }, "stochastic": True}
    return act


def _hunt_expected_yield(squads: int, lam: dict[str, float]) -> float:
    """λ-bewerteter Erwartungswert der Jagdbeute in Ziel-Sekunden (14.2)."""
    per_squad = (lam.get("furs", 0.0) * HUNT_FURS_EV
                 + lam.get("ivory", 0.0) * HUNT_IVORY_CHANCE * HUNT_IVORY_EV
                 + lam.get("unicorns", 0.0) * HUNT_UNICORN_CHANCE)
    return squads * per_squad


def _hunt_candidate(snap, cands, lam=None) -> None:
    mp = A.resource(snap, "manpower")
    if not mp or not A.job_unlocked(snap, "hunter") and A.job_count(snap, "hunter") == 0:
        # Jagd lohnt erst mit Catpower-Produktion
        if not mp or mp["value"] < HUNT_MANPOWER_COST:
            return
    if mp.get("maxValue", 0) <= 0:
        return
    fill = mp["value"] / mp["maxValue"]
    cap_pressure = fill >= HUNT_FILL_FALLBACK and mp["value"] >= HUNT_MANPOWER_COST

    if lam and mp["value"] >= HUNT_MANPOWER_COST:
        # EV-Regel (Spec 14.2): Jagd = Trade mit bekannter Verteilung.
        squads = int(mp["value"] // HUNT_MANPOWER_COST)
        hunt_value = _hunt_expected_yield(squads, lam)
        rate = mp.get("perSec", 0.0)
        cap_time = ((mp["maxValue"] - mp["value"]) / rate
                    if rate > A.RATE_EPS else math.inf)
        if cap_pressure or cap_time < HUNT_CAP_BUFFER_S:
            # Cap-Verlust droht: Warten verschenkt Catpower — sofort jagen.
            comp = {"capLoss": 1.5}
            if hunt_value > 1e-9:
                comp["huntValue"] = hunt_value   # Sekundenwert, nur Anzeige
            if A.res_value(snap, "furs") <= 0:
                comp["economy"] = 0.3   # erster Pelz = Happiness-Schub
            cands.append(Candidate(_hunt_action(squads), _score(comp), comp))
        elif hunt_value > HUNT_VALUE_MIN_S:
            # Beute ist dem Ziel JETZT mehr wert als der Batch-Vorteil des
            # Wartens (EV(sofort) > EV(warten), Spec 14.2).
            comp = {"economy": 1.3, "huntValue": hunt_value}
            cands.append(Candidate(_hunt_action(squads), _score(comp), comp))
        return

    # Fallback ohne λ-Daten (Bestandsverhalten): 85-%-Schwelle.
    if cap_pressure:
        comp = {"capLoss": 1.5}
        if A.res_value(snap, "furs") <= 0:
            comp["economy"] = 0.3   # erster Pelz = Happiness-Schub
        cands.append(Candidate(_hunt_action(int(mp["value"] // HUNT_MANPOWER_COST)),
                               sum(comp.values()), comp))


# ---------------------------------------------------------------- Crafts

def _craft_ratio(snap) -> float:
    """Craft-Ausbeute-Bonus aus dem Snapshot (Fallback 0 = Basisausbeute)."""
    return float(snap.get("workshop", {}).get("craftRatio", 0.0) or 0.0)


# Cap-Management (Spec 11.4): einheitliches Basisgewicht der Optionen
# „werterhaltender Craft" / „profitabler Trade" bei drohendem Cap-Verlust —
# die AUSWAHL zwischen den Optionen trifft der netValue-Sekundenwert in
# _score (NetValue bestätigt die Reihenfolge, keine blinde Prioritätsliste);
# die alten Füllstands-Schwellen (0.92 Craft, 0.95 Trade) bleiben reine
# TRIGGER-Vorfilter. NetValue ≤ 0 heißt: „akzeptierter Verlust" ist die
# beste Option — der Kandidat wird als infeasible dokumentiert. Ohne
# λ-Daten bleibt das alte Verhalten (feste Scores 1.6/1.1).
CAP_OPTION_BASE = 1.5
CAP_ACCEPTED_LOSS = ("akzeptierter Verlust ist die beste Option (11.4): "
                     "NetValue {nv:.1f} s ≤ 0 — kein werterhaltender Abfluss "
                     "mit positivem Zielwert")


def _craft_candidates(snap, target, bn, cands, lam=None) -> None:
    prices_target = _target_prices(snap, target) or []

    # a) Kaskadierendes Crafting Richtung Meilenstein (Craft-Graph 11.2 light):
    #    Braucht das Ziel z. B. Blueprints, deren Inputs (Compendia) fehlen,
    #    steigt die Kaskade rekursiv ab: Parchment → Manuscript → Compendium
    #    → Blueprint. Pro Zyklus entsteht der jeweils tiefste machbare Craft.
    seen: set[str] = set()
    for p in prices_target:
        if A.craft_recipe(snap, p["name"]) is not None:
            gap = p["val"] - A.res_value(snap, p["name"])
            if gap > 0:
                _craft_toward(snap, p["name"], gap, cands, depth=0, seen=seen,
                              lam=lam, goal_prices=prices_target)

    # b) Cap-Verlust am Input vermeiden (11.4) — Trigger-Vorfilter 0.92,
    #    Auswahl per NetValue (siehe CAP_OPTION_BASE):
    goal_res = {p["name"] for p in prices_target}
    for input_res, craft_name in CAP_RELIEF_CRAFTS.items():
        recipe = A.craft_recipe(snap, craft_name)
        if not recipe:
            continue
        r = A.resource(snap, input_res)
        if not r or r.get("maxValue", 0) <= 0:
            continue
        price = next((q["val"] for q in recipe["prices"] if q["name"] == input_res), None)
        if not price:
            continue
        if r["value"] / r["maxValue"] > 0.92 and r["value"] >= price \
                and craft_name not in seen:
            batch = max(1, min(10, int((r["value"] * 0.3) // price)))
            act = actions.craft(craft_name, recipe["label"], batch,
                                prices=recipe["prices"],
                                craft_ratio=_craft_ratio(snap))
            if lam:
                # NetValue des werterhaltenden Crafts: λ-Wert des Produkts
                # minus OpportunityCost der Inputs, die ZUGLEICH im Ziel-
                # preisvektor stehen (11.2). Der überlaufende Input selbst
                # hat außerhalb des Ziels Alternativwert 0 — er verfiele
                # sonst am Cap (11.4).
                units = batch * (1.0 + _craft_ratio(snap))
                ben = lam.get(craft_name, 0.0) * units
                opp = sum(lam.get(q["name"], 0.0) * q["val"] * batch
                          for q in recipe["prices"] if q["name"] in goal_res)
                nv = shadow.net_value(ben, opp)
                if nv <= 0:
                    cands.append(Candidate(
                        act, 0.0, {"capLoss": 0.0, "netValue": nv},
                        feasible=False,
                        reject_reason=CAP_ACCEPTED_LOSS.format(nv=nv)))
                else:
                    comp = {"capLoss": CAP_OPTION_BASE, "netValue": nv}
                    cands.append(Candidate(act, _score(comp), comp))
            else:
                cands.append(Candidate(act, 1.6, {"capLoss": 1.6}))


def _craft_toward(snap, craft_name: str, gap: float, cands, depth: int,
                  seen: set[str], lam=None, goal_prices=None) -> None:
    """Rekursiver Abstieg im Craft-Graphen (max. Tiefe 4).

    Score (Spec 11.2): Mit λ-Daten NetValue-basiert statt Tiefen-Score —

        EffectiveCost(craft) = Σ_j λ_j·Input_j / CraftYield
                               + OpportunityCost(inputs)

    Herleitung der Implementierung: Inputs AUSSERHALB des Zielpreisvektors
    tragen ihr λ ausschließlich über die Kaskade AUS dem Produkt
    (λ_input = λ_produkt / Inputmenge, shadow._propagate_cascade) — ihr
    Alternativwert ist 0 und sie kürzen sich exakt gegen den Produktnutzen.
    Übrig bleibt als effektive Kostenposition die OPPORTUNITÄT der Inputs,
    die ZUGLEICH im Zielpreisvektor stehen (λ der Alternativverwendung:
    das Ziel direkt bezahlen). NetValue = λ_produkt·Einheiten − Opportunität;
    Basisgewicht 1.0 als Kaskaden-Marker, netValue geht normiert in den
    Score ein (Kaufregel 10.3: negativer NetValue wird nie ausgeführt).
    Kaskade und Batching (kleinste Charge bis Gate, max. 10) bleiben.
    Fallback ohne λ oder ohne λ_Produkt: alter Tiefen-Score
    max(0.5, 2.0 − 0.1·Tiefe)."""
    if depth > 4 or craft_name in seen:
        return
    seen.add(craft_name)
    recipe = A.craft_recipe(snap, craft_name)
    if recipe is None:
        return
    missing = A.missing_for(snap, recipe["prices"])
    if not missing:
        # Inputs vorhanden → so viele craften wie sinnvoll (bis 10)
        max_by_inputs = min(
            (A.res_value(snap, q["name"]) // q["val"]
             for q in recipe["prices"] if q["val"] > 0), default=1)
        batch = max(1, min(10, int(max_by_inputs), math.ceil(gap)))
        lam_prod = (lam or {}).get(craft_name, 0.0)
        if lam and lam_prod > 1e-9:
            yield_per = 1.0 + _craft_ratio(snap)
            goal_res = {p["name"] for p in (goal_prices or [])}
            ben_t = lam_prod * batch * yield_per
            opp_t = sum(lam.get(q["name"], 0.0) * q["val"] * batch
                        for q in recipe["prices"] if q["name"] in goal_res)
            comp = {"craftPath": 1.0, "benefitTime": ben_t, "costTime": opp_t,
                    "netValue": shadow.net_value(ben_t, opp_t)}
            score = _score(comp)
        else:
            score = max(0.5, 2.0 - 0.1 * depth)
            comp = {"milestone": score}
        cands.append(Candidate(
            actions.craft(craft_name, recipe["label"], batch,
                          prices=recipe["prices"], craft_ratio=_craft_ratio(snap)),
            score, comp))
        return
    # Inputs fehlen → craftbare Inputs eine Ebene tiefer anstoßen
    for m in missing:
        if A.craft_recipe(snap, m["name"]) is not None:
            _craft_toward(snap, m["name"], m["missing"], cands, depth + 1, seen,
                          lam=lam, goal_prices=goal_prices)


# ---------------------------------------------------------------- Religion

# Kosten der Unicorn-Opferung (religion.js Ziggurat-Panel):
SACRIFICE_UNICORN_COST = 2500


def _religion_candidates(snap, target, cands) -> None:
    religion = snap.get("religion", {})
    target_name = target.get("name") if target and target["kind"] == "religion_upgrade" else None

    # Religion-Upgrades (Faith-Käufe): Solar Revolution ist DER globale
    # Produktionsmultiplikator (Spec 15.1), Apocrypha schaltet Adore frei.
    for u in religion.get("upgrades", []):
        if u["name"] == target_name or not u["unlocked"]:
            continue
        if u["noStackable"] and (u["on"] or u["val"]):
            continue   # bereits gekauft
        if not A.affordable(snap, u["prices"]):
            continue
        if u["name"] == "solarRevolution":
            comp = {"unlock": 2.0}
        elif u["name"] == "apocripha":
            comp = {"unlock": 1.6}
        elif u["name"] == "transcendence":
            comp = {"unlock": 1.2}
        else:
            comp = {"economy": 0.9}
        cands.append(Candidate(
            actions.buy_religion_upgrade(u["name"], u["label"], prices=u["prices"]),
            sum(comp.values()), comp))

    # Ziggurat-/Unicorn-Kette (Spec 15.3, vereinfacht bewertet):
    for z in religion.get("ziggurat", []):
        if not z["unlocked"] or not A.affordable(snap, z["prices"]):
            continue
        cands.append(Candidate(
            actions.buy_religion_upgrade(z["name"], z["label"], ziggurat=True,
                                         prices=z["prices"]),
            1.0, {"economy": 1.0}))

    # Unicorns opfern, sobald ein Batch voll ist und ein Ziggurat steht:
    if A.bld_val(snap, "ziggurat") >= 1 \
            and A.res_value(snap, "unicorns") >= SACRIFICE_UNICORN_COST:
        cands.append(Candidate(actions.sacrifice_unicorns(), 1.5, {"economy": 1.5}))


def _religion_ev_candidates(snap, cands, lam, horizon) -> None:
    """EV-Kandidaten der Religion-Endgame-Ökonomie (Spec 15.4/15.5).

    Transcend läuft bewusst NICHT hier: die TAP-Transaktion gehört
    ausschließlich in die Pre-Reset-Transaktion (Spec 15.2,
    reset.execute_reset Schritt 5). Hier laufen nur die Grenzwert-
    Konvertierungen (Alicorn→TC, Tears→BLS) und die Pact-Ökonomie —
    jeweils mit Sekundenwert-Komponente (tapValue/pactValue) als
    Anzeige, netValue-frei (Score über die economy-Komponente)."""
    lam = lam or {}

    # Alicorns → Time Crystals (15.4, λ-Grenzwertregel + Anachronomancy):
    due, det = religion.alicorn_conversion_due(snap, lam)
    if due and det["batches"] >= 1:
        comp = {"economy": 1.2, "tapValue": det["gainS"] - det["keepS"]}
        cands.append(Candidate(actions.convert_alicorns(det["batches"]),
                               _score(comp), comp))

    # Tears → Black Liquid Sorrow (15.3, Grenzwertregel analog):
    due, det = religion.tears_refine_due(snap, lam)
    if due and det["batches"] >= 1:
        comp = {"economy": 1.0, "tapValue": det["gainS"] - det["keepS"]}
        cands.append(Candidate(actions.refine_tears(det["batches"]),
                               _score(comp), comp))

    # Pacts (15.5): Kauf nur bei positivem PactValue UND vorhandenen
    # Snapshot-Daten (pact_value liefert sonst None — Schicht inaktiv).
    pacts = snap.get("pacts")
    if isinstance(pacts, dict) and (pacts.get("pactsAvailable") or 0) > 0:
        for p in pacts.get("list", []):
            if not p.get("unlocked") or p.get("special"):
                continue
            if p.get("name") not in religion.PACT_UTILITY_RATIO:
                continue
            if not A.affordable(snap, p.get("prices") or []):
                continue
            pv = religion.pact_value(snap, p["name"], lam, horizon)
            if not pv or not pv.get("positive"):
                continue
            comp = {"economy": 1.0, "pactValue": pv["pactValueS"]}
            cands.append(Candidate(
                actions.buy_pact(p["name"], p.get("label") or p["name"],
                                 p.get("prices")),
                _score(comp), comp))

    # Siphoning (15.5): Policy nur, wenn die Schuldkosten-Reduktion den
    # unmittelbaren Necrocorn-Nutzen übersteigt (religion.siphoning_due,
    # sonst dokumentiert konservativ AUS). Kauf über den Policy-Weg
    # (I-07-Prüfung im echten Controller, BUY_POLICY_JS).
    due, det = religion.siphoning_due(snap, lam)
    if due:
        pol = next((q for q in snap.get("policies") or []
                    if q.get("name") == "siphoning"), None)
        if pol and pol.get("unlocked") and not pol.get("researched") \
                and not pol.get("blocked") \
                and A.affordable(snap, pol.get("prices") or []):
            comp = {"policy": 1.0,
                    "pactValue": det["reductionS"] - det["foregoneS"]}
            cands.append(Candidate(
                actions.select_policy("siphoning",
                                      pol.get("label") or "Siphoning",
                                      pol.get("prices")),
                _score(comp), comp))


# ---------------------------------------------------------------- Space

# Welche Planeten-Gebäude produzieren was (für Engpass-Kopplung):
SPACE_BUILDING_PRODUCES = {
    "sattelite": "starchart",
    "moonOutpost": "unobtainium",
    "planetCracker": "uranium",
    "hydrofracturer": "oil",
    "researchVessel": "starchart",
    "sunlifter": "energy",
}


def _space_building_candidates(snap, target, bn, cands, lam=None) -> None:
    """Space-Gebäude-Kandidaten inkl. 16.2-Energieregel: ein Gebäude mit
    positiver Rohproduktion bekommt einen Energie-Malus, wenn sein
    Verbrauch (Snapshot-Feld energyConsumption, space.js effects) das
    Energie-Budget ins Defizit drückt — das Defizit drosselt die effektive
    Produktion der Critical-Path-Gebäude (I-04). Der Malus greift nur mit
    λ-Daten (es gibt dann ein bewertetes Ziel, dessen Produktion leidet);
    ohne λ- oder Energie-Daten bleibt das Altverhalten (Fallback)."""
    target_name = target.get("name") if target and target["kind"] == "space_build" else None
    balance = snap.get("derived", {}).get("energy", {}).get("balance", 0)
    for planet in snap.get("space", {}).get("planets", []):
        for b in planet.get("buildings", []):
            if b["name"] == target_name:
                continue   # läuft bereits als Meilenstein-Kandidat
            if not b["unlocked"] or not A.affordable(snap, b["prices"]):
                continue
            comp: dict[str, float] = {}
            produces = SPACE_BUILDING_PRODUCES.get(b["name"])
            if bn and produces and produces == bn.get("resource"):
                comp["bottleneck"] = 1.8
            else:
                comp["economy"] = 0.8   # Space-Ausbau ist fast immer Fortschritt
            cons = float(b.get("energyConsumption") or 0)
            if lam and cons > 0 and balance - cons < 0:
                comp["energyCost"] = -1.5   # 16.2: Defizit drosselt den Critical Path
            deltas = actions.price_deltas(b["prices"])
            act = actions.Action(
                id=f"space_bld:{b['name']}", type="BUY_BUILDING",
                label=f"Baue {b['label']} ({planet['label']}, Nr. {b['val'] + 1})",
                exec_spec={"kind": "click_button", "tab": "Space",
                           "panel": planet["label"], "title": b["label"], "batch": 1},
                expected=f"{b['label']} auf {b['val'] + 1}",
                predicted={"deltas": deltas, "stochastic": False} if deltas else None,
            )
            cands.append(Candidate(act, _score(comp), comp))


# ---------------------------------------------------------------- Handel

# Fixkosten jedes Trades (zusätzlich zur rassespezifischen Ware):
TRADE_GOLD_COST = 15
TRADE_MANPOWER_COST = 50
# Erwartungsmengen-Formel (Spec 14.1) — Referenzwerte Kittens Game 1.5.0.2,
# diplomacy.js tradeImpl:
#   E[Menge] = value · (1 + seasons[saison]) · (1 + tradeRatio)
#              · chance/100 · Standing-Faktor
# tradeRatio-Effekt = +1 % Erfolgsmenge pro Trade Ship;
# hostile:  P(Trade gelingt) = standing + standingRatio/100 (geklemmt [0,1]);
# friendly: Bonus-Chance = standing + standingRatio/200 → Menge ×1.25.
# Was der Snapshot nicht liefert (seasons/standing/tradeRatio), wird
# konservativ mit Faktor 1.0 bzw. Modifikator 0.0 angesetzt.
TRADE_SHIP_RATIO = 0.01
TRADE_FRIENDLY_BONUS = 0.25


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _trade_expected_yield(snap, race: dict, diplo: dict) -> dict[str, float]:
    """Erwartete Menge je Ressource für EINEN Trade (Ergebnisverteilung 14.1)."""
    season = snap.get("calendar", {}).get("seasonName", "")
    trade_ratio = diplo.get("tradeRatio")
    if trade_ratio is None:
        # Fallback: +1 % pro Trade Ship (Referenz 1.5.0.2, „tradeRatio"-Effekt).
        trade_ratio = TRADE_SHIP_RATIO * A.res_value(snap, "ship")
    standing_ratio = diplo.get("standingRatio") or 0.0
    attitude = race.get("attitude") or "neutral"
    standing = race.get("standing") or 0.0
    success, bonus = 1.0, 1.0
    if attitude == "hostile":
        success = _clamp01(standing + standing_ratio / 100.0)
    elif attitude == "friendly":
        bonus = 1.0 + TRADE_FRIENDLY_BONUS * _clamp01(standing + standing_ratio / 200.0)
    out: dict[str, float] = {}
    for s in race.get("sells", []):
        season_mod = (s.get("seasons") or {}).get(season, 0.0) or 0.0
        chance = _clamp01((s.get("chance") or 0.0) / 100.0)
        amount = ((s.get("value") or 0.0) * (1.0 + season_mod)
                  * (1.0 + trade_ratio) * chance * success * bonus)
        if amount > 0:
            out[s["name"]] = out.get(s["name"], 0.0) + amount
    return out


def _trade_value(snap, race: dict, diplo: dict, lam: dict[str, float]) -> float:
    """TradeValue(race) = Σ_o P(o|race,state)·Value(o) − Value(costs) in
    Ziel-Sekunden (Spec 14.1); Value über Schattenpreise λ. Kosten sind die
    Fixkosten (Gold/Catpower) plus die verkaufte Ware (buys)."""
    gain = sum(lam.get(res, 0.0) * amt
               for res, amt in _trade_expected_yield(snap, race, diplo).items())
    costs = ([{"name": "gold", "val": TRADE_GOLD_COST},
              {"name": "manpower", "val": TRADE_MANPOWER_COST}]
             + [{"name": p["name"], "val": p["val"]} for p in race.get("buys", [])])
    return gain - shadow.cost_time(costs, lam)


def _trade_action(snap, race: dict, diplo: dict, batch: int) -> "actions.Action":
    """Trade-Aktion mit stochastischer EV-Prognose (14.1): Fixkosten + Ware
    sicher, Erträge als Erwartungswerte (großzügige Toleranz, G-10)."""
    act = actions.trade(race["name"], race["title"], batch)
    deltas: dict[str, float] = {
        "gold": -float(TRADE_GOLD_COST * batch),
        "manpower": -float(TRADE_MANPOWER_COST * batch),
    }
    for p in race.get("buys", []):
        deltas[p["name"]] = deltas.get(p["name"], 0.0) - float(p["val"]) * batch
    for res, amt in _trade_expected_yield(snap, race, diplo).items():
        deltas[res] = deltas.get(res, 0.0) + amt * batch
    act.predicted = {"deltas": deltas, "stochastic": True}
    return act


def _trade_candidates(snap, bn, cands, lam=None) -> None:
    diplo = snap.get("diplomacy", {})
    races = A.races(snap)
    gold = A.res_value(snap, "gold")
    manpower = A.res_value(snap, "manpower")

    # Kundschafter: WEITERE Handelspartner sind ein Unlock (Optionswert).
    # Der erste kommt automatisch per Emissär — vorher wäre der Catpower-
    # Einsatz verschwendet (diplomacy.js: unlockRandomRace via update()).
    if diplo.get("undiscovered") and manpower >= 1000 and races:
        cands.append(Candidate(actions.explore(), 1.6, {"unlock": 1.6}))

    if not races:
        return

    for race in races:
        # Leviathans liefern Time Crystals + Relics — persistenter Endgame-
        # Wert, solange sie da sind immer handeln (Spec 14.4 vereinfacht):
        if race["name"] == "leviathans":
            batch = int(min(manpower // TRADE_MANPOWER_COST, 5)) if manpower else 5
            for p in race.get("buys", []):
                have = A.res_value(snap, p["name"])
                batch = int(min(batch, have // p["val"])) if p["val"] else batch
            if batch >= 1:
                cands.append(Candidate(
                    _trade_action(snap, race, diplo, batch), 1.7,
                    {"economy": 1.7}))
            continue
        sells_bottleneck = bn and bn.get("resource") and any(
            s["name"] == bn["resource"] for s in race.get("sells", []))
        trade_val = None
        if lam:
            # TradeValue-EV (Spec 14.1): Handel nur bei positivem
            # Erwartungswert über die Ergebnisverteilung.
            trade_val = _trade_value(snap, race, diplo, lam)
            if trade_val <= 0:
                continue
        elif not sells_bottleneck:
            # Fallback ohne λ-Daten (TradeValue-light, Bestandsverhalten):
            # Handel nur, wenn die Rasse den aktuellen Engpass liefert.
            continue
        batch = int(min(gold // TRADE_GOLD_COST, manpower // TRADE_MANPOWER_COST, 5))
        for p in race.get("buys", []):
            have = A.res_value(snap, p["name"])
            batch = int(min(batch, have // p["val"])) if p["val"] else batch
        if batch >= 1:
            comp = {"bottleneck": 1.7} if sells_bottleneck else {"economy": 0.9}
            if trade_val is not None:
                comp["tradeValue"] = trade_val * batch   # Sekundenwert, Anzeige
            _apply_food_risk(snap, comp, race.get("buys", []))
            cands.append(Candidate(
                _trade_action(snap, race, diplo, batch),
                _score(comp), comp,
            ))

    # Gold am Cap ist verschenkter Handelsspielraum (Cap-Regel 11.4):
    # 0.95-Füllstand bleibt Trigger-Vorfilter; mit λ-Daten entscheidet der
    # NetValue-Sekundenwert (TradeValue 14.1) über die Auswahl — NetValue
    # ≤ 0 ⇒ akzeptierter Verlust (CAP_OPTION_BASE, siehe Kommentar oben).
    gold_res = A.resource(snap, "gold")
    if gold_res and gold_res.get("maxValue", 0) > 0 \
            and gold_res["value"] / gold_res["maxValue"] > 0.95 \
            and manpower >= TRADE_MANPOWER_COST:
        race = races[0]
        batch = int(min(gold // TRADE_GOLD_COST, manpower // TRADE_MANPOWER_COST, 3))
        for p in race.get("buys", []):
            have = A.res_value(snap, p["name"])
            batch = int(min(batch, have // p["val"])) if p["val"] else batch
        if batch >= 1 and not any(c.action.id == f"trade:{race['name']}" for c in cands):
            act = _trade_action(snap, race, diplo, batch)
            if lam:
                nv = _trade_value(snap, race, diplo, lam) * batch
                if nv <= 0:
                    cands.append(Candidate(
                        act, 0.0, {"capLoss": 0.0, "netValue": nv},
                        feasible=False,
                        reject_reason=CAP_ACCEPTED_LOSS.format(nv=nv)))
                else:
                    comp = {"capLoss": CAP_OPTION_BASE, "netValue": nv}
                    cands.append(Candidate(act, _score(comp), comp))
            else:
                cands.append(Candidate(act, 1.1, {"capLoss": 1.1}))


# ---------------------------------------------------------------- Religion / Festival

# EV-Timing Praise (Spec 15.1): Cap-Puffer ≈ ein Entscheidungsintervall —
# läuft Faith vorher ans Cap, verfällt Produktion; Fallback-Schwelle 95 %.
PRAISE_CAP_BUFFER_S = 60.0
PRAISE_FILL_FALLBACK = 0.95


def _praise_candidate(snap, cands, lam=None, horizon=None) -> None:
    # Faith am Cap verfällt — Praise wandelt sie in dauerhaften Worship (15.1).
    faith = A.resource(snap, "faith")
    if not faith or faith.get("maxValue", 0) <= 0:
        return
    # Sparregel (absoluter Vorrang, unverändert): Faith ist auch Kaufwährung
    # der Religion-Upgrades. Solange ein erreichbares (Cap reicht) Upgrade
    # offen ist, wird gespart statt gepriesen.
    cap = faith["maxValue"]
    for u in snap.get("religion", {}).get("upgrades", []):
        if not u["unlocked"] or (u["noStackable"] and (u["on"] or u["val"])):
            continue
        price = next((p["val"] for p in u["prices"] if p["name"] == "faith"), None)
        if price is not None and price <= cap:
            return

    fill = faith["value"] / cap
    if lam:
        # EV-Regel (Spec 15.1): Praise nur, wenn Cap-Verlust wirklich droht
        # (Cap-Zeit unter dem Entscheidungspuffer oder Fallback-Füllstand) …
        rate = faith.get("perSec", 0.0)
        cap_time = ((cap - faith["value"]) / rate
                    if rate > A.RATE_EPS else math.inf)
        if fill < PRAISE_FILL_FALLBACK and cap_time >= PRAISE_CAP_BUFFER_S:
            return
        lam_f = lam.get("faith", 0.0)
        if lam_f > 0.0:
            # … und der integrierte Produktionsgewinn (vermiedene Cap-
            # Verlustrate × λ_faith über den Horizont) den Wert des Haltens
            # (λ_faith × Bestand — das Ziel braucht die Faith) übersteigt.
            gain = lam_f * max(0.0, rate) * (horizon or shadow.HORIZON_MIN)
            hold = lam_f * faith["value"]
            if gain <= hold:
                return
            comp = {"capLoss": 1.5, "praiseValue": gain - hold}  # s-Wert, Anzeige
            cands.append(Candidate(actions.praise(), _score(comp), comp))
            return
        cands.append(Candidate(actions.praise(), 1.5, {"capLoss": 1.5}))
        return

    # Fallback ohne λ-Daten (Bestandsverhalten): 95-%-Schwelle.
    if fill < PRAISE_FILL_FALLBACK:
        return
    cands.append(Candidate(actions.praise(), 1.5, {"capLoss": 1.5}))


# Festivalkosten sind im Spiel fix verdrahtet (village.js FestivalButton):
FESTIVAL_PRICES = [
    {"name": "manpower", "val": 1500},
    {"name": "culture", "val": 5000},
    {"name": "parchment", "val": 2500},
]


def _festival_candidate(snap, cands) -> None:
    if snap.get("calendar", {}).get("festivalDays", 0) > 0:
        return
    if not A.tech_researched(snap, "drama"):
        return
    if not A.affordable(snap, FESTIVAL_PRICES):
        return
    # +30 % Happiness wirkt auf die gesamte Produktion — fast immer gut.
    happiness = snap.get("village", {}).get("happiness", 1.0)
    score = 1.8 if happiness < 1.3 else 1.2
    cands.append(Candidate(actions.festival(), score, {"happiness": score}))


# ---------------------------------------------------------------- Time (M6/M8)

HEAT_PER_SHATTER = 10   # time.js:1407 (5 mit 1000-Years-Erstabschluss)

# Void-Struktur-Nutzenraten (Spec 19.3): breite Ratio-Effekte aus
# gamefiles/js/time.js voidspaceUpgrades; schmale Spezialeffekte gehen als
# REFERENZSCHÄTZUNG mit Gewicht 0.2 ein (Muster wie religion.PACT_UTILITY_RATIO).
VOIDSPACE_UTILITY_RATIO: dict[str, float] = {
    # globalResourceRatio 0.02 + umbraBoostRatio 0.1 (schmal, time.js:600-603):
    "voidRift": 0.02 + 0.1 * 0.2,
    # voidResonance 0.1 — nur Order-of-the-Void-Trigger (time.js:643-645):
    "voidResonator": 0.1 * 0.2,
    # temporalParadoxDay/Void — schmale Zeit-Effekte (time.js:588-590/618-623):
    "voidHoover": 0.01 * 0.2,
    "chronocontrol": 0.01 * 0.2,
}


def _time_candidates(snap, cands, lam=None, horizon=None, run_type=None) -> None:
    """Time-Tab-Kandidaten: Chronoforge (RR-/Furnace-Wert 17.2/17.3),
    Voidspace (19.3) und die Shatter-Engine (17.5, timecrystal.py).

    Mit λ-Daten steuern rr_value/furnace_value die Chronoforge-Prioritäten
    und shatter_decision die Shatter-Regel; ohne λ- oder Time-Daten bleibt
    exakt das bisherige konservative Verhalten (Fallback, kein Crash)."""
    time_state = snap.get("time", {})
    horizon = horizon if horizon is not None else shadow.HORIZON_MIN
    rrv = timecrystal.rr_value(snap, lam) if lam else None
    fnv = timecrystal.furnace_value(snap, lam, horizon) if lam else None

    # Chronoforge-Ausbau (Resource Retrieval, Furnaces, Batteries):
    for u in time_state.get("chronoforge", []):
        if not u["unlocked"] or not A.affordable(snap, u["prices"]):
            continue
        reject = None
        if u["name"] == "ressourceRetrieval":
            comp: dict[str, float] = {"economy": 1.3}
            if rrv is not None:
                # 17.2: nächstes RR nur bei positivem RRValue, der auch den
                # Wert eines zusätzlichen Chrono Furnace übersteigt.
                comp["rrValue"] = rrv["rrValueS"]
                if rrv["rrValueS"] <= 0:
                    reject = (f"RRValue {rrv['rrValueS']:.0f} s ≤ 0 — Ertrag "
                              f"deckt den TC-Preis nicht (17.2)")
                elif fnv is not None and fnv["furnaceValueS"] > rrv["rrValueS"]:
                    reject = (f"Chrono Furnace ist wertvoller "
                              f"({fnv['furnaceValueS']:.0f} s > "
                              f"{rrv['rrValueS']:.0f} s, 17.2)")
        elif u["name"] == "blastFurnace" and fnv is not None:
            # 17.3: Furnace nur, wenn Heat die Batchgröße tatsächlich begrenzt.
            comp = {"economy": 0.9, "furnaceValue": fnv["furnaceValueS"]}
            if fnv["furnaceValueS"] <= 0:
                reject = (f"FurnaceValue {fnv['furnaceValueS']:.0f} s ≤ 0 — "
                          f"Heat begrenzt die Shatter-Batches nicht (17.3)")
        else:
            comp = {"economy": 0.8}
        deltas = actions.price_deltas(u["prices"])
        act = actions.Action(
            id=f"chronoforge:{u['name']}", type="BUY_UPGRADE",
            label=f"Chronoforge: {u['label']}",
            exec_spec={"kind": "click_button", "tab": "Time", "title": u["label"], "batch": 1},
            expected=f"{u['label']} auf {u['val'] + 1}",
            predicted={"deltas": deltas, "stochastic": False} if deltas else None,
        )
        if reject:
            cands.append(Candidate(act, 0.0, dict(comp), feasible=False,
                                   reject_reason=reject))
        else:
            cands.append(Candidate(act, _score(comp), comp))

    # Voidspace (Spec 19/19.3):
    for u in time_state.get("voidspace", []):
        if not u["unlocked"] or not A.affordable(snap, u["prices"]):
            continue
        deltas = actions.price_deltas(u["prices"])
        if u["name"] == "cryochambers":
            # Cryochambers (Kitten-Carryover) bleiben in jedem Run wertvoll:
            cands.append(Candidate(actions.Action(
                id="voidspace:cryochambers", type="BUY_UPGRADE",
                label="Cryochamber bauen (Kitten-Carryover)",
                exec_spec={"kind": "click_button", "tab": "Time", "title": u["label"], "batch": 1},
                expected="Ein Kitten überlebt den nächsten Reset",
                predicted={"deltas": deltas, "stochastic": False} if deltas else None,
            ), 1.4, {"economy": 1.4}))
            continue
        # Übrige Void-Strukturen NUR im SEED_RUN (19.3: Void-Farming ist ein
        # eigener MacroPlan, kein Beiläufig-Einbau in Paragon-Runs):
        if run_type != "SEED_RUN":
            continue
        ratio = VOIDSPACE_UTILITY_RATIO.get(u["name"])
        if ratio is None:
            continue
        comp = {"economy": 0.9, "voidValue": ratio * horizon}
        cands.append(Candidate(actions.Action(
            id=f"voidspace:{u['name']}", type="BUY_UPGRADE",
            label=f"Voidspace: {u['label']}",
            exec_spec={"kind": "click_button", "tab": "Time", "title": u["label"], "batch": 1},
            expected=f"{u['label']} auf {u['val'] + 1}",
            predicted={"deltas": deltas, "stochastic": False} if deltas else None,
        ), _score(comp), comp))

    # Shatter (Spec 17.5): mit λ- und Time-Daten entscheidet die Engine
    # (Regeln A–D, Batch-Maximierung unter Heat-/Cap-Constraints):
    if lam and timecrystal.has_time_data(snap):
        dec = timecrystal.shatter_decision(snap, lam, horizon)
        if dec is not None:
            batch, rule, detail = dec
            comp = {"economy": 1.1}
            if detail.get("valueS"):
                comp["shatterValue"] = detail["valueS"]
            act = actions.shatter(batch)
            act.expected += f" — Regel {rule} (17.5): {detail}"
            cands.append(Candidate(act, _score(comp), comp))
        return

    # Fallback ohne λ-Daten (Bestandsverhalten): konservative Shatter-Regel —
    # nur mit Resource-Retrieval-Infrastruktur und Heat-Spielraum.
    tc = A.res_value(snap, "timeCrystal")
    rr = next((u["val"] for u in time_state.get("chronoforge", [])
               if u["name"] == "ressourceRetrieval"), 0)
    heat = time_state.get("heat", 0)
    heat_max = time_state.get("heatMax", 0)
    if rr >= 1 and tc >= 10 and heat_max > 0:
        headroom = int((heat_max - heat) // HEAT_PER_SHATTER)
        batch = min(5, int(tc) - 5, headroom)   # 5 TC Reserve behalten
        if batch >= 1:
            cands.append(Candidate(actions.shatter(batch), 1.1, {"economy": 1.1}))


# ---------------------------------------------------------------- Tempus Fugit (Anhang B)

# Hysterese-Schwellen (Anti-Flattern, Muster wie ENERGY_REACTIVATE_MARGIN):
# aktivieren erst ab 2 min Flux-Vorrat, deaktivieren unter 30 s — dazwischen
# bleibt der Zustand unverändert (kein Kandidat). Flux-Verbrauch: 1 Tick
# temporalFlux je Spieltick (time.js:153-155) → Vorrat in Sekunden = Ticks/tps.
TEMPUS_ON_MIN_FLUX_S = 120.0
TEMPUS_OFF_MIN_FLUX_S = 30.0
# Beschleunigungsfaktor: +50 % Spielgeschwindigkeit (game.js:3964/3984).
TEMPUS_ACCEL_RATIO = 0.5


def _tempus_fugit_candidate(snap, cands, lam=None, horizon=None) -> None:
    """Tempus-Fugit-Nutzenregel (Anhang B SET_TEMPUS_FUGIT):

    AN, wenn Flux-Vorrat ≥ TEMPUS_ON_MIN_FLUX_S UND das aktive Ziel von
    Beschleunigung profitiert (positives λ-gewichtetes Produktionsprofil —
    Σ λ_i · Rate_i > 0); AUS, wenn Flux knapp (< TEMPUS_OFF_MIN_FLUX_S).
    Fallback: ohne Tempus-Fugit-Zustand im Snapshot (isAccelerated fehlt)
    oder ohne λ-Daten für die AN-Regel entsteht kein Kandidat."""
    time_state = snap.get("time", {})
    if "isAccelerated" not in time_state:
        return
    accelerated = bool(time_state.get("isAccelerated"))
    tf = time_state.get("temporalFlux")
    flux_ticks = (float(tf.get("value", 0.0)) if isinstance(tf, dict)
                  else A.res_value(snap, "temporalFlux"))
    tps = float(snap.get("meta", {}).get("ticksPerSecond", 5) or 5)
    flux_s = flux_ticks / tps

    if accelerated:
        if flux_s < TEMPUS_OFF_MIN_FLUX_S:
            comp = {"tempusFugit": 1.2}
            cands.append(Candidate(
                actions.set_tempus_fugit(False), _score(comp), comp))
        return

    if flux_s < TEMPUS_ON_MIN_FLUX_S or not lam:
        return
    # λ-gewichtetes Produktionsprofil: Ziel-Sekunden je Realsekunde Produktion.
    prod = sum(lam.get(r["name"], 0.0) * r.get("perSec", 0.0)
               for r in snap.get("resources", [])
               if r.get("perSec", 0.0) > 0)
    if prod <= 0:
        return
    # Gewinn: +50 % Produktion, solange der Flux-Vorrat trägt (max. Horizont).
    gain = TEMPUS_ACCEL_RATIO * prod * min(flux_s, horizon or shadow.HORIZON_MIN)
    comp = {"tempusFugit": 1.0, "tfValue": gain}
    cands.append(Candidate(actions.set_tempus_fugit(True), _score(comp), comp))


# ---------------------------------------------------------------- WAIT

def _wait_candidate(snap, bn, cands, meta_view) -> None:
    if bn and bn.get("resource"):
        miss = ", ".join(f"{m['missing']:.0f} {m['name']}" for m in bn.get("missing", []))
        eta = bn.get("etaSeconds")
        if (eta is None or not math.isfinite(eta)):
            conv = _conversion_eta(snap, bn)
            if conv is not None and math.isfinite(conv):
                eta = conv   # endliche Weckbedingung über die Konversionskette
        reason = (f"Warte auf {bn['resource']} für „{meta_view.objective_label}“: "
                  f"fehlen {miss} (~{fmt_duration(eta)})")
        wake = "Replan bei Bezahlbarkeit, neuem Unlock oder Kitten-Ankunft"
    else:
        reason = "Kein Kandidat mit positivem Wert — beobachte Produktion"
        wake = "Replan beim nächsten Ereignis"
    cands.append(Candidate(actions.wait(reason, wake), WAIT_SCORE, {"base": WAIT_SCORE}))


# ================================================================ Deadlock (22.3)

def _conversion_eta(snap: dict, bn: dict | None) -> float | None:
    """Endliche Weckbedingung über die KONVERSIONSKETTE (Live-Deadlock-Fund):
    Ist die Engpass-Ressource per Refine/Craft herstellbar (Rezepte wie in
    shadow.REFINE_RECIPES bzw. Workshop-Crafts), liefert dies die Zeit, bis
    die Inputs für EINE Konversionseinheit reichen — z. B. Catnip wächst auf
    100 fürs erste Refine, obwohl die Holzrate selbst 0 ist. None, wenn keine
    Konversion existiert oder kein Input in endlicher Zeit erreichbar ist."""
    res = (bn or {}).get("resource")
    if not res:
        return None
    recipe = A.craft_recipe(snap, res)
    prices = recipe["prices"] if recipe else shadow.REFINE_RECIPES.get(res)
    if not prices:
        return None
    worst = 0.0
    for p in prices:
        missing = p["val"] - A.res_value(snap, p["name"])
        if missing <= 0:
            continue
        rate = A.res_rate(snap, p["name"])
        if rate <= 0:
            return None
        worst = max(worst, missing / rate)
    return worst


def is_deadlock(candidates: list[Candidate], bn: dict | None,
                snap: dict | None = None) -> bool:
    """Deadlock-Definition (Spec 22.3): kein zulässiger Kandidat mit
    positivem Score existiert UND WAIT hat keine Weckbedingung mit
    endlicher Zeit. Endliche Weckbedingungen sind die Engpass-ETA ODER —
    mit Snapshot — die Konversions-ETA (_conversion_eta): Warten verbessert
    den Zustand auch, wenn der Input einer Refine-/Craft-Konversion in
    endlicher Zeit reicht."""
    if any(c.feasible and c.score > 0 and c.action.type != "WAIT"
           for c in candidates):
        return False
    eta = (bn or {}).get("etaSeconds")
    if eta is not None and math.isfinite(eta):
        return False
    if snap is not None:
        conv = _conversion_eta(snap, bn)
        if conv is not None and math.isfinite(conv):
            return False
        # Food-Erholung ist eine endliche Weckbedingung (Live-Fund: bei
        # Warn-/Kritisch-Lage sperren Safety-Gates viele Kandidaten — das
        # ist gewolltes Warten, kein Deadlock, solange Catnip wächst oder
        # die nächste Saison die Felder verstärkt):
        food = snap.get("derived", {}).get("food", {})
        if food.get("status", "ok") != "ok" and A.res_rate(snap, "catnip") > 0:
            return False
    return True


def resolve_deadlock(snap: dict, meta_view, safety_result, *,
                     run_horizon_s: float | None = None
                     ) -> tuple[list[Candidate], dict | None, dict]:
    """Generische Deadlock-Auflösung (Spec 22.3) — deterministisch, EIN
    Durchlauf, kein Loop:

    (a) Makrohorizont der λ-/Payback-Bewertung verdoppeln und einmal neu
        bewerten (längerer Horizont kann Payback-Gates 10.4 öffnen);
    (b) zusätzlich die Suchraum-Heuristik lockern: ECONOMY_WHITELIST-
        Beschränkung der Gebäude-Kandidaten aufheben (nur für DIESE
        Bewertung — der Normalzyklus behält die Heuristik);
    (c) bleibt der Deadlock, wird eine Frontier-Wächter-Meldung „deadlock"
        erzeugt (frontier.deadlock_notice — der Betreiber sieht sie im
        Cockpit), und der Agent wartet weiter.

    Sicherheitsinvarianten und Versionsbindung werden NIEMALS gelockert
    (22.3 Satz 2): blocked_types, foodRisk, Storage-Gates 11.3 und die
    Kaufregel 10.3 gelten in jeder Stufe unverändert.

    Rückgabe: (candidates, bottleneck, detail) mit detail["stage"] ∈
    {"a", "b", "c"}; in Stufe c zusätzlich detail["notice"]."""
    cands, bn = generate(snap, meta_view, safety_result, horizon_scale=2.0,
                         run_horizon_s=run_horizon_s)
    if not is_deadlock(cands, bn, snap):
        return cands, bn, {"stage": "a",
                           "detail": "Horizontverdopplung löst den Deadlock (22.3 a)"}
    cands, bn = generate(snap, meta_view, safety_result, horizon_scale=2.0,
                         relax_whitelist=True, run_horizon_s=run_horizon_s)
    if not is_deadlock(cands, bn, snap):
        return cands, bn, {"stage": "b",
                           "detail": "gelockerter Suchraum (ECONOMY_WHITELIST auf) "
                                     "löst den Deadlock (22.3 b)"}
    notice = frontier.deadlock_notice(meta_view.run_type,
                                      meta_view.objective_label)
    return cands, bn, {"stage": "c",
                       "detail": "Deadlock bleibt — Frontier-Meldung (22.3 c)",
                       "notice": notice}


# ================================================================ Begründung

REASON_TEMPLATES = {
    "safety": "Sicherheitsinvariante: {label} schützt die Food-Versorgung.",
    "milestone": "{label} bringt den aktiven Meilenstein direkt voran.",
    "bottleneck": "{label} löst den aktuellen Engpass ({res}).",
    "jobValue": "Freie Kitten sind ungenutzte Produktion — {label}.",
    "unlock": "{label} schaltet neue Möglichkeiten frei (Unlock-first-Regel).",
    "housing": "{label}: mehr Kitten = mehr Produktion (Food-Reserve ist sicher).",
    "storage": "{label}: eine Storage-Bedingung ist erfüllt (Storage-Regel 11.3 A–D).",
    "storageB": "{label}: zusätzlicher Carryover-Wert übersteigt die Baukosten (11.3 B).",
    "storageC": "{label}: verhindert bewerteten Cap-Verlust im Puffer (11.3 C).",
    "capLoss": "{label} verhindert Produktionsverlust am Ressourcen-Cap.",
    "foodSafe": "{label}: Food-Projektion bleibt auch ohne diesen Farmer sicher (Winter vorbei).",
    "economy": "{label} ist eine günstige Ökonomie-Investition.",
    "happiness": "{label}: Happiness wirkt als Multiplikator auf die gesamte Produktion.",
    "energy": "{label}: das Energie-Defizit drosselt die Produktion (Invariante I-04).",
    "energyRelief": "{label}: Energie-Steuerung nach 16.4 (Zielbeitrag je Energieeinheit).",
    "leader": "{label}: Trait mit der größten Zielzeitverkürzung (Leader-Regel 12.3).",
    "leaderValue": "{label}: prognostizierter Zielzeitgewinn des Trait-Wechsels (12.3).",
    "netValue": "{label} spart netto Zielzeit (Schattenpreis-Bewertung 10.2/10.3).",
    "delayPenalty": "{label} würde das aktuelle Sparziel verzögern (DelayPenalty 10.3).",
    "savingFor": "{label}: Sparziel aktiv — billigere Käufe werden zurückgehalten.",
    "allocDeficit": "{label}: Soll-Allokation 12.2 — größtes Job-Defizit zuerst.",
    "potential": "{label} ist das aktuelle Sparziel (noch nicht bezahlbar).",
    "optionValue": "{label}: Optionswert = Verkürzung der Rest-ETA durch den Unlock (8.4).",
    "craftPath": "{label}: Craft-Kaskade zum Ziel, Score aus NetValue/EffectiveCost (11.2).",
    "benefitTime": "{label} beschleunigt das Ziel (Benefit in Ziel-Sekunden).",
    "costTime": "{label} kostet Ziel-Sekunden (Schattenpreis-Bewertung).",
    "pollutionCost": "{label} verlangsamt über Pollution die Kitten-Ankünfte (13.2, Zeitkosten).",
    "jobScore": "{label} maximiert den Zielzeitgewinn pro Kitten (JobScore 12.2).",
    "csValue": "{label}: Carryover-Sekundenwert der nächsten Chronosphere (CS-Suche 19.1).",
    "policy": "{label}: beste Policy des Kontexts, I-07 gegen alle Alternativen geprüft (13.4).",
    "policyValue": "{label}: λ-bewerteter Modifikator-Gewinn über den Restplan-Horizont (13.4).",
    "tradeValue": "{label}: positiver Handels-Erwartungswert über die Ergebnisverteilung (TradeValue 14.1).",
    "huntValue": "{label}: erwartete Beute ist jetzt mehr wert als das Warten auf einen größeren Batch (14.2).",
    "praiseValue": "{label}: drohender Faith-Cap-Verlust wiegt schwerer als das Halten (15.1).",
    "tapValue": "{label}: λ-Grenzwert der Konvertierung übersteigt den Haltewert (15.3/15.4).",
    "pactValue": "{label}: PactValue = ΔBPU − Debt − Upkeep − Necrocorn-Alternativwert > 0 (15.5).",
    "rrValue": "{label}: RRValue = Grenzertrag × erwartete Shatter − TC-Preis·λ_TC > 0 (17.2).",
    "furnaceValue": "{label}: FurnaceValue = vermiedene Heat-Wartezeit + Batch-Wert − Kosten (17.3).",
    "shatterValue": "{label}: Shatter-Regel A–D erfüllt, Batch unter Heat-/Cap-Constraints maximiert (17.5).",
    "voidValue": "{label}: Void-Struktur-Beitrag im SEED_RUN (19.3, λ-bewertete Nutzenrate).",
    "energyCost": "{label}: Energieverbrauch würde den Critical Path drosseln (16.2).",
    "tempusFugit": "{label}: Tempus-Fugit-Nutzenregel mit Flux-Hysterese (Anhang B).",
    "tfValue": "{label}: +50 % Produktion, solange der Flux-Vorrat trägt (game.js:3964).",
    "base": "{label}",
}


def reason_for(candidate: Candidate, bn: dict | None) -> str:
    if not candidate.components:
        return candidate.action.label
    dominant = max(candidate.components, key=lambda k: candidate.components[k])
    template = REASON_TEMPLATES.get(dominant, "{label}")
    return template.format(label=candidate.action.label,
                           res=(bn or {}).get("resource") or "?")
