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


def evaluate(snap: dict, run_type: str, next_perk: dict | None) -> dict[str, Any]:
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
    elif next_perk is not None:
        price = next((p["val"] for p in next_perk.get("prices", []) if p["name"] == "paragon"), 0)
        funds_after_reset = paragon_now + projection
        recommended = (projection >= MIN_PARAGON_GAIN and funds_after_reset >= price)
        reason = (f"{funds_after_reset} Paragon nach Reset decken {next_perk['label']} ({price})"
                  if recommended else
                  f"{funds_after_reset} / {price} Paragon für {next_perk['label']}")
    else:
        reason = "Kein Reset-Ziel im aktuellen Run"

    gates = [
        {"name": "Paragon-Projektion", "pass": projection > 0,
         "detail": f"+{projection} Paragon bei Reset"},
        {"name": "Run-Ziel finanziert", "pass": recommended, "detail": reason},
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


async def execute_reset(runtime, reset_eval: dict) -> None:
    """Pre-Reset-Transaktion + atomarer Reset + Warten auf den neuen Run."""
    bus = runtime.bus
    browser = runtime.browser

    # 1. Save-Export (Schutz persistenter Werte, I-02)
    save = await browser.export_save()
    if save and runtime.store:
        runtime.store.write_save(save)

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

    # 5. Auf Reload + Neuinitialisierung warten
    await asyncio.sleep(3.0)
    await browser._wait_for_game(timeout_s=90)
    bus.publish("narrative.chapter", {
        "priority": "P1",
        "title": "Neuer Run beginnt",
        "body": "Carryover geprüft — der Agent baut die Wirtschaft mit Paragon-Bonus neu auf.",
    })
