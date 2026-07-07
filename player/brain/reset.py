"""Reset-Bewertung und Pre-Reset-Transaktion (Spec Kap. 20, vereinfacht).

Reset-Regeln (deterministisch):
- FIRST_RUN: Paragon-Projektion >= FIRST_RESET_MIN_PARAGON ist notwendige
  Vorbedingung (Community-Richtwert: erster Reset ab ~105 Kitten = 35
  Paragon); endgültig entscheidet ResetValue = V(post) − V(continue) über
  die EV-Projektion (Spec 20.1, siehe _reset_value) — ohne Simulationsdaten
  greift die Schwelle allein (Altverhalten).
- PRICE_RATIO_RUN: Reset, sobald aktueller Paragon + Projektion den Preis des
  nächsten Metaphysics-Ziels deckt (Spec 20.2: „Finanzierung des nächsten
  Metaphysics-Ziels") UND die Projektion einen Mindestwert erreicht (damit
  ein Run nicht nach zwei Minuten endet).

Die Pre-Reset-Transaktion (20.3 light):
  1. Save exportieren (I-02: Schutz persistenter Werte)
  2. Gates prüfen und im Cockpit anzeigen
  3. Kapitelkarte (P1) veröffentlichen
  4. game.resetAutomatic() — das Spiel lädt die Seite neu
  5. Auf Neuinitialisierung warten; der nächste Zyklus beginnt den neuen Run
"""

from __future__ import annotations

import asyncio
from typing import Any

from player.driver.actor import SET_CHALLENGE_PENDING_JS

from . import challenge, simulate

FIRST_RESET_MIN_PARAGON = 35
# Mindestprojektion für Folge-Resets — verhindert Mini-Runs:
MIN_PARAGON_GAIN = 10

# Vergleichshorizont der ResetValue-Rechnung (Spec 20.1): T = bisherige
# Runzeit, geklemmt auf [10 min, 2 h].
RESET_VALUE_T_MIN = 600.0
RESET_VALUE_T_MAX = 2 * 3600.0


# Paragon-Speedrun (Spec 20.4): Mindestlaufzeit und Abbruchkriterium.
PARAGON_RUN_MIN_SECONDS = 20 * 60
PARAGON_MARGINAL_WINDOW = 5 * 60      # Fenster für die marginale Rate
PARAGON_MARGINAL_FACTOR = 0.5         # Reset, wenn marginal < 50 % der Ø-Rate


# Kernschritte von challenges.applyPending OHNE UI-Confirm (gamefiles/js/
# challenges.js:687-702): Abschluss-Check der On-Reset-Challenges, Reserven
# berechnen, Chronospheres nullen (Challenge-Einstieg erlaubt keinen
# CS-Carryover), Cryochamber-/Anarchy-Sonderfälle wie im Original. Läuft nur,
# wenn tatsächlich eine Challenge pending ist. Die pending → active-
# Umwandlung selbst macht _resetInternal (gamefiles/game.js:5136-5141).
APPLY_PENDING_CORE_JS = """
() => {
    const g = window.gamePage || window.game;
    if (!g || !g.challenges || !g.challenges.getCountPending()) { return false; }
    g.challenges.onRunReset();
    g.challenges.reserves.calculateReserves(false);
    g.bld.get("chronosphere").val = 0;
    g.bld.get("chronosphere").on = 0;
    if (!g.challenges.getChallenge("postApocalypse").pending) {
        g.time.getVSU("cryochambers").val = 0;
        g.time.getVSU("cryochambers").on = 0;
    } else if (g.challenges.getChallenge("anarchy").pending && g.village.leader) {
        g.village.leader.isLeader = false;
        g.village.leader = null;
    }
    return true;
}
"""


