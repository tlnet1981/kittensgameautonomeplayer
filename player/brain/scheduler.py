"""Ereignisgetriebenes Replanning (Spielmechanik-Spec 21.1–21.3, 5.3).

Zwei Bausteine:

1. `next_wakeup`: wann lohnt sich der nächste Zyklus? Frühestes aus
   Saisonwechsel, halber Cap-/Depletion-Zeit und dem weichen Kontrollpunkt
   (21.2: min aus 30 s, 10 % Ziel-ETA, ½ nächste Cap-Zeit). Der Rückgabewert
   wird zum `replan_reason` des nächsten Zyklus.

2. `signature`/`classify_hard_trigger`: harte Trigger (21.1) durch Vergleich
   mit dem Vorzyklus — neue Unlocks, Cap erreicht, Saison-/Cycle-Wechsel,
   Kitten-Änderung, Aktionsfehler. Hart schlägt weich.

replan_reason-Struktur: {"type": "hard"|"soft", "source": str, "detail": str}.
Quellen (source): season | cap | eta | interval | safety | mismatch | unlock
| kitten | cycle | error — die letzten vier erweitern die Beispielliste der
Spec deterministisch (dokumentierte Näherung).
"""

from __future__ import annotations

import math

from player.state.derived import SECONDS_PER_DAY

# Klemmen des Weckintervalls: nie schneller als das Entscheidungsintervall
# (Zuschauer-Taktung), nie langsamer als der weiche Kontrollpunkt (21.2).
MAX_WAKEUP_S = 30.0


def next_wakeup(snap: dict, target_eta: float | None,
                decision_interval: float = 1.5) -> tuple[float, dict]:
    """(Schlafdauer in s, replan_reason des nächsten Zyklus).

    Fallbacks: ohne Snapshot/Daten bleibt es beim decision_interval
    ("interval"); Kitten-Ankunft nur, falls der Snapshot eine ETA liefert
    (village.nextKittenEtaSeconds — derzeit nicht im Reader, dokumentiert).
    """
    if not snap:
        return decision_interval, {"type": "soft", "source": "interval",
                                   "detail": "kein Snapshot — Basisintervall"}
    events: list[tuple[float, str, str]] = []

    # Saisonwechsel: Resttage der Saison × 2 s (Spielkonstante).
    cal = snap.get("calendar", {})
    days_per_season = float(cal.get("daysPerSeason", 100)) or 100.0
    day = float(cal.get("day", 0) or 0)
    season_rest = max(0.0, (days_per_season - day)) * SECONDS_PER_DAY
    if season_rest > 0:
        events.append((season_rest, "season",
                       f"Saisonwechsel in ~{season_rest:.0f}s"))

    # Nächste Cap-/Depletion-Zeit über alle Ressourcen (derived, Anhang D);
    # geweckt wird bei der HALBEN Zeit (21.2, ½ nächste Cap-Zeit).
    cap_t = math.inf
    cap_res = None
    for name, d in sorted(snap.get("derived", {}).get("resources", {}).items()):
        for t in (d.get("fillTime"), d.get("depletionTime")):
            if t is not None and 0 < t < cap_t:
                cap_t, cap_res = t, name
    if math.isfinite(cap_t):
        events.append((cap_t / 2.0, "cap",
                       f"½ Cap-/Depletion-Zeit von {cap_res} (~{cap_t:.0f}s)"))

    # Kitten-Ankunft, falls der Snapshot eine ETA liefert (Fallback: keine).
    kitten_eta = snap.get("village", {}).get("nextKittenEtaSeconds")
    if isinstance(kitten_eta, (int, float)) and kitten_eta > 0:
        events.append((float(kitten_eta), "kitten", "Kitten-Ankunft"))

    # Weicher Kontrollpunkt: 10 % der Ziel-ETA … maximal 30 s (21.2).
    if target_eta is not None and math.isfinite(target_eta) and target_eta > 0:
        events.append((0.1 * target_eta, "eta",
                       f"10 % der Ziel-ETA ({target_eta:.0f}s)"))
    events.append((MAX_WAKEUP_S, "interval", "periodischer Kontrollpunkt (30s)"))

    # Frühestes Ereignis, deterministischer Tie-Break über die Quelle:
    delay, source, detail = min(events, key=lambda e: (e[0], e[1]))
    delay = max(decision_interval, min(delay, MAX_WAKEUP_S))
    return delay, {"type": "soft", "source": source, "detail": detail}


# ---------------------------------------------------------------- Harte Trigger

def signature(snap: dict) -> dict:
    """Vergleichsbasis für die harte Trigger-Erkennung (21.1) — kompakt und
    deterministisch (nur Mengen/Skalare, keine Zeitstempel)."""
    caps_reached = set()
    for r in snap.get("resources", []):
        cap = r.get("maxValue", 0.0)
        if cap > 0 and r.get("value", 0.0) >= cap * 0.999:
            caps_reached.add(r["name"])
    return {
        "techs": {t["name"] for t in snap.get("science", {}).get("techs", [])
                  if t.get("researched")},
        "unlocked_techs": {t["name"] for t in snap.get("science", {}).get("techs", [])
                           if t.get("unlocked") and not t.get("researched")},
        "unlocked_upgrades": {u["name"] for u in snap.get("workshop", {}).get("upgrades", [])
                              if u.get("unlocked") and not u.get("researched")},
        "tabs": tuple(snap.get("tabs", []) or ()),
        "season": snap.get("calendar", {}).get("season"),
        "cycle": snap.get("calendar", {}).get("cycle"),
        "kittens": snap.get("village", {}).get("kittens", 0),
        "caps_reached": caps_reached,
    }


def classify_hard_trigger(prev: dict | None, cur: dict,
                          exec_failed: bool = False) -> dict | None:
    """Erster zutreffender harter Trigger (deterministische Reihenfolge)
    oder None. Aktionsfehler > Unlocks > Cap > Saison/Cycle > Kitten."""
    if exec_failed:
        return {"type": "hard", "source": "error",
                "detail": "Aktionsfehler im Vorzyklus (21.1)"}
    if prev is None:
        return None
    new_unlocks = sorted(
        (cur["techs"] - prev["techs"])
        | (cur["unlocked_techs"] - prev["unlocked_techs"])
        | (cur["unlocked_upgrades"] - prev["unlocked_upgrades"])
        | (set(cur["tabs"]) - set(prev["tabs"])))
    if new_unlocks:
        return {"type": "hard", "source": "unlock",
                "detail": "Neu verfügbar: " + ", ".join(new_unlocks[:4])}
    new_caps = sorted(cur["caps_reached"] - prev["caps_reached"])
    if new_caps:
        return {"type": "hard", "source": "cap",
                "detail": "Cap erreicht: " + ", ".join(new_caps[:4])}
    if cur["season"] != prev["season"]:
        return {"type": "hard", "source": "season",
                "detail": f"Saisonwechsel → {cur['season']}"}
    if cur["cycle"] != prev["cycle"]:
        return {"type": "hard", "source": "cycle",
                "detail": f"Cycle-Wechsel → {cur['cycle']}"}
    if cur["kittens"] != prev["kittens"]:
        return {"type": "hard", "source": "kitten",
                "detail": f"Kitten-Zahl {prev['kittens']} → {cur['kittens']}"}
    return None
