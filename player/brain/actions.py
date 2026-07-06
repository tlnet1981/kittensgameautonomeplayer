"""Aktionsklassen (Spielmechanik-Spec Anhang B, M1-Umfang).

Eine Action beschreibt WAS getan wird (für Cockpit & Log) und WIE es der
Actor ausführt (`exec_spec`). Sie trägt keinen Score — Bewertung passiert
in tactics.py als Candidate.

exec_spec-Kinds (driver/actor.py):
    click_button   Tab öffnen, Button per Titel finden, Glow, Klick (ggf. Batch)
    assign_job     Kitten einem Job zuweisen (Village-Tab + JS-API)
    shift_job      Kitten von einem Job zu einem anderen verschieben
    hunt           game.village.huntAll() mit sichtbarem Village-Tab
    craft          game.workshop.craft(name, amt) mit sichtbarem Workshop-Tab
    wait           nichts tun (bewusstes Warten)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Action:
    id: str                      # stabil & eindeutig, z. B. "build:field"
    type: str                    # BUY_BUILDING | RESEARCH | BUY_UPGRADE | CRAFT | HUNT
    #                              | ASSIGN_JOB | GATHER | REFINE | WAIT | SAFETY
    label: str                   # menschenlesbar: "Baue Catnip-Feld (Nr. 3)"
    exec_spec: dict[str, Any]    # Ausführungsbeschreibung für den Actor
    expected: str = ""           # erwarteter Effekt (ein Satz)
    batch: int = 1               # Chargengröße (Spec 10.5)
    irreversible: bool = False   # Reset/Policies etc. (ab M3 relevant)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type, "label": self.label,
            "expected": self.expected, "batch": self.batch,
            "irreversible": self.irreversible,
        }


# ------------------------------------------------------------------ Fabriken

def gather_catnip(batch: int = 10) -> Action:
    return Action(
        id="gather:catnip", type="GATHER",
        label=f"Sammle Catnip ({batch}× klicken)",
        exec_spec={"kind": "click_button", "tab": "Bonfire", "title": "Gather catnip", "batch": batch},
        expected=f"+{batch} Catnip", batch=batch,
    )


def refine_catnip(batch: int = 1) -> Action:
    return Action(
        id="refine:catnip", type="REFINE",
        label=f"Veredle Catnip zu Holz ({batch}×)",
        exec_spec={"kind": "click_button", "tab": "Bonfire", "title": "Refine catnip", "batch": batch},
        expected=f"-{batch * 100} Catnip → +{batch} Wood (Basis)", batch=batch,
    )


def buy_building(name: str, label: str, count: int) -> Action:
    return Action(
        id=f"build:{name}", type="BUY_BUILDING",
        label=f"Baue {label} (Nr. {count + 1})",
        exec_spec={"kind": "click_button", "tab": "Bonfire", "title": label, "batch": 1},
        expected=f"{label} auf {count + 1}",
    )


def research(name: str, label: str) -> Action:
    return Action(
        id=f"research:{name}", type="RESEARCH",
        label=f"Erforsche {label}",
        exec_spec={"kind": "click_button", "tab": "Science", "title": label, "batch": 1},
        expected=f"Technologie {label} freigeschaltet",
    )


def buy_upgrade(name: str, label: str) -> Action:
    return Action(
        id=f"upgrade:{name}", type="BUY_UPGRADE",
        label=f"Kaufe Upgrade {label}",
        exec_spec={"kind": "click_button", "tab": "Workshop", "title": label, "batch": 1},
        expected=f"Workshop-Upgrade {label} aktiv",
    )


def assign_job(job: str, job_label: str, amount: int = 1) -> Action:
    return Action(
        id=f"job:{job}", type="ASSIGN_JOB",
        label=f"Weise {amount} Kitten dem Job {job_label} zu",
        exec_spec={"kind": "assign_job", "job": job, "amount": amount},
        expected=f"+{amount} {job_label}",
    )


def shift_job(from_job: str, to_job: str, to_label: str, amount: int = 1) -> Action:
    return Action(
        id=f"shift:{from_job}>{to_job}", type="ASSIGN_JOB",
        label=f"Verschiebe {amount} Kitten: {from_job} → {to_label}",
        exec_spec={"kind": "shift_job", "from": from_job, "to": to_job, "amount": amount},
        expected=f"+{amount} {to_label}, -{amount} {from_job}",
    )


def hunt() -> Action:
    return Action(
        id="hunt:all", type="HUNT",
        label="Schicke alle Jäger los",
        exec_spec={"kind": "hunt"},
        expected="Catpower → Furs/Ivory (Chance auf Unicorn)",
    )


def craft(name: str, label: str, times: int) -> Action:
    return Action(
        id=f"craft:{name}", type="CRAFT",
        label=f"Crafte {times}× {label}",
        exec_spec={"kind": "craft", "name": name, "times": times},
        expected=f"+{times} {label} (× Craft Ratio)", batch=times,
    )


def trade(race: str, race_title: str, times: int) -> Action:
    return Action(
        id=f"trade:{race}", type="TRADE",
        label=f"Handle {times}× mit {race_title}",
        exec_spec={"kind": "trade", "race": race, "times": times},
        expected="Ressourcen gemäß Trade-Tabelle", batch=times,
    )


def explore() -> Action:
    return Action(
        id="explore:races", type="TRADE",
        label="Schicke Kundschafter aus (neue Handelspartner)",
        exec_spec={"kind": "click_button", "tab": "Trade", "title": "Send explorers", "batch": 1},
        expected="Chance auf neue Rasse (-1000 Catpower)",
    )


def praise() -> Action:
    return Action(
        id="praise:sun", type="PRAISE",
        label="Preise die Sonne (Faith → Worship)",
        exec_spec={"kind": "praise"},
        expected="Faith wird in dauerhaften Worship umgewandelt",
    )


def festival() -> Action:
    return Action(
        id="festival:hold", type="FESTIVAL",
        label="Feiere ein Festival (+30 % Happiness, ein Jahr)",
        exec_spec={"kind": "click_button", "tab": "Village", "title": "Hold festival", "batch": 1},
        expected="+30 % Happiness, doppelte Kitten-Ankunft",
    )


def wait(reason: str, wake: str) -> Action:
    return Action(
        id="wait", type="WAIT",
        label="Warten (bewusste Entscheidung)",
        exec_spec={"kind": "wait", "reason": reason, "wake": wake},
        expected=wake,
    )
