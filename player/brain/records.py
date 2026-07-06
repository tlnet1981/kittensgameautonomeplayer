"""DecisionRecord — die vollständige, erklärbare Entscheidungsakte.

Entspricht Spielmechanik-Spec Kap. 23 / Cockpit-Spec 23.2 (reduziert):
Jede Entscheidung enthält Auslöser, Kontext (Phase, Ziel, Engpass),
alle Kandidaten mit Score-Zerlegung, den Gewinner und Ablehnungsgründe.
Das ist die Datenquelle für den Decision Inspector im Cockpit.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Any

from .actions import Action

_decision_counter = itertools.count(1)


@dataclass
class Candidate:
    action: Action
    score: float
    components: dict[str, float]        # Score-Zerlegung, z. B. {"milestone": 2.0, ...}
    feasible: bool = True
    reject_reason: str | None = None    # warum NICHT gewählt / nicht machbar
    eta_seconds: float | None = None    # bei nicht bezahlbaren: Zeit bis leistbar

    def to_dict(self, selected: bool = False) -> dict:
        return {
            "action": self.action.to_dict(),
            "score": round(self.score, 4),
            "components": {k: round(v, 4) for k, v in self.components.items() if abs(v) > 1e-9},
            "feasible": self.feasible,
            "rejectReason": self.reject_reason,
            "etaSeconds": self.eta_seconds,
            "selected": selected,
        }


@dataclass
class DecisionRecord:
    trigger: str                        # was die Entscheidung ausgelöst hat
    phase: str
    run_type: str
    objective: str                      # aktiver Meilenstein (Label)
    bottleneck: dict[str, Any] | None   # {"resource","missing","etaSeconds"}
    candidates: list[Candidate]
    selected: Candidate
    reason: str                         # Ein-Satz-Begründung (dominanter Beitrag)
    safety: dict[str, Any] = field(default_factory=dict)
    decision_id: int = field(default_factory=lambda: next(_decision_counter))
    ts: float = field(default_factory=time.time)
    game_time: dict[str, Any] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)   # wird nach Ausführung gefüllt
    observed: str | None = None                               # beobachteter Effekt

    def to_dict(self) -> dict:
        # Kandidaten sortiert: Gewinner zuerst, dann nach Score absteigend.
        ordered = sorted(self.candidates, key=lambda c: (-c.score, c.action.id))
        return {
            "decisionId": self.decision_id,
            "ts": self.ts,
            "trigger": self.trigger,
            "phase": self.phase,
            "runType": self.run_type,
            "objective": self.objective,
            "bottleneck": self.bottleneck,
            "reason": self.reason,
            "safety": self.safety,
            "gameTime": self.game_time,
            "selected": self.selected.to_dict(selected=True),
            "candidates": [c.to_dict(selected=(c is self.selected)) for c in ordered],
            "execution": self.execution,
            "observed": self.observed,
        }
