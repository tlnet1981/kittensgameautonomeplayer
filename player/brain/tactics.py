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
from . import actions, shadow
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
# Gebäude, die der generische Ökonomie-Score überhaupt anfasst:
ECONOMY_WHITELIST = (set(BUILDING_PRODUCES) | HOUSING_BUILDINGS | STORAGE_BUILDINGS
                     | ENERGY_PRODUCERS
                     | {"workshop", "unicornPasture", "amphitheatre", "tradepost",
                        "temple", "factory", "chapel", "aqueduct", "ziggurat",
                        "chronosphere"})

# Craft-Rezepte zur Cap-Verlust-Vermeidung: Input-Ressource -> Craft-Name.
CAP_RELIEF_CRAFTS = {
    "wood": "beam",
    "minerals": "slab",
    "iron": "plate",
    "culture": "manuscript",
}

WAIT_SCORE = 0.01

# Reine Anzeige-Komponenten (Sekundenwerte der Schattenpreis-Rechnung) —
# sie fließen NICHT additiv in den Score ein; netValue geht normiert ein.
SHADOW_INFO_KEYS = ("costTime", "benefitTime", "netValue", "jobScore")
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
    additiv; netValue geht normiert ein (Kaufregel 10.3, NetValue primär)."""
    s = sum(v for k, v in comp.items() if k not in SHADOW_INFO_KEYS)
    if "netValue" in comp:
        s += max(-NET_VALUE_CLAMP, min(NET_VALUE_CLAMP,
                                       comp["netValue"] / NET_VALUE_SCALE))
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
    if target["kind"] == "space_program":
        for p in snap.get("space", {}).get("programs", []):
            if p["name"] == target["name"]:
                return p["prices"]
        return None
    if target["kind"] == "religion_upgrade":
        for u in snap.get("religion", {}).get("upgrades", []):
            if u["name"] == target["name"] and not (u["noStackable"] and (u["on"] or u["val"])):
                return u["prices"]
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
    if target["kind"] == "space_program":
        return next((p for p in snap.get("space", {}).get("programs", [])
                     if p["name"] == target["name"]), None)
    if target["kind"] == "religion_upgrade":
        return next((u for u in snap.get("religion", {}).get("upgrades", [])
                     if u["name"] == target["name"]), None)
    return None


# ================================================================ Kandidaten

def generate(snap: dict, meta_view, safety_result) -> tuple[list[Candidate], dict | None]:
    """Erzeugt alle Kandidaten inkl. Scores; gibt (candidates, bottleneck) zurück."""
    target = meta_view.active.target if meta_view.active else None
    bn = bottleneck_info(snap, target)
    cands: list[Candidate] = []
    blocked = safety_result.blocked_types
    banking = _kitten_banking_mode(snap, bn)
    reserved = _reserved_resource(snap, bn, banking)

    # Schattenpreise EINMAL pro Zyklus am aktiven Meilenstein-Ziel (10.2);
    # ohne Preisvektor bleiben die Dicts leer → überall Fallback-Heuristik.
    goal_prices = _target_prices(snap, target)
    lam = shadow.shadow_prices(snap, goal_prices) if goal_prices else {}
    lam_rate = shadow.rate_shadow_prices(snap, goal_prices) if goal_prices else {}
    horizon = shadow.run_horizon(snap)

    _milestone_candidate(snap, target, bn, cands, blocked)
    _job_candidates(snap, bn, cands, lam_rate)
    _gather_candidates(snap, target, bn, cands)
    _research_candidates(snap, target, cands, lam)
    _building_candidates(snap, target, bn, cands, blocked, reserved, banking,
                         lam, horizon)
    if banking:
        _banking_candidates(snap, cands)
    _upgrade_candidates(snap, cands, lam)
    _hunt_candidate(snap, cands)
    _craft_candidates(snap, target, bn, cands, lam)
    _trade_candidates(snap, bn, cands)
    _praise_candidate(snap, cands)
    _festival_candidate(snap, cands)
    _religion_candidates(snap, target, cands)
    _space_building_candidates(snap, bn, cands)
    _time_candidates(snap, cands)
    _wait_candidate(snap, bn, cands, meta_view)

    # Deterministisch sortieren: Score absteigend, dann Action-ID (C.2).
    cands.sort(key=lambda c: (-c.score, c.action.id))
    return cands, bn


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
    elif target["kind"] == "space_program":
        act = actions.space_program(target["name"], obj.get("label") or target["name"])
    elif target["kind"] == "religion_upgrade":
        act = actions.buy_religion_upgrade(target["name"], obj.get("label") or target["name"])
    else:
        act = actions.research(target["name"], obj["label"])

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


# ---------------------------------------------------------------- Jobs

def _job_candidates(snap, bn, cands, lam_rate=None) -> None:
    village = snap.get("village", {})
    free = village.get("freeKittens", 0)
    food = snap.get("derived", {}).get("food", {})
    food_tight = food.get("status", "ok") != "ok"

    if free <= 0:
        _job_rebalance_candidate(snap, bn, cands, village, food_tight, lam_rate)
        return

    # Mindestfarmer-/Food-Leitplanke hat VORRANG vor jeder λ-Bewertung:
    if food_tight and A.job_unlocked(snap, "farmer"):
        cands.append(Candidate(
            actions.assign_job("farmer", "Farmer", 1), 2.6,
            {"jobValue": 1.6, "safety": 1.0},
        ))
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


def _job_rebalance_candidate(snap, bn, cands, village, food_tight,
                             lam_rate=None) -> None:
    """Lokale Tauschoperation (Spec 12.2 Schritt 7): Der Engpass-Job ist
    komplett unbesetzt und es gibt keine freien Kitten → ein Kitten aus dem
    größten anderen Job umschulen. `job_count == 0` verhindert Thrashing
    (höchstens ein Tausch-Kandidat pro Zyklus). Mit λ-Daten zusätzlich:
    der Tausch muss sich lohnen — JobScore(Ziel) − JobScore(Spender) >
    REBALANCE_GAIN_MIN; ohne λ-Daten bleibt das bisherige Verhalten."""
    if not bn or not bn.get("resource"):
        return
    job = RESOURCE_JOB.get(bn["resource"])
    if not job or not A.job_unlocked(snap, job) or A.job_count(snap, job) > 0:
        return
    donors = [j for j in village.get("jobs", [])
              if j["name"] != job and j["value"] > 0
              and not (j["name"] == "farmer" and food_tight)]
    if not donors:
        return
    biggest = max(donors, key=lambda j: (j["value"], j["name"]))
    comp = {"jobValue": 1.2, "bottleneck": 1.0}
    if lam_rate:
        gain = shadow.job_score(snap, job, lam_rate)
        loss = shadow.job_score(snap, biggest["name"], lam_rate)
        if gain - loss <= REBALANCE_GAIN_MIN:
            return   # Tausch lohnt sich nicht (Anti-Thrashing)
        comp["jobScore"] = gain - loss         # Sekundenwert, nur Anzeige
    label = next((j["title"] for j in village.get("jobs", []) if j["name"] == job), job)
    cands.append(Candidate(
        actions.shift_job(biggest["name"], job, label, 1), 2.2, comp,
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
        comp = {"bottleneck": 2.0}
        _apply_food_risk(snap, comp, [{"name": "catnip", "val": 100 * batch}])
        cands.append(Candidate(actions.refine_catnip(batch), sum(comp.values()), comp))


# ---------------------------------------------------------------- Forschung

def _research_candidates(snap, target, cands, lam=None) -> None:
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
        # die Payback-Regel gesperrt (Spec 10.4), der Score bleibt fix:
        ct = shadow.cost_time(t["prices"], lam) if lam else 0.0
        if ct > 1e-9:
            comp["costTime"] = ct
        cands.append(Candidate(actions.research(t["name"], t["label"]), 1.9, comp))


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
                         banking=False, lam=None, horizon=None) -> None:
    target_name = target.get("name") if target and target["kind"] == "build" else None
    prices_target = _target_prices(snap, target)
    cap_blocked_res = A.cap_blocks(snap, prices_target) if prices_target else None
    horizon = horizon if horizon is not None else shadow.HORIZON_MIN

    for b in snap.get("buildings", []):
        name = b["name"]
        if name == target_name or not b["unlocked"] or name not in ECONOMY_WHITELIST:
            continue
        if not A.affordable(snap, b["prices"]):
            continue

        energy_deficit = snap.get("derived", {}).get("energy", {}).get("balance", 0) < 0

        comp: dict[str, float] = {}
        if name in ENERGY_PRODUCERS and energy_deficit:
            # Energie-Defizit drosselt Produktion global — Erzeuger vorziehen (16.4).
            comp["energy"] = 2.0
        elif name in STORAGE_BUILDINGS:
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
            comp, reject = _housing_eval(snap, name, b, blocked)
            if reject:
                cands.append(Candidate(
                    actions.buy_building(name, b["label"], b["val"]), 0.0,
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
                    actions.buy_building(name, b["label"], b["val"]), 0.0,
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
            comp["economy"] = 1.2      # Carryover über Resets (Spec 19.1)
        else:
            comp["economy"] = 0.6      # generischer Ausbau

        # --- Schattenpreis-Ökonomie (Spec 10.2–10.4) für Produktionsgebäude:
        # Sekundenwerte als transparente Komponenten; NetValue fließt über
        # _score normiert ein. Safety-/Unlock-/Energie-/Storage-/Housing-
        # Käufe und der Banking-Modus bleiben unberührt (Vorrangregeln).
        if lam and not banking and name in BUILDING_PRODUCES \
                and not any(k in comp for k in ("storage", "energy", "housing")):
            rate_delta = _building_rate_delta(snap, name, BUILDING_PRODUCES[name])
            cost_t = shadow.cost_time(b["prices"], lam)
            ben_t = shadow.benefit_time(rate_delta, lam, horizon)
            if cost_t > 1e-9 or ben_t > 1e-9:
                comp["costTime"] = cost_t
                comp["benefitTime"] = ben_t
                comp["netValue"] = shadow.net_value(ben_t, cost_t)
                # Payback-Gate (10.4): NUR reine Produktions-/Ökonomiekäufe.
                # Engpasslöser gelten als zwingende Dependency des Ziels.
                if "bottleneck" not in comp and cost_t > 1e-9:
                    pb = shadow.payback(cost_t, ben_t / horizon)
                    if pb > horizon:
                        cands.append(Candidate(
                            actions.buy_building(name, b["label"], b["val"]),
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
        cands.append(Candidate(actions.buy_building(name, b["label"], b["val"]), score, comp))


def _building_rate_delta(snap, name: str, produces: str) -> dict[str, float]:
    """Geschätzter Produktionszuwachs des nächsten Exemplars (Näherung):
    - field: bekannte Basisrate × aktueller Saisonmodifikator
    - pasture: senkt den Verbrauch um 0,5 % des Catnip-Bedarfs
    - sonst: beobachtete Netto-Rate / Gebäudeanzahl; erstes Exemplar ohne
      Bestandsdaten ≈ +10 % der laufenden Produktion (Ratio-Gebäude).
    Ohne Rate: leer → benefit_time = 0, Fallback greift."""
    if name == "field":
        mod = snap.get("calendar", {}).get("currentCatnipModifier", 1.0) or 1.0
        return {"catnip": CATNIP_PER_FIELD_PER_SEC * mod}
    if name == "pasture":
        demand = snap.get("derived", {}).get("food", {}).get("demandPerSec", 0.0)
        return {"catnip": 0.005 * demand} if demand > 0 else {}
    val = A.bld_val(snap, name)
    rate = A.res_rate(snap, produces)
    if rate <= 0:
        return {}
    if val >= 1:
        return {produces: rate / val}
    return {produces: rate * 0.1}


def _apply_food_risk(snap, comp: dict, prices: list[dict]) -> None:
    """foodRisk-Komponente (I-01): Bei kritischer Winter-Projektion drückt
    ein Catnip-Preis den Kandidaten unter Null (Kaufregel 10.3 filtert ihn)."""
    if snap.get("derived", {}).get("food", {}).get("status") != "critical":
        return
    if any(p["name"] == "catnip" for p in prices):
        comp["foodRisk"] = -3.0


# Housing-Kapazitätszuwachs pro Gebäude (Spec 12.1 KittenArrival-Basis):
HOUSING_CAPACITY = {"hut": 2, "logHouse": 1, "mansion": 1}


def _housing_eval(snap, name: str, b: dict, blocked) -> tuple[dict, str | None]:
    """HousingValue-Logik nach Spec 12.1 (deterministisch vereinfacht).

    Liefert (Score-Komponenten, Ablehnungsgrund|None). Regeln:
    1. Bedarfs-Gate: nur bauen, wenn die Kapazität voll ist — ungenutzte
       Plätze haben keinen Produktionswert (12.1). maxKittens == 0 gilt
       als voll → die erste Hütte entsteht dynamisch ohne Meilenstein.
    2. Food-Gate: die Saisonprojektion muss die MEHRLAST der neuen Kitten
       tragen (ersetzt die frühere Pauschalsperre).
    3. Score: Basis 1.6 (Kitten = Arbeiter am Engpass) + 0.4 Paragon-
       Grenzwert ab 68 Kitten (ab 70 zählt jedes Kitten beim Reset).
    """
    village = snap.get("village", {})
    kittens = village.get("kittens", 0)
    max_kittens = village.get("maxKittens", 0)
    comp: dict[str, float] = {"housing": 1.6}
    if kittens >= 68:
        comp["paragon"] = 0.4

    # 1. Bedarfs-Gate
    if max_kittens > kittens:
        return comp, (f"ungenutzte Housing-Kapazität ({kittens}/{max_kittens}) — "
                      f"neue Plätze haben keinen Wert (12.1)")

    # 2. Food-Gate über die Saisonprojektion
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


def _bottleneck_near_cap(snap, bn) -> bool:
    if not bn or not bn.get("resource"):
        return False
    r = A.resource(snap, bn["resource"])
    if not r or not r.get("maxValue"):
        return False
    return r["value"] / r["maxValue"] > 0.9


# ---------------------------------------------------------------- Upgrades

def _upgrade_candidates(snap, cands, lam=None) -> None:
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
        cands.append(Candidate(actions.buy_upgrade(u["name"], u["label"]), 1.4, comp))


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
                              lam=lam)

    # b) Cap-Verlust am Input vermeiden (11.4):
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
            cands.append(Candidate(actions.craft(craft_name, recipe["label"], batch),
                                   1.6, {"capLoss": 1.6}))


def _craft_toward(snap, craft_name: str, gap: float, cands, depth: int,
                  seen: set[str], lam=None) -> None:
    """Rekursiver Abstieg im Craft-Graphen (max. Tiefe 4)."""
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
        score = max(0.5, 2.0 - 0.1 * depth)
        comp = {"milestone": score}
        # Sekundenwerte transparent machen (Score bleibt fix — Crafts der
        # Meilenstein-Kaskade sind zwingende Dependencies, Spec 10.4):
        if lam:
            cost_t = shadow.cost_time(
                [{"name": q["name"], "val": q["val"] * batch}
                 for q in recipe["prices"]], lam)
            ben_t = lam.get(craft_name, 0.0) * batch
            if cost_t > 1e-9 or ben_t > 1e-9:
                comp["costTime"] = cost_t
                comp["benefitTime"] = ben_t
                comp["netValue"] = shadow.net_value(ben_t, cost_t)
        cands.append(Candidate(actions.craft(craft_name, recipe["label"], batch),
                               score, comp))
        return
    # Inputs fehlen → craftbare Inputs eine Ebene tiefer anstoßen
    for m in missing:
        if A.craft_recipe(snap, m["name"]) is not None:
            _craft_toward(snap, m["name"], m["missing"], cands, depth + 1, seen,
                          lam=lam)


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
            actions.buy_religion_upgrade(u["name"], u["label"]),
            sum(comp.values()), comp))

    # Ziggurat-/Unicorn-Kette (Spec 15.3, vereinfacht bewertet):
    for z in religion.get("ziggurat", []):
        if not z["unlocked"] or not A.affordable(snap, z["prices"]):
            continue
        cands.append(Candidate(
            actions.buy_religion_upgrade(z["name"], z["label"], ziggurat=True),
            1.0, {"economy": 1.0}))

    # Unicorns opfern, sobald ein Batch voll ist und ein Ziggurat steht:
    if A.bld_val(snap, "ziggurat") >= 1 \
            and A.res_value(snap, "unicorns") >= SACRIFICE_UNICORN_COST:
        cands.append(Candidate(actions.sacrifice_unicorns(), 1.5, {"economy": 1.5}))


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


def _space_building_candidates(snap, bn, cands) -> None:
    for planet in snap.get("space", {}).get("planets", []):
        for b in planet.get("buildings", []):
            if not b["unlocked"] or not A.affordable(snap, b["prices"]):
                continue
            comp: dict[str, float] = {}
            produces = SPACE_BUILDING_PRODUCES.get(b["name"])
            if bn and produces and produces == bn.get("resource"):
                comp["bottleneck"] = 1.8
            else:
                comp["economy"] = 0.8   # Space-Ausbau ist fast immer Fortschritt
            act = actions.Action(
                id=f"space_bld:{b['name']}", type="BUY_BUILDING",
                label=f"Baue {b['label']} ({planet['label']}, Nr. {b['val'] + 1})",
                exec_spec={"kind": "click_button", "tab": "Space",
                           "panel": planet["label"], "title": b["label"], "batch": 1},
                expected=f"{b['label']} auf {b['val'] + 1}",
            )
            cands.append(Candidate(act, sum(comp.values()), comp))


# ---------------------------------------------------------------- Handel

# Fixkosten jedes Trades (zusätzlich zur rassespezifischen Ware):
TRADE_GOLD_COST = 15
TRADE_MANPOWER_COST = 50


def _trade_candidates(snap, bn, cands) -> None:
    diplo = snap.get("diplomacy", {})
    races = diplo.get("races", [])
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
                    actions.trade("leviathans", race["title"], batch), 1.7,
                    {"economy": 1.7}))
            continue
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
            comp = {"bottleneck": 1.7}
            _apply_food_risk(snap, comp, race.get("buys", []))
            cands.append(Candidate(
                actions.trade(race["name"], race["title"], batch),
                sum(comp.values()), comp,
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
    if faith["value"] / faith["maxValue"] < 0.95:
        return
    # Aber: Faith ist auch Kaufwährung der Religion-Upgrades. Solange ein
    # erreichbares (Cap reicht) Upgrade offen ist, wird gespart statt gepriesen.
    cap = faith["maxValue"]
    for u in snap.get("religion", {}).get("upgrades", []):
        if not u["unlocked"] or (u["noStackable"] and (u["on"] or u["val"])):
            continue
        price = next((p["val"] for p in u["prices"] if p["name"] == "faith"), None)
        if price is not None and price <= cap:
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


# ---------------------------------------------------------------- Time (M6)

HEAT_PER_SHATTER = 10   # time.js:1254 (5 mit 1000-Years-Challenge)


def _time_candidates(snap, cands) -> None:
    time_state = snap.get("time", {})

    # Chronoforge-Ausbau (Resource Retrieval, Furnaces, Batteries):
    for u in time_state.get("chronoforge", []):
        if not u["unlocked"] or not A.affordable(snap, u["prices"]):
            continue
        # RR ist der Kern der Shatter-Engine (Spec 17.2) — höher gewichten:
        comp = {"economy": 1.3} if u["name"] == "ressourceRetrieval" else {"economy": 0.8}
        cands.append(Candidate(actions.Action(
            id=f"chronoforge:{u['name']}", type="BUY_UPGRADE",
            label=f"Chronoforge: {u['label']}",
            exec_spec={"kind": "click_button", "tab": "Time", "title": u["label"], "batch": 1},
            expected=f"{u['label']} auf {u['val'] + 1}",
        ), sum(comp.values()), comp))

    # Cryochambers (Kitten-Carryover über Resets, Spec 19):
    for u in time_state.get("voidspace", []):
        if u["name"] != "cryochambers" or not u["unlocked"] \
                or not A.affordable(snap, u["prices"]):
            continue
        cands.append(Candidate(actions.Action(
            id="voidspace:cryochambers", type="BUY_UPGRADE",
            label="Cryochamber bauen (Kitten-Carryover)",
            exec_spec={"kind": "click_button", "tab": "Time", "title": u["label"], "batch": 1},
            expected="Ein Kitten überlebt den nächsten Reset",
        ), 1.4, {"economy": 1.4}))

    # Konservative Shatter-Regel (Spec 17.5, Basisausbaustufe): nur mit
    # Resource-Retrieval-Infrastruktur und Heat-Spielraum.
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
    "energy": "{label}: das Energie-Defizit drosselt die Produktion (Invariante I-04).",
    "netValue": "{label} spart netto Zielzeit (Schattenpreis-Bewertung 10.2/10.3).",
    "benefitTime": "{label} beschleunigt das Ziel (Benefit in Ziel-Sekunden).",
    "costTime": "{label} kostet Ziel-Sekunden (Schattenpreis-Bewertung).",
    "jobScore": "{label} maximiert den Zielzeitgewinn pro Kitten (JobScore 12.2).",
    "base": "{label}",
}


def reason_for(candidate: Candidate, bn: dict | None) -> str:
    if not candidate.components:
        return candidate.action.label
    dominant = max(candidate.components, key=lambda k: candidate.components[k])
    template = REASON_TEMPLATES.get(dominant, "{label}")
    return template.format(label=candidate.action.label,
                           res=(bn or {}).get("resource") or "?")
