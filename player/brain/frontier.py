"""Ausbaugrenzen-Wächter („Frontier Guard").

Der Agent deckt das Spiel bis zu einer bestimmten Tiefe ab (siehe
docs/brain.md, „Bewusste Vereinfachungen"). Dieses Modul überwacht, wann
der Spielstand in die NÄHE einer noch nicht implementierten Schicht kommt
— und meldet das als prominenten Cockpit-Hinweis, damit der Betreiber
weiß: jetzt lohnt es sich, die nächste Schicht von Claude Code nachrüsten
zu lassen.

Jeder Hinweis enthält:
- was gerade im Spiel passiert (Trigger)
- was der Agent aktuell NICHT tut
- wo es spezifiziert ist (Spielmechanik-Spec-Kapitel, docs/brain.md)
- einen fertigen Prompt zum Kopieren für die nächste Claude-Code-Session

Einmal ausgelöste Hinweise bleiben aktiv, bis sie im Cockpit quittiert
werden; der Zustand überlebt Neustarts (data/frontier-state.json).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Frontier:
    id: str
    title: str
    trigger: Callable[[dict, str], bool]      # (snapshot, run_type) -> bool
    happening: str      # Was passiert gerade im Spiel?
    missing: str        # Was tut der Agent (noch) nicht?
    where: str          # Wo nachlesen (Spec-Kapitel, Doku, Spielcode)?
    prompt: str         # Fertiger Prompt für die nächste Claude-Code-Session


# Umgesetzte (entfernte) Frontiers: „policies“ (Spec 13.4/I-07 →
# brain/policy.py + tactics._policy_candidates), „challenges“ (Spec 18 →
# brain/challenge.py, CHALLENGE_RUN in meta.py, 18.4-Reset-Gate in reset.py),
# „transcend“ (Spec 15.2 → brain/religion.py tap_plan/transcend_value +
# reset.execute_reset Schritt 5), „pacts“ (Spec 15.4/15.5 →
# brain/religion.py pact_value/alicorn_conversion_due +
# tactics._religion_ev_candidates), „shatter_engine“ (Spec 17.1–17.5 →
# brain/timecrystal.py + tactics._time_candidates, SHATTER_/LEVIATHAN_RUN
# in meta.py) und „cs_loop“ (Spec 19.2/19.3 → chrono.positive_cs_check/
# seed_run_admissible, SEED_/POSITIVE_CS_RUN in meta.py).
FRONTIERS: list[Frontier] = []


def check(snap: dict, run_type: str, already_fired: set[str]) -> list[dict[str, Any]]:
    """Liefert neu ausgelöste Frontier-Hinweise (als dicts fürs Cockpit)."""
    fired: list[dict[str, Any]] = []
    for f in FRONTIERS:
        if f.id in already_fired:
            continue
        try:
            if f.trigger(snap, run_type):
                fired.append(to_dict(f))
        except Exception:
            continue   # defekter Trigger darf den Agenten nie stoppen
    return fired


def to_dict(f: Frontier) -> dict[str, Any]:
    return {
        "id": f.id,
        "title": f.title,
        "happening": f.happening,
        "missing": f.missing,
        "where": f.where,
        "prompt": f.prompt,
    }


def by_id(fid: str) -> Frontier | None:
    return next((f for f in FRONTIERS if f.id == fid), None)