def evaluate(snap: dict, run_type: str, next_perk: dict | None,
             paragon_samples: list[tuple[float, int]] | None = None) -> dict[str, Any]:
    """Bewertet, ob jetzt resettet werden soll. Liefert Gates fürs Cockpit."""
    projection = snap.get("derived", {}).get("resetParagon", 0)
    paragon_now = snap.get("prestige", {}).get("paragon", 0)

    recommended = False
    reason = ""
    reset_value: dict | None = None
    if run_type == "FIRST_RUN":
        # Schwelle bleibt notwendige Vorbedingung (Sanity-Grenze); erst dann
        # entscheidet ResetValue = V(post) − V(continue) (Spec 20.1):
        if projection < FIRST_RESET_MIN_PARAGON:
            reason = f"Projektion {projection} / {FIRST_RESET_MIN_PARAGON} Paragon"
        else:
            reset_value = _reset_value(snap, projection)
            if reset_value is None:      # keine Simulationsdaten → Altverhalten
                recommended = True
                reason = f"Projektion {projection} ≥ {FIRST_RESET_MIN_PARAGON} Paragon"
            else:
                recommended = reset_value["resetValue"] > 0
                reason = (f"Projektion {projection} ≥ {FIRST_RESET_MIN_PARAGON} Paragon; "
                          + _reset_value_text(reset_value)
                          + ("" if recommended else " — Weiterlaufen dominiert"))
    elif run_type == "PARAGON_RUN":
        # Spec 20.4: Run endet, wenn die marginale Paragonrate unter die
        # Durchschnittsrate des Runs fällt (Proxy für den Neustart-Ø).
        # Diese Speedrun-Regel bleibt unangetastet (kein ResetValue-Gate).
        recommended, reason = _paragon_speedrun_rule(projection, paragon_samples)
    elif run_type == "CHALLENGE_RUN":
        # Spec 18.4: Reset NUR, wenn das SPIEL die Challenge als erfüllt
        # markiert (researched-Flag aus dem Snapshot; researchChallenge in
        # gamefiles/js/challenges.js:648-665 setzt es, sobald die
        # Zielbedingung wirklich erfüllt ist). Eine bloß prognostizierte
        # Erfüllung reicht nicht — kein ResetValue-Ersatzweg.
        recommended, reason = challenge.reset_gate(snap)
    elif next_perk is not None:
        price = next((p["val"] for p in next_perk.get("prices", []) if p["name"] == "paragon"), 0)
        funds_after_reset = paragon_now + projection
        # Harte Regel (Spec 20.2): Perk-Finanzierung erreicht → Reset, auch
        # ohne positiven ResetValue; die V-Werte werden nur transparent gemacht.
        recommended = (projection >= MIN_PARAGON_GAIN and funds_after_reset >= price)
        reason = (f"{funds_after_reset} Paragon nach Reset decken {next_perk['label']} ({price})"
                  if recommended else
                  f"{funds_after_reset} / {price} Paragon für {next_perk['label']}")
        if recommended:
            reset_value = _reset_value(snap, projection)
            if reset_value is not None:
                reason += "; " + _reset_value_text(reset_value)
    else:
        reason = "Kein Reset-Ziel im aktuellen Run"

    # TC-Schutz (Invariante I-02 / Spec 9.1): Reset mit relevantem
    # Time-Crystal-Bestand nur mit Anachronomancy (TC überleben sonst nicht).
    tc = next((r["value"] for r in snap.get("resources", []) if r["name"] == "timeCrystal"), 0)
    anachronomancy = any(p["name"] == "anachronomancy" and p["researched"]
                         for p in snap.get("prestige", {}).get("perks", []))
    tc_safe = tc < 3 or anachronomancy
    if not tc_safe:
        recommended = False

    gates = [
        {"name": "Paragon-Projektion", "pass": projection > 0,
         "detail": f"+{projection} Paragon bei Reset"},
        {"name": "Run-Ziel finanziert", "pass": recommended or not tc_safe, "detail": reason},
        {"name": "TC-Schutz (Anachronomancy)", "pass": tc_safe,
         "detail": (f"{tc:.0f} TC " + ("geschützt" if anachronomancy else
                    "UNGESCHÜTZT — Reset blockiert" if tc >= 3 else "— unkritisch"))},
        {"name": "Save-Export", "pass": True, "detail": "wird in der Transaktion ausgeführt"},
    ]
    # Pending-Challenge für den NÄCHSTEN Run (Spec 18 / Pre-Reset-Schritt):
    # nur wenn der Makroplan den Challenge-Run vorsieht (run_type ==
    # CHALLENGE_RUN aus meta.determine_run_plan), noch keine Challenge läuft
    # und eine unerledigte Challenge positiven Wert hat (18.2). execute_reset
    # aktiviert sie unmittelbar vor dem Reset (pending → active beim Reset,
    # gamefiles/game.js:5136-5141).
    pending_challenge = None
    if run_type == "CHALLENGE_RUN" and challenge.active_challenge(snap) is None:
        best = challenge.best_challenge(snap)
        if best is not None:
            pending_challenge = {"name": best[0],
                                 "label": challenge.label_of(snap, best[0]),
                                 "value": round(best[1], 4)}

    return {
        "recommended": recommended,
        "projection": projection,
        "paragonNow": paragon_now,
        "reason": reason,
        "gates": gates,
        "nextPerk": next_perk["label"] if next_perk else None,
        "resetValue": reset_value,
        "pendingChallenge": pending_challenge,
    }


