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
from . import actions
from .records import Candidate
from .safety import RESERVE_COMFORT_SECONDS

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
    "smelter": "iron",
    "quarry": "minerals",
}
HOUSING_BUILDINGS = {"hut", "logHouse", "mansion"}
STORAGE_BUILDINGS = {"barn", "warehouse", "harbor"}
# Gebäude, die der generische Ökonomie-Score in M1 überhaupt anfasst:
ECONOMY_WHITELIST = (set(BUILDING_PRODUCES) | HOUSING_BUILDINGS | STORAGE_BUILDINGS
                     | {"workshop", "unicornPasture", "amphitheatre", "tradepost", "temple"})

# Craft-Rezepte zur Cap-Verlust-Vermeidung: Input-Ressource -> Craft-Name.
CAP_RELIEF_CRAFTS = {
    "wood": "beam",
    "minerals": "slab",
    "iron": "plate",
    "culture": "manuscript",
}

WAIT_SCORE = 0.01


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


def _target_prices(snap: dict, target: dict | None) -> list[dict] | None:
    if not target:
        return None
    if target["kind"] == "build":
        b = A.building(snap, target["name"])
        return b["prices"] if b else None
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
    return None


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
    return None


# ================================================================ Kandidaten

def generate(snap: dict, meta_view, safety_result) -> tuple[list[Candidate], dict | None]:
    """Erzeugt alle Kandidaten inkl. Scores; gibt (candidates, bottleneck) zurück."""
    target = meta_view.active.target if meta_view.active else None
    bn = bottleneck_info(snap, target)
    cands: list[Candidate] = []
    blocked = safety_result.blocked_types
    reserved = _reserved_resource(snap, bn)

    _milestone_candidate(snap, target, bn, cands, blocked)
    _job_candidates(snap, bn, cands)
    _gather_candidates(snap, target, bn, cands)
    _research_candidates(snap, target, cands)
    _building_candidates(snap, target, bn, cands, blocked, reserved)
    _upgrade_candidates(snap, cands)
    _hunt_candidate(snap, cands)
    _craft_candidates(snap, target, bn, cands)
    _trade_candidates(snap, bn, cands)
    _praise_candidate(snap, cands)
    _festival_candidate(snap, cands)
    _wait_candidate(snap, bn, cands, meta_view)

    # Deterministisch sortieren: Score absteigend, dann Action-ID (C.2).
    cands.sort(key=lambda c: (-c.score, c.action.id))
    return cands, bn


def _reserved_resource(snap: dict, bn: dict | None) -> str | None:
    """Opportunitätskosten-Regel (Spec 10.2, vereinfacht):

    Ist der Engpass nur über eine Konversion lösbar (z. B. Wood ganz früh
    ausschließlich über „Refine catnip", solange es keine Woodcutter gibt),
    dann ist die Input-Ressource der Konversion reserviert — Ökonomie-Käufe,
    die sie verbrauchen, würden den Engpass verlängern und werden bestraft.
    """
    if bn and bn.get("resource") == "wood" and A.job_count(snap, "woodcutter") == 0 \
            and A.res_rate(snap, "wood") <= 0.001:
        return "catnip"
    return None


# ---------------------------------------------------------------- Meilenstein

def _milestone_candidate(snap, target, bn, cands, blocked) -> None:
    obj = _target_obj(snap, target)
    if not obj or not target:
        return
    prices = _target_prices(snap, target)
    if prices is None:
        return

    if target["kind"] == "build":
        act = actions.buy_building(target["name"], obj["label"], obj["val"])
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
        act = actions.buy_perk(target["name"], obj.get("label") or target["name"])
    else:
        act = actions.research(target["name"], obj["label"])

    if A.affordable(snap, prices):
        cands.append(Candidate(act, 3.0, {"milestone": 3.0}))
    else:
        eta = bn.get("etaSeconds") if bn else None
        miss = ", ".join(f"{m['missing']:.0f} {m['name']}" for m in (bn or {}).get("missing", []))
        reason = f"noch nicht bezahlbar: fehlen {miss} (~{fmt_duration(eta)})"
        if bn and bn.get("capBlocked"):
            reason = f"Cap von {bn['capBlocked']} blockiert das Ziel — Storage nötig (11.3 A)"
        cands.append(Candidate(act, 0.0, {"milestone": 0.0}, feasible=False,
                               reject_reason=reason, eta_seconds=eta))


# ---------------------------------------------------------------- Jobs

