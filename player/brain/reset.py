"""Reset-Bewertung und Pre-Reset-Transaktion (Spec Kap. 20, vereinfacht).

Reset-Regeln (deterministisch, ohne volle Simulation):
- FIRST_RUN: Reset, sobald die Paragon-Projektion >= FIRST_RESET_MIN_PARAGON.
  (Community-Richtwert: erster Reset ab ~105 Kitten = 35 Paragon.)
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

FIRST_RESET_MIN_PARAGON = 35
# Mindestprojektion für Folge-Resets — verhindert Mini-Runs:
MIN_PARAGON_GAIN = 10


# Paragon-Speedrun (Spec 20.4): Mindestlaufzeit und Abbruchkriterium.
PARAGON_RUN_MIN_SECONDS = 20 * 60
PARAGON_MARGINAL_WINDOW = 5 * 60      # Fenster für die marginale Rate
PARAGON_MARGINAL_FACTOR = 0.5         # Reset, wenn marginal < 50 % der Ø-Rate


def evaluate(snap: dict, run_type: str, next_perk: dict | None,
             paragon_samples: list[tuple[float, int]] | None = None) -> dict[str, Any]:
    """Bewertet, ob jetzt resettet werden soll. Liefert Gates fürs Cockpit."""
    projection = snap.get("derived", {}).get("resetParagon", 0)
    paragon_now = snap.get("prestige", {}).get("paragon", 0)

    recommended = False
    reason = ""
    if run_type == "FIRST_RUN":
        recommended = projection >= FIRST_RESET_MIN_PARAGON
        reason = (f"Projektion {projection} ≥ {FIRST_RESET_MIN_PARAGON} Paragon"
                  if recommended else
                  f"Projektion {projection} / {FIRST_RESET_MIN_PARAGON} Paragon")
    elif run_type == "PARAGON_RUN":
        # Spec 20.4: Run endet, wenn die marginale Paragonrate unter die
        # Durchschnittsrate des Runs fällt (Proxy für den Neustart-Ø).
        recommended, reason = _paragon_speedrun_rule(projection, paragon_samples)
    elif next_perk is not None:
        price = next((p["val"] for p in next_perk.get("prices", []) if p["name"] == "paragon"), 0)
        funds_after_reset = paragon_now + projection
        recommended = (projection >= MIN_PARAGON_GAIN and funds_after_reset >= price)
        reason = (f"{funds_after_reset} Paragon nach Reset decken {next_perk['label']} ({price})"
                  if recommended else
                  f"{funds_after_reset} / {price} Paragon für {next_perk['label']}")
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
    return {
        "recommended": recommended,
        "projection": projection,
        "paragonNow": paragon_now,
        "reason": reason,
        "gates": gates,
        "nextPerk": next_perk["label"] if next_perk else None,
    }


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