# ---------------------------------------------------------------- ResetValue

def _reset_value(snap: dict, projection: float) -> dict | None:
    """ResetValue = V(post) − V(continue) in Paragon bei gleicher Realzeit T
    (Spec 20.1). None, wenn der Snapshot keine Projektion trägt (Fallback).

    V(continue): Paragon-Stand, wenn der Run noch T Sekunden weiterläuft und
    DANN resettet wird — Projektion + Kitten-/Jahreszuwachs aus simulate.
    V(post): Paragon-Stand eines Neustarts JETZT nach T Sekunden — die
    Projektion wird sofort gebankt, der neue Run fährt eine konservativ
    LINEARE Rampe von 0 auf die historische Ø-Paragonrate des aktuellen
    Runs (Fläche = avg_rate·T/2; der Neustart braucht Anlaufzeit, erreicht
    aber dank permanenter Boni mindestens die alte Ø-Rate — dokumentierte
    Näherung statt voller Neustart-Simulation)."""
    if not simulate.has_projection_data(snap):
        return None
    elapsed = simulate.run_elapsed_seconds(snap)
    t_cmp = min(max(elapsed, RESET_VALUE_T_MIN), RESET_VALUE_T_MAX)
    proj = simulate.project(snap, t_cmp)
    delta_continue = proj.paragon_projection(t_cmp) - proj.paragon_projection(0.0)
    v_continue = projection + delta_continue
    avg_rate = projection / max(elapsed, 1.0)
    v_post = projection + avg_rate * t_cmp / 2.0
    return {
        "resetValue": round(v_post - v_continue, 2),
        "vContinue": round(v_continue, 2),
        "vPost": round(v_post, 2),
        "horizonS": round(t_cmp, 1),
    }


def _reset_value_text(rv: dict) -> str:
    """V-Werte für den reason-Text (Cockpit-Transparenz, Spec 20.1)."""
    return (f"ResetValue {rv['resetValue']:+.1f} Paragon "
            f"(V(neu) {rv['vPost']:.1f} vs V(weiter) {rv['vContinue']:.1f} "
            f"über {rv['horizonS']:.0f} s)")


def _paragon_speedrun_rule(projection: int,
                           samples: list[tuple[float, int]] | None) -> tuple[bool, str]:
    if not samples or len(samples) < 2:
        return False, "Paragon-Run: sammle Verlaufsdaten"
    t0, p0 = samples[0]
    t_now, p_now = samples[-1]
    runtime_s = t_now - t0
    if runtime_s < PARAGON_RUN_MIN_SECONDS or projection < MIN_PARAGON_GAIN:
        return False, (f"Paragon-Run läuft {runtime_s / 60:.0f} min, "
                       f"Projektion +{projection}")
    avg_rate = (p_now - p0) / max(1.0, runtime_s)
    window_start = t_now - PARAGON_MARGINAL_WINDOW
    recent = [(t, p) for t, p in samples if t >= window_start]
    if len(recent) < 2:
        return False, "Paragon-Run: Fenster zu kurz"
    marginal_rate = (recent[-1][1] - recent[0][1]) / max(1.0, recent[-1][0] - recent[0][0])
    if avg_rate <= 0:
        return False, "Paragon-Run: noch keine positive Rate"
    if marginal_rate < avg_rate * PARAGON_MARGINAL_FACTOR:
        return True, (f"marginale Paragonrate {marginal_rate * 3600:.1f}/h < "
                      f"{PARAGON_MARGINAL_FACTOR:.0%} der Ø-Rate {avg_rate * 3600:.1f}/h "
                      f"(Spec 20.4)")
    return False, (f"marginale Rate {marginal_rate * 3600:.1f}/h hält Ø-Rate "
                   f"{avg_rate * 3600:.1f}/h — weiterlaufen")


