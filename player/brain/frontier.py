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

from player.state import access as A


@dataclass
class Frontier:
    id: str
    title: str
    trigger: Callable[[dict, str], bool]      # (snapshot, run_type) -> bool
    happening: str      # Was passiert gerade im Spiel?
    missing: str        # Was tut der Agent (noch) nicht?
    where: str          # Wo nachlesen (Spec-Kapitel, Doku, Spielcode)?
    prompt: str         # Fertiger Prompt für die nächste Claude-Code-Session


def _ziggurat_upgrade_val(snap: dict, name: str) -> int:
    for z in snap.get("religion", {}).get("ziggurat", []):
        if z["name"] == name:
            return int(z.get("val", 0))
    return 0


# Umgesetzte (entfernte) Frontiers: „policies“ (Spec 13.4/I-07 →
# brain/policy.py + tactics._policy_candidates) und „challenges“ (Spec 18 →
# brain/challenge.py, CHALLENGE_RUN in meta.py, 18.4-Reset-Gate in reset.py).
FRONTIERS: list[Frontier] = [
    Frontier(
        id="transcend",
        title="Transcendence lohnt sich — TAP ist unvollständig",
        trigger=lambda snap, run: snap.get("religion", {}).get("worship", 0) > 50_000,
        happening=("Der Worship-Vorrat ist groß genug, dass Transcendence-Tiers "
                   "erreichbar werden."),
        missing=("Der Agent führt vor Resets nur Adore aus (TAP-light). Transcend "
                 "— der bewusste Epiphany-Einsatz für permanente Tier-Boni — fehlt, "
                 "inklusive der Abwägung aus Spec 15.2 (Wiederanlaufzeit vs. Tier-Gewinn)."),
        where=("Spielmechanik-Spec Kap. 15.2 (TAP-Transaktion) und 15.1. "
               "Spielcode: gamefiles/js/religion.js (transcend, getTranscendenceRatio). "
               "Aktueller Stand: player/brain/reset.py (TAP-light) und docs/brain.md."),
        prompt=("Erweitere den Kittens-Player um die vollständige TAP-Transaktion "
                "(Spec 15.2): Transcend-Aktion in player/brain/actions.py + Actor "
                "(game.religion.transcend() in gamefiles/js/religion.js verifizieren), "
                "Zulässigkeitsregel: neues Tier erreichbar UND verbleibende Epiphany-"
                "Struktur verbessert den Restplan UND Wiederanlaufzeit verschlechtert "
                "die Milestone-Zeit nicht. In die Pre-Reset-Transaktion "
                "(player/brain/reset.py, vor dem Adore-Schritt) integrieren, "
                "Transcendence-Tier ins Reset-Gate und Systems-Religion-Panel."),
    ),
    Frontier(
        id="shatter_engine",
        title="Shatter-Engine-Potenzial — Agent shattert nur konservativ",
        trigger=lambda snap, run: (
            A.res_value(snap, "timeCrystal") >= 50
            or any(u["name"] == "ressourceRetrieval" and u["val"] >= 3
                   for u in snap.get("time", {}).get("chronoforge", []))),
        happening=("Der Time-Crystal-Bestand bzw. Resource-Retrieval-Ausbau erreicht "
                   "eine Größenordnung, in der eine profitable Shatter-Engine "
                   "(Spec Kap. 17) den Endgame-Fortschritt dominieren würde."),
        missing=("Der Agent nutzt nur die konservative Shatter-Regel (kleine Batches, "
                 "Heat-Spielraum, 5-TC-Reserve). Es fehlen: TC-Rückfluss-Bilanz "
                 "(17.1), RR-Wert-Formel (17.2), Chrono-Furnace-Steuerung (17.3), "
                 "Cycle-Positionierung und die Batchgrößen-Optimierung (17.5)."),
        where=("Spielmechanik-Spec Kap. 17 komplett + Anhang D (RR-Wert). "
               "Spielcode: gamefiles/js/time.js (shatter, heat, getCFU). "
               "Aktueller Stand: player/brain/tactics.py → _time_candidates."),
        prompt=("Erweitere den Kittens-Player um die volle Shatter-Engine (Spec Kap. "
                "17): TC-Nettobilanz 17.1, RR-Kaufregel 17.2 (RRValue-Formel Anhang D), "
                "Chrono-Furnace-Bewertung 17.3, Shatter-Batchgrößen-Optimierung unter "
                "Heat-/Cycle-Constraints 17.5 inkl. Cycle-Positionierung für "
                "Trade-Boni (game.calendar.cycle). Ersetze die konservative Regel in "
                "player/brain/tactics.py _time_candidates, ergänze ein Shatter-"
                "Engine-Panel im Systems-Tab (TC-Rückfluss pro Shatter, Konfidenz) "
                "und Tests mit Snapshot-Fixtures."),
    ),
    Frontier(
        id="pacts",
        title="Black Pyramid erreicht — Pacts/Necrocorns nicht automatisiert",
        trigger=lambda snap, run: (
            _ziggurat_upgrade_val(snap, "blackPyramid") > 0
            or A.res_value(snap, "necrocorn") > 0),
        happening=("Eine Black Pyramid steht (oder Necrocorns existieren) — damit "
                   "beginnt die Necrocorn-/Pact-Ökonomie des Endgames."),
        missing=("Der Agent kauft keine Pacts und steuert kein Siphoning: die "
                 "PactValue-Bilanz (Debt-Kosten, Upkeep, alternativer Necrocorn-Wert) "
                 "aus Spec 15.5 ist nicht implementiert."),
        where=("Spielmechanik-Spec Kap. 15.5 (PactValue-Formel) und 15.3/15.4 "
               "(Alicorn-Kette). Spielcode: gamefiles/js/religion.js (pacts, "
               "necrocornDeficit). Rezept: docs/brain.md."),
        prompt=("Erweitere den Kittens-Player um Pacts & Necrocorn-Management (Spec "
                "15.5): Snapshot-Sektion für game.religion.pacts + Necrocorn-Debt, "
                "PactValue-Formel (ΔBlackPyramidUtility − DebtCost − UpkeepCost − "
                "AlternativeNecrocornValue), BUY_PACT/SET_SIPHONING-Aktionen "
                "(Anhang B), Alicorn→TC-Konvertierungsregel 15.4. Pact-Käufe sind "
                "irreversibel → vollständige DecisionRecords. Cockpit: Pact-"
                "Observatory-Panel (Cockpit-Spec 11.3)."),
    ),
    Frontier(
        id="cs_loop",
        title="Chronosphere-Bestand wächst — Seed-/Carryover-Strategie fehlt",
        trigger=lambda snap, run: A.bld_val(snap, "chronosphere") >= 3,
        happening=("Mehrere Chronospheres sind gebaut — Carryover über Resets wird "
                   "strategisch relevant (Seed-Runs, positive Reset-Schleife)."),
        missing=("Der Agent kauft Chronospheres nur opportunistisch. Es fehlen: "
                 "CSValue-Formel (19.1), optimale Chronosphere-Zahl pro Run, "
                 "Seed-Run-Typ und die positive Reset-Bedingung (19.2) inklusive "
                 "Non-Carry-Restausgaben in der Pre-Reset-Transaktion (20.3 Schritt 8)."),
        where=("Spielmechanik-Spec Kap. 19 komplett + 20.3. "
               "Aktueller Stand: player/brain/reset.py (Pre-Reset-Transaktion) und "
               "tactics.py (Chronosphere im Whitelist)."),
        prompt=("Erweitere den Kittens-Player um Chronosphere-/Seed-Strategie (Spec "
                "Kap. 19): CSValue-Formel 19.1 mit Suche über n−2…n+3, Run-Typen "
                "SEED_RUN und POSITIVE_CS_RUN im Meta-Controller, positive "
                "Reset-Bedingung 19.2 (Vektordominanz des Carryover), Pre-Reset-"
                "Schritt 'nicht übertragbare Ressourcen mit Restwert ausgeben' "
                "(20.3 Schritt 8) und Carryover-Abgleich nach dem Reset. Cockpit: "
                "Continue-vs-Reset-Darstellung im Systems-Tab erweitern."),
    ),
]


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
