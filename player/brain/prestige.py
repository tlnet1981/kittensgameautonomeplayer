"""Ports der permanenten Prestige-Boni aus der Referenzversion
(gamefiles/, Kittens Game 1.5.0.2).

Eigenes Modul (#43): timecrystal.py braucht paragon_production_ratio für
die zustandsabhängige Paragon-Bewertung (Regel D), darf aber reset.py
nicht importieren — reset zieht den Driver (player.driver.actor) in jeden
Import. reset.py re-exportiert beide Funktionen unverändert.
"""

from __future__ import annotations


def _limited_dr(effect: float, limit: float) -> float:
    """Port von game.js getLimitedDR (Zeilen 2303-2323): die ersten 75 %
    des Limits sind frei von Diminishing Returns; der Rest nähert sich
    asymptotisch +25 % — (1 − δ/(x+δ))·δ mit δ = 0.25·limit."""
    abs_effect = abs(effect)
    max_undiminished = 0.75 * limit
    if abs_effect <= max_undiminished:
        return effect
    diminished = abs_effect - max_undiminished
    delta = 0.25 * limit
    total = max_undiminished + (1 - delta / (diminished + delta)) * delta
    return -total if effect < 0 else total


def paragon_production_ratio(paragon: float, burned_paragon: float = 0.0, *,
                             paragon_ratio: float = 1.0,
                             dark_future: bool = False) -> float:
    """Port von prestige.js getParagonProductionRatio (Zeilen 523-534):
    +1 % Produktion je Paragon (×paragonRatio), gekappt per getLimitedDR
    auf 2×paragonRatio; burnedParagon ebenso mit Kappe 1× (4× im Dark
    Future). paragonRatio-Effekte (Perks/Challenges) stehen nicht im
    Snapshot → Aufrufer nutzen konservativ 1.0 (dokumentiert)."""
    prod = _limited_dr(paragon * 0.010 * paragon_ratio, 2 * paragon_ratio)
    burned_cap = (4 if dark_future else 1) * paragon_ratio
    prod += _limited_dr(burned_paragon * 0.010 * paragon_ratio, burned_cap)
    return prod
