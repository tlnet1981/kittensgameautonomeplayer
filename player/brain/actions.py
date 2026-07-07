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

# ActionAtomicity (Spec Anhang A.2): Grundlage des AgentMode-Gates (G-02) —
# im MODEL_MISMATCH sind nur READ_ONLY-Aktionen (plus "Verbraucher
# abschalten") zulässig, IRREVERSIBLE folgt der Spec-7.4-Liste.
READ_ONLY = "READ_ONLY"
REVERSIBLE = "REVERSIBLE"
BATCH_REVERSIBLE = "BATCH_REVERSIBLE"
IRREVERSIBLE = "IRREVERSIBLE"


def price_deltas(prices: list[dict] | None) -> dict[str, float] | None:
    """Preisvektor → Sofort-Effekt-Prognose {res: −preis} (G-10)."""
    if not prices:
        return None
    out: dict[str, float] = {}
    for p in prices:
        out[p["name"]] = out.get(p["name"], 0.0) - float(p["val"])
    return out


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
    atomicity: str = REVERSIBLE  # ActionAtomicity (Anhang A.2)
    # Prognostizierter Sofort-Effekt für die Distanzprüfung (G-10):
    # {"deltas": {res: ±menge}, "stochastic": bool} | None = kein Modell.
    predicted: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type, "label": self.label,
            "expected": self.expected, "batch": self.batch,
            "irreversible": self.irreversible,
            "atomicity": self.atomicity,
            "predicted": self.predicted,
        }


# ------------------------------------------------------------------ Fabriken

def gather_catnip(batch: int = 10) -> Action:
    return Action(
        id="gather:catnip", type="GATHER",
        label=f"Sammle Catnip ({batch}× klicken)",
        exec_spec={"kind": "click_button", "tab": "Bonfire", "title": "Gather catnip", "batch": batch},
        expected=f"+{batch} Catnip", batch=batch,
        atomicity=BATCH_REVERSIBLE if batch > 1 else REVERSIBLE,
        predicted={"deltas": {"catnip": float(batch)}, "stochastic": False},
    )


def refine_catnip(batch: int = 1) -> Action:
    return Action(
        id="refine:catnip", type="REFINE",
        label=f"Veredle Catnip zu Holz ({batch}×)",
        exec_spec={"kind": "click_button", "tab": "Bonfire", "title": "Refine catnip", "batch": batch},
        expected=f"-{batch * 100} Catnip → +{batch} Wood (Basis)", batch=batch,
        atomicity=BATCH_REVERSIBLE if batch > 1 else REVERSIBLE,
        predicted={"deltas": {"catnip": -100.0 * batch, "wood": float(batch)},
                   "stochastic": False},
    )


def buy_building(name: str, label: str, count: int,
                 prices: list[dict] | None = None) -> Action:
    deltas = price_deltas(prices)
    return Action(
        id=f"build:{name}", type="BUY_BUILDING",
        label=f"Baue {label} (Nr. {count + 1})",
        exec_spec={"kind": "click_button", "tab": "Bonfire", "title": label, "batch": 1},
        expected=f"{label} auf {count + 1}",
        predicted={"deltas": deltas, "stochastic": False} if deltas else None,
    )


def research(name: str, label: str, prices: list[dict] | None = None) -> Action:
    deltas = price_deltas(prices)
    return Action(
        id=f"research:{name}", type="RESEARCH",
        label=f"Erforsche {label}",
        exec_spec={"kind": "click_button", "tab": "Science", "title": label, "batch": 1},
        expected=f"Technologie {label} freigeschaltet",
        predicted={"deltas": deltas, "stochastic": False} if deltas else None,
    )