def _job_candidates(snap, bn, cands) -> None:
    village = snap.get("village", {})
    free = village.get("freeKittens", 0)
    food = snap.get("derived", {}).get("food", {})
    reserve = food.get("reserveSeconds")

    if free <= 0:
        _job_rebalance_candidate(snap, bn, cands, village, reserve)
        return

    # Food zuerst stabilisieren, wenn Reserve unter Komfortniveau:
    if reserve is not None and reserve < RESERVE_COMFORT_SECONDS and A.job_unlocked(snap, "farmer"):
        cands.append(Candidate(
            actions.assign_job("farmer", "Farmer", 1), 2.6,
            {"jobValue": 1.6, "safety": 1.0},
        ))
        return

    # Sonst: Job, der den Engpass produziert; Fallback-Prioritätsliste.
    job = None
    src = "Engpass"
    if bn and bn.get("resource"):
        job = RESOURCE_JOB.get(bn["resource"])
    if not job or not A.job_unlocked(snap, job):
        src = "Basispriorität"
        for j in ("woodcutter", "farmer", "scholar", "miner", "hunter"):
            if A.job_unlocked(snap, j):
                job = j
                break
    if job:
        label = next((j["title"] for j in village.get("jobs", []) if j["name"] == job), job)
        cands.append(Candidate(
            actions.assign_job(job, label, 1), 2.4,
            {"jobValue": 2.4},
        ))
        if src == "Engpass":
            cands[-1].components["bottleneck"] = 0.0  # nur Anzeige-Marker