async def execute_reset(runtime, reset_eval: dict) -> None:
    """Pre-Reset-Transaktion + atomarer Reset + Warten auf den neuen Run."""
    bus = runtime.bus
    browser = runtime.browser

    # 1. Save-Export (Schutz persistenter Werte, I-02)
    save = await browser.export_save()
    if save and runtime.store:
        runtime.store.write_save(save)

    # 1b. TAP-light (Spec 15.2, ohne Transcend in dieser Ausbaustufe):
    #     Worship über Adore in permanente Epiphany retten, sofern Apocrypha
    #     verfügbar ist — Worship selbst überlebt den Reset nicht in voller Höhe.
    try:
        adored = await browser.evaluate(
            "() => { const ru = game.religion.getRU('apocripha');"
            " if (!ru || !ru.on || game.religion.faith < 1000) return false;"
            " game.religion.resetFaith(1.01, false); return true; }")
        if adored:
            bus.publish("narrative.milestone", {
                "priority": "P2", "title": "Adore vor Reset",
                "body": "Worship wurde in permanente Epiphany umgewandelt (TAP-Kette).",
            })
    except Exception:
        pass

    # 1c. Pending-Challenge für den NÄCHSTEN Run aktivieren (Spec 18,
    #     Schritt der Pre-Reset-Transaktion; die restlichen 20.3-Schritte
    #     baut Phase I). Verifikation über das pending-Flag; danach die
    #     applyPending-Kernschritte (Reserven, CS-Nullung) wie im Spiel.
    pending = reset_eval.get("pendingChallenge")
    if pending:
        try:
            res = await browser.evaluate(SET_CHALLENGE_PENDING_JS,
                                         {"name": pending["name"]})
            if res.get("pending"):
                await browser.evaluate(APPLY_PENDING_CORE_JS)
                bus.publish("narrative.milestone", {
                    "priority": "P2",
                    "title": f"Challenge vorgemerkt: {pending['label']}",
                    "body": ("Der nächste Run läuft als Challenge-Run — "
                             "pending wird beim Reset aktiv (Spec 18)."),
                })
            else:
                bus.publish("model.warning", {
                    "error": (f"Challenge {pending['name']} nicht aktivierbar: "
                              f"{res.get('error', 'pending-Flag nicht gesetzt')}")})
        except Exception:
            pass

    # 2./3. Kapitelkarte — der Reset ist ein Kapitelwechsel (Cockpit-Spec 14.5)
    bus.publish("narrative.chapter", {
        "priority": "P1",
        "title": f"RESET — Kapitelwechsel (+{reset_eval['projection']} Paragon)",
        "body": (f"{reset_eval['reason']}. Die Zivilisation beginnt von vorn — "
                 f"schneller, mit permanenten Boni."),
    })
    bus.publish("reset.committed", reset_eval)

    # 4. Atomarer Reset (lädt die Seite neu)
    await browser.evaluate("() => game.resetAutomatic()")

    # 5. Auf Reload + Neuinitialisierung warten (inkl. Glow-CSS & Optionen)
    await asyncio.sleep(3.0)
    await browser.reinitialize(timeout_s=90)
    bus.publish("narrative.chapter", {
        "priority": "P1",
        "title": "Neuer Run beginnt",
        "body": "Carryover geprüft — der Agent baut die Wirtschaft mit Paragon-Bonus neu auf.",
    })