def buy_upgrade(name: str, label: str, prices: list[dict] | None = None) -> Action:
    deltas = price_deltas(prices)
    return Action(
        id=f"upgrade:{name}", type="BUY_UPGRADE",
        label=f"Kaufe Upgrade {label}",
        exec_spec={"kind": "click_button", "tab": "Workshop", "title": label, "batch": 1},
        expected=f"Workshop-Upgrade {label} aktiv",
        predicted={"deltas": deltas, "stochastic": False} if deltas else None,
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


def toggle_building(name: str, label: str, on: bool) -> Action:
    """Verbraucher/Erzeuger um EINE Einheit an-/abschalten (Spec 16.4 / Anhang B
    TOGGLE_BUILDING). `on=False` reduziert die aktive Anzahl um 1."""
    verb = "Aktiviere" if on else "Deaktiviere"
    return Action(
        id=f"toggle:{name}:{'on' if on else 'off'}", type="TOGGLE_BUILDING",
        label=f"{verb} 1× {label} (Energie-Steuerung)",
        exec_spec={"kind": "toggle_building", "name": name, "on": on},
        expected=f"{label}: aktive Anzahl {'+1' if on else '−1'}",
    )


def set_leader(kitten_index: int, label: str) -> Action:
    """Leader setzen (Spec 12.3 / Anhang B SET_LEADER). `kitten_index` ist der
    Index in village.sim.kittens (wie im Snapshot-Census)."""
    return Action(
        id=f"leader:{kitten_index}", type="SET_LEADER",
        label=f"Ernenne {label} zum Leader",
        exec_spec={"kind": "set_leader", "index": kitten_index},
        expected=f"{label} ist Leader",
    )


def hunt() -> Action:
    return Action(
        id="hunt:all", type="HUNT",
        label="Schicke alle Jäger los",
        exec_spec={"kind": "hunt"},
        expected="Catpower → Furs/Ivory (Chance auf Unicorn)",
    )


def craft(name: str, label: str, times: int, prices: list[dict] | None = None,
          craft_ratio: float = 0.0) -> Action:
    deltas = None
    if prices:
        deltas = {p["name"]: -float(p["val"]) * times for p in prices}
        deltas[name] = deltas.get(name, 0.0) + times * (1.0 + craft_ratio)
    return Action(
        id=f"craft:{name}", type="CRAFT",
        label=f"Crafte {times}× {label}",
        exec_spec={"kind": "craft", "name": name, "times": times},
        expected=f"+{times} {label} (× Craft Ratio)", batch=times,
        atomicity=BATCH_REVERSIBLE if times > 1 else REVERSIBLE,
        predicted={"deltas": deltas, "stochastic": False} if deltas else None,
    )


def space_program(name: str, label: str, prices: list[dict] | None = None) -> Action:
    """Space-Mission starten (einmalig, z. B. Orbital Launch)."""
    deltas = price_deltas(prices)
    return Action(
        id=f"space:{name}", type="BUY_BUILDING",
        label=f"Space: {label}",
        exec_spec={"kind": "click_button", "tab": "Space", "title": label, "batch": 1},
        expected=f"Mission {label} abgeschlossen",
        predicted={"deltas": deltas, "stochastic": False} if deltas else None,
    )


def buy_perk(name: str, label: str, prices: list[dict] | None = None) -> Action:
    """Metaphysics-Perk kaufen — irreversibel (Paragon wird ausgegeben).
    Panel-Scoping verhindert die Kollision mit gleichnamigen Policies!"""
    deltas = price_deltas(prices)
    return Action(
        id=f"perk:{name}", type="BUY_UPGRADE",
        label=f"Kaufe Metaphysics: {label}",
        exec_spec={"kind": "click_button", "tab": "Science",
                   "panel": "Metaphysics", "title": label, "batch": 1},
        expected=f"Permanenter Bonus: {label}",
        irreversible=True, atomicity=IRREVERSIBLE,
        predicted={"deltas": deltas, "stochastic": False} if deltas else None,
    )


def select_policy(name: str, label: str, prices: list[dict] | None = None) -> Action:
    """Exklusive Policy wählen — irreversibel (Spec 7.4/13.4/I-07): die
    `blocks`-Alternativen sind danach bis zum Reset gesperrt
    (gamefiles/js/science.js:847-849). Panel-Scoping im Actor beachten
    (Policy „Diplomacy" vs. Metaphysics-Perk „Diplomacy", actor.py)."""
    deltas = price_deltas(prices)
    return Action(
        id=f"policy:{name}", type="SELECT_POLICY",
        label=f"Policy wählen: {label}",
        exec_spec={"kind": "select_policy", "name": name, "label": label},
        expected=f"Policy {label} aktiv — exklusive Alternativen blockiert (I-07 geprüft)",
        irreversible=True, atomicity=IRREVERSIBLE,
        predicted={"deltas": deltas, "stochastic": False} if deltas else None,
    )


def activate_challenge(name: str, label: str) -> Action:
    """Challenge als pending vormerken — irreversibel behandelt (Spec 7.4):
    der Reset wandelt pending → active (gamefiles/game.js:5136-5141), danach
    gelten die Challenge-Regeln für den ganzen Folgerun. Kostenlos
    (ChallengeBtnController.buyItem: „item-is-free", challenges.js:877-883)."""
    return Action(
        id=f"challenge:{name}", type="ACTIVATE_CHALLENGE",
        label=f"Challenge vormerken: {label} (pending für den nächsten Run)",
        exec_spec={"kind": "activate_challenge", "name": name, "label": label},
        expected=f"Challenge {label} ist pending und wird beim Reset aktiv",
        irreversible=True, atomicity=IRREVERSIBLE,
    )


def reset_run() -> Action:
    return Action(
        id="reset:run", type="RESET",
        label="RESET — neuen Run mit Paragon starten",
        exec_spec={"kind": "reset"},
        expected="Paragon-Gewinn, Neustart der Zivilisation",
        irreversible=True, atomicity=IRREVERSIBLE,
    )


def trade(race: str, race_title: str, times: int) -> Action:
    return Action(
        id=f"trade:{race}", type="TRADE",
        label=f"Handle {times}× mit {race_title}",
        exec_spec={"kind": "trade", "race": race, "times": times},
        expected="Ressourcen gemäß Trade-Tabelle", batch=times,
        atomicity=BATCH_REVERSIBLE if times > 1 else REVERSIBLE,
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


def buy_religion_upgrade(name: str, label: str, ziggurat: bool = False,
                         prices: list[dict] | None = None) -> Action:
    deltas = price_deltas(prices)
    return Action(
        id=f"religion:{name}", type="BUY_UPGRADE",
        label=f"Religion: {label}",
        exec_spec={"kind": "click_button", "tab": "Religion", "title": label, "batch": 1},
        expected=f"{label} aktiv" + (" (Ziggurat-Ausbau)" if ziggurat else ""),
        predicted={"deltas": deltas, "stochastic": False} if deltas else None,
    )


def sacrifice_unicorns() -> Action:
    return Action(
        id="religion:sacrificeUnicorns", type="SACRIFICE_UNICORNS",
        label="Opfere Unicorns (→ Tears)",
        exec_spec={"kind": "click_button", "tab": "Religion",
                   "title": "Sacrifice unicorns", "batch": 1},
        expected="2500 Unicorns → Tears (× Ziggurat-Stufe)",
        irreversible=True, atomicity=IRREVERSIBLE,
        predicted={"deltas": {"unicorns": -2500.0}, "stochastic": False},
    )


def adore() -> Action:
    """Adore the Galaxy: Worship → permanente Epiphany (Teil der TAP-Kette)."""
    return Action(
        id="religion:adore", type="ADORE",
        label="Adore the Galaxy (Worship → Epiphany)",
        exec_spec={"kind": "adore"},
        expected="Worship wird zu permanenter Epiphany",
        irreversible=True, atomicity=IRREVERSIBLE,
    )


def transcend() -> Action:
    """Transcend: Epiphany → Transcendence Tier (Spec 15.2, irreversibel per
    7.4). Kostet _getTranscendNextPrice() Epiphany (religion.js:1624-1653);
    läuft NUR in der Pre-Reset-Transaktion, nie im normalen Zyklus."""
    return Action(
        id="religion:transcend", type="TRANSCEND",
        label="Transcend (Epiphany → Transcendence Tier)",
        exec_spec={"kind": "transcend"},
        expected="Transcendence Tier +1, Epiphany sinkt um den Tier-Preis",
        irreversible=True, atomicity=IRREVERSIBLE,
    )


def convert_alicorns(batches: int = 1) -> Action:
    """Alicorns → Time Crystals (Spec 15.4, irreversibel per 7.4):
    25 Alicorns je Batch → (1 + tcRefineRatio) TC (religion.js:3028-3049).
    Der TC-Gewinn hängt am Live-Effekt und fehlt deshalb in der Prognose."""
    return Action(
        id="religion:convertAlicorns", type="CONVERT_ALICORNS",
        label=f"Konvertiere Alicorns → Time Crystals ({batches}× 25)",
        exec_spec={"kind": "convert_alicorns", "batches": batches},
        expected=f"-{batches * 25} Alicorns → +{batches}× (1+tcRefineRatio) TC",
        batch=batches, irreversible=True, atomicity=IRREVERSIBLE,
        predicted={"deltas": {"alicorn": -25.0 * batches}, "stochastic": False},
    )


def refine_tears(batches: int = 1) -> Action:
    """Tears → Black Liquid Sorrow (Spec 15.3, irreversibel per 7.4):
    10 000 Tears je Batch → 1 BLS, Sorrow-Cap-gated (religion.js:2262-2311)."""
    return Action(
        id="religion:refineTears", type="REFINE_TEARS",
        label=f"Refine Tears → Black Liquid Sorrow ({batches}×)",
        exec_spec={"kind": "refine_tears", "batches": batches},
        expected=f"-{batches * 10000} Tears → +{batches} BLS",
        batch=batches, irreversible=True, atomicity=IRREVERSIBLE,
        predicted={"deltas": {"tears": -10000.0 * batches,
                              "sorrow": float(batches)}, "stochastic": False},
    )


def buy_pact(name: str, label: str, prices: list[dict] | None = None) -> Action:
    """Pact kaufen (Spec 15.5, irreversibel per 7.4): 100 Relic, danach
    dauerhafter Necrocorn-Upkeep (religion.js pactsManager)."""
    deltas = price_deltas(prices)
    return Action(
        id=f"pact:{name}", type="BUY_PACT",
        label=f"Pact schließen: {label}",
        exec_spec={"kind": "buy_pact", "name": name, "label": label},
        expected=f"{label} aktiv — dauerhafter Necrocorn-Upkeep beginnt",
        irreversible=True, atomicity=IRREVERSIBLE,
        predicted={"deltas": deltas, "stochastic": False} if deltas else None,
    )


def festival() -> Action:
    return Action(
        id="festival:hold", type="FESTIVAL",
        label="Feiere ein Festival (+30 % Happiness, ein Jahr)",
        exec_spec={"kind": "click_button", "tab": "Village", "title": "Hold festival", "batch": 1},
        expected="+30 % Happiness, doppelte Kitten-Ankunft",
    )


def shatter(batch: int) -> Action:
    """Time Crystals shattern (+1 Jahr je TC; Ertrag über Resource Retrieval).
    Große Batches (> 2) gelten als irreversibel (Spec 7.4)."""
    return Action(
        id="time:shatter", type="SHATTER",
        label=f"Shatter {batch}× Time Crystal (+{batch} Jahre)",
        exec_spec={"kind": "shatter", "batch": batch},
        expected=f"+{batch} Jahre, Ressourcen via Resource Retrieval, +Heat",
        irreversible=True, batch=batch,
        atomicity=IRREVERSIBLE if batch > 2 else BATCH_REVERSIBLE,
        predicted={"deltas": {"timeCrystal": -float(batch)}, "stochastic": False},
    )


def set_tempus_fugit(on: bool) -> Action:
    """Tempus Fugit an-/abschalten (Anhang B SET_TEMPUS_FUGIT, REVERSIBLE).

    Mechanik der Referenz: Toggle über time.isAccelerated (time.js:1086-1097,
    AccelerateTimeBtnController.buyItem — „item-is-free", frei umschaltbar);
    +50 % Spielgeschwindigkeit (game.js:3964/3984 timeAccelerationRatio),
    Verbrauch 1 temporalFlux je Tick (time.js:153-155), automatisches AUS
    bei Flux 0 (time.js:156-158)."""
    verb = "Aktiviere" if on else "Deaktiviere"
    return Action(
        id=f"time:tempusFugit:{'on' if on else 'off'}", type="SET_TEMPUS_FUGIT",
        label=f"{verb} Tempus Fugit (+50 % Spielgeschwindigkeit)",
        exec_spec={"kind": "set_tempus_fugit", "on": on},
        expected=("Zeit beschleunigt, Flux wird verbraucht" if on
                  else "Normalgeschwindigkeit, Flux-Vorrat bleibt"),
        atomicity=REVERSIBLE,
    )


def wait(reason: str, wake: str) -> Action:
    return Action(
        id="wait", type="WAIT",
        label="Warten (bewusste Entscheidung)",
        exec_spec={"kind": "wait", "reason": reason, "wake": wake},
        expected=wake,
        atomicity=READ_ONLY,
    )