def _job_rebalance_candidate(snap, bn, cands, village, reserve) -> None:
    """Lokale Tauschoperation (Spec 12.2 Schritt 7): Der Engpass-Job ist
    komplett unbesetzt und es gibt keine freien Kitten → ein Kitten aus dem
    größten anderen Job umschulen. `job_count == 0` verhindert Thrashing."""
    if not bn or not bn.get("resource"):
        return
    job = RESOURCE_JOB.get(bn["resource"])
    if not job or not A.job_unlocked(snap, job) or A.job_count(snap, job) > 0:
        return
    food_tight = reserve is not None and reserve < RESERVE_COMFORT_SECONDS
    donors = [j for j in village.get("jobs", [])
              if j["name"] != job and j["value"] > 0
              and not (j["name"] == "farmer" and food_tight)]
    if not donors:
        return
    biggest = max(donors, key=lambda j: (j["value"], j["name"]))
    label = next((j["title"] for j in village.get("jobs", []) if j["name"] == job), job)
    cands.append(Candidate(
        actions.shift_job(biggest["name"], job, label, 1), 2.2,
        {"jobValue": 1.2, "bottleneck": 1.0},
    ))


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

    # Refine: Holz aus Catnip, solange es keine/kaum Woodcutter gibt.
    wood_needed = bn and bn.get("resource") == "wood"
    catnip_val = A.res_value(snap, "catnip")
    if wood_needed and A.job_count(snap, "woodcutter") == 0 and catnip_val >= 100:
        missing_wood = next((m["missing"] for m in bn.get("missing", []) if m["name"] == "wood"), 0)
        batch = max(1, min(5, int(catnip_val // 100), math.ceil(missing_wood)))
        cands.append(Candidate(actions.refine_catnip(batch), 2.0,
                               {"bottleneck": 2.0}))


# ---------------------------------------------------------------- Forschung

def _research_candidates(snap, target, cands) -> None:
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
        cands.append(Candidate(actions.research(t["name"], t["label"]), 1.9,
                               {"unlock": 1.9}))


# ---------------------------------------------------------------- Gebäude

def _building_candidates(snap, target, bn, cands, blocked, reserved=None) -> None:
    target_name = target.get("name") if target and target["kind"] == "build" else None
    prices_target = _target_prices(snap, target)
    cap_blocked_res = A.cap_blocks(snap, prices_target) if prices_target else None

    for b in snap.get("buildings", []):
        name = b["name"]
        if name == target_name or not b["unlocked"] or name not in ECONOMY_WHITELIST:
            continue
        if not A.affordable(snap, b["prices"]):
            continue

        comp: dict[str, float] = {}
        if name in STORAGE_BUILDINGS:
            # Storage-Regel 11.3 A: nur wenn ein Cap das Meilenstein-Ziel blockiert
            # (oder der Engpass kurz vor Cap-Verlust steht).
            relief = _storage_relieves(snap, name, cap_blocked_res)
            if relief:
                comp["storage"] = 2.2
            else:
                near_cap = _bottleneck_near_cap(snap, bn)
                if near_cap:
                    comp["storage"] = 1.0
                else:
                    continue  # Storage ohne Bedarf ist unzulässig (11.3)
        elif name in HOUSING_BUILDINGS:
            if "housing" in blocked:
                cands.append(Candidate(
                    actions.buy_building(name, b["label"], b["val"]), 0.0,
                    {"housing": 0.0}, feasible=False,
                    reject_reason="Food-Sicherheit blockiert Housing (I-01)"))
                continue
            comp["housing"] = 1.6
        elif BUILDING_PRODUCES.get(name) and bn and BUILDING_PRODUCES[name] == bn.get("resource"):
            comp["bottleneck"] = 1.8   # produziert genau den Engpass
        elif name == "workshop" and A.bld_val(snap, "workshop") == 0:
            comp["unlock"] = 1.7       # erste Werkstatt schaltet Crafts frei
        elif name == "amphitheatre" and snap.get("village", {}).get("happiness", 1.0) < 1.0:
            comp["happiness"] = 1.2    # unglückliche Kitten produzieren weniger
        else:
            comp["economy"] = 0.6      # generischer Ausbau

        # Opportunitätskosten: Kauf verbraucht die für den Engpass reservierte
        # Ressource (z. B. Catnip, das eigentlich zu Holz veredelt werden muss).
        # Die Strafe drückt generische Käufe unter Null — und Aktionen mit
        # negativem NetValue werden nie ausgeführt (Kaufregel 10.3).
        if reserved and any(p["name"] == reserved for p in b["prices"]) \
                and "bottleneck" not in comp and "storage" not in comp:
            comp["opportunity"] = -0.7

        score = sum(comp.values())
        cands.append(Candidate(actions.buy_building(name, b["label"], b["val"]), score, comp))


def _storage_relieves(snap, storage_name, cap_blocked_res) -> bool:
    if not cap_blocked_res:
        return False
    relief_map = {
        "barn": {"catnip", "wood", "minerals", "iron"},
        "warehouse": {"wood", "minerals", "iron"},
        "harbor": {"catnip", "wood", "minerals", "iron", "coal", "gold"},
    }
    return cap_blocked_res in relief_map.get(storage_name, set())


def _bottleneck_near_cap(snap, bn) -> bool:
    if not bn or not bn.get("resource"):
        return False
    r = A.resource(snap, bn["resource"])
    if not r or not r.get("maxValue"):
        return False
    return r["value"] / r["maxValue"] > 0.9


# ---------------------------------------------------------------- Upgrades

def _upgrade_candidates(snap, cands) -> None:
    ups = [u for u in snap.get("workshop", {}).get("upgrades", [])
           if u["unlocked"] and not u["researched"] and A.affordable(snap, u["prices"])]
    ups.sort(key=lambda u: (sum(p["val"] for p in u["prices"]), u["name"]))
    for u in ups[:2]:
        cands.append(Candidate(actions.buy_upgrade(u["name"], u["label"]), 1.4,
                               {"unlock": 1.4}))


# ---------------------------------------------------------------- Jagd

def _hunt_candidate(snap, cands) -> None:
    mp = A.resource(snap, "manpower")
    if not mp or not A.job_unlocked(snap, "hunter") and A.job_count(snap, "hunter") == 0:
        # Jagd lohnt erst mit Catpower-Produktion
        if not mp or mp["value"] < 100:
            return
    if mp.get("maxValue", 0) <= 0:
        return
    fill = mp["value"] / mp["maxValue"]
    if fill >= 0.85 and mp["value"] >= 100:
        comp = {"capLoss": 1.5}
        if A.res_value(snap, "furs") <= 0:
            comp["economy"] = 0.3   # erster Pelz = Happiness-Schub
        cands.append(Candidate(actions.hunt(), sum(comp.values()), comp))


# ---------------------------------------------------------------- Crafts

def _craft_candidates(snap, target, bn, cands) -> None:
    prices_target = _target_prices(snap, target) or []
    needed_crafts = {p["name"] for p in prices_target} & {"beam", "slab", "plate", "scaffold"}

    for input_res, craft_name in CAP_RELIEF_CRAFTS.items():
        recipe = A.craft_recipe(snap, craft_name)
        if not recipe:
            continue
        r = A.resource(snap, input_res)
        if not r or r.get("maxValue", 0) <= 0:
            continue
        price = next((p["val"] for p in recipe["prices"] if p["name"] == input_res), None)
        if not price:
            continue

        comp: dict[str, float] = {}
        batch = 0
        # a) Meilenstein braucht das Craftprodukt:
        if craft_name in needed_crafts:
            need = next((p["val"] for p in prices_target if p["name"] == craft_name), 0)
            have = A.res_value(snap, craft_name)
            gap = max(0.0, need - have)
            if gap > 0 and r["value"] >= price:
                batch = max(1, min(10, int(r["value"] // price), math.ceil(gap)))
                comp["milestone"] = 2.0
        # b) Cap-Verlust am Input vermeiden (11.4):
        elif r["value"] / r["maxValue"] > 0.92 and r["value"] >= price:
            batch = max(1, min(10, int((r["value"] * 0.3) // price)))
            comp["capLoss"] = 1.6

        if batch > 0:
            cands.append(Candidate(actions.craft(craft_name, recipe["label"], batch),
                                   sum(comp.values()), comp))


# ---------------------------------------------------------------- Handel

# Fixkosten jedes Trades (zusätzlich zur rassespezifischen Ware):
TRADE_GOLD_COST = 15
TRADE_MANPOWER_COST = 50


def _trade_candidates(snap, bn, cands) -> None:
    diplo = snap.get("diplomacy", {})
    races = diplo.get("races", [])
    gold = A.res_value(snap, "gold")
    manpower = A.res_value(snap, "manpower")

    # Kundschafter: neue Handelspartner sind ein Unlock (Optionswert).
    if diplo.get("undiscovered") and manpower >= 1000:
        cands.append(Candidate(actions.explore(), 1.6, {"unlock": 1.6}))

    if not races:
        return

    for race in races:
        # TradeValue-light (Spec 14.1): Handel nur, wenn die Rasse den
        # aktuellen Engpass liefert. EV-Rechnung folgt mit späterem Ausbau.
        sells_bottleneck = bn and bn.get("resource") and any(
            s["name"] == bn["resource"] for s in race.get("sells", []))
        if not sells_bottleneck:
            continue
        batch = int(min(gold // TRADE_GOLD_COST, manpower // TRADE_MANPOWER_COST, 5))
        for p in race.get("buys", []):
            have = A.res_value(snap, p["name"])
            batch = int(min(batch, have // p["val"])) if p["val"] else batch
        if batch >= 1:
            cands.append(Candidate(
                actions.trade(race["name"], race["title"], batch), 1.7,
                {"bottleneck": 1.7},
            ))

    # Gold am Cap ist verschenkter Handelsspielraum (Cap-Regel 11.4):
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
            cands.append(Candidate(
                actions.trade(race["name"], race["title"], batch), 1.1,
                {"capLoss": 1.1},
            ))


# ---------------------------------------------------------------- Religion / Festival

def _praise_candidate(snap, cands) -> None:
    # Faith am Cap verfällt — Praise wandelt sie in dauerhaften Worship (15.1).
    faith = A.resource(snap, "faith")
    if not faith or faith.get("maxValue", 0) <= 0:
        return
    if faith["value"] / faith["maxValue"] >= 0.95:
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


# ---------------------------------------------------------------- WAIT

def _wait_candidate(snap, bn, cands, meta_view) -> None:
    if bn and bn.get("resource"):
        miss = ", ".join(f"{m['missing']:.0f} {m['name']}" for m in bn.get("missing", []))
        reason = (f"Warte auf {bn['resource']} für „{meta_view.objective_label}“: "
                  f"fehlen {miss} (~{fmt_duration(bn.get('etaSeconds'))})")
        wake = "Replan bei Bezahlbarkeit, neuem Unlock oder Kitten-Ankunft"
    else:
        reason = "Kein Kandidat mit positivem Wert — beobachte Produktion"
        wake = "Replan beim nächsten Ereignis"
    cands.append(Candidate(actions.wait(reason, wake), WAIT_SCORE, {"base": WAIT_SCORE}))


# ================================================================ Begründung

REASON_TEMPLATES = {
    "safety": "Sicherheitsinvariante: {label} schützt die Food-Versorgung.",
    "milestone": "{label} bringt den aktiven Meilenstein direkt voran.",
    "bottleneck": "{label} löst den aktuellen Engpass ({res}).",
    "jobValue": "Freie Kitten sind ungenutzte Produktion — {label}.",
    "unlock": "{label} schaltet neue Möglichkeiten frei (Unlock-first-Regel).",
    "housing": "{label}: mehr Kitten = mehr Produktion (Food-Reserve ist sicher).",
    "storage": "{label}: das aktuelle Cap blockiert den Fortschritt (Storage-Regel A).",
    "capLoss": "{label} verhindert Produktionsverlust am Ressourcen-Cap.",
    "economy": "{label} ist eine günstige Ökonomie-Investition.",
    "happiness": "{label}: Happiness wirkt als Multiplikator auf die gesamte Produktion.",
    "base": "{label}",
}


def reason_for(candidate: Candidate, bn: dict | None) -> str:
    if not candidate.components:
        return candidate.action.label
    dominant = max(candidate.components, key=lambda k: candidate.components[k])
    template = REASON_TEMPLATES.get(dominant, "{label}")
    return template.format(label=candidate.action.label,
                           res=(bn or {}).get("resource") or "?")
