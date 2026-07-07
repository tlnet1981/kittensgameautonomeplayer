"""Religion-Endgame-Ökonomie: TAP, Alicorn-/Tear-Konvertierung, Pacts
(Spielmechanik-Spec 15.2–15.5).

Alle Formeln stammen aus der Referenzversion (gamefiles/, Kittens Game
1.5.0.2) und zitieren die Datei/Zeile. Fehlen Snapshot-Daten, liefern die
Funktionen konservative Fallbacks (nichts tun) statt zu raten.

TAP (15.2, gamefiles/js/religion.js):
- Transcend (religion.js:1624-1653): kostet `_getTranscendNextPrice()`
  Epiphany (faithRatio) und erhöht transcendenceTier um 1. Preisformel
  (religion.js:1655-1661 + game.js:5277 getInverseUnlimitedDR):
      totalPrice(t) = 0.05 · x · (x+1)   mit x = e^t / 10
      nextPrice(t)  = totalPrice(t+1) − totalPrice(t)
- Adore (religion.js:1617-1621 _resetFaithInternal): Epiphany-Gewinn =
  worship / 1e6 · (tt+1)² · bonusRatio — der Tier wirkt QUADRATISCH auf
  alle künftigen Adores. Genau daraus entsteht die Transcend-Bilanz:
  Transcend lohnt vor einem Adore, wenn der Mehrgewinn des nächsten Adore
  ((tt+2)² statt (tt+1)²) den Epiphany-Preis übersteigt.
- Praise (religion.js:1569-1583): Faith → Worship × (1 + ApocryphaBonus);
  ApocryphaBonus = getUnlimitedDR(faithRatio, 0.1) · 0.1 (religion.js:1523).

Konvertierungen (15.3/15.4, gamefiles/js/religion.js:3028-3100):
- Alicorn-Opfer: 25 Alicorns → (1 + tcRefineRatio) Time Crystals.
- Tear-Refinement: 10 000 Tears → 1 Black Liquid Sorrow (Sorrow-Cap-gated,
  religion.js:2262-2311). Sorrow `persists: true` (resources.js:286-291),
  Tears/Alicorns `persists: false` (resources.js:236-257) — vor einem Reset
  ist die Konvertierung daher trivial werterhaltend.

Pacts (15.5, gamefiles/js/religion.js pactsManager):
- Preis je Pact: 100 Relic, priceRatio fest 1 (pactsManager.constructor).
- Upkeep: pactNecrocornConsumption = −0.0005 Necrocorn/Tag je Pact
  (religion.js:1458-1459 effectsBase).
- Debt: fractureNecrocornDeficit = 50; getDebtPenaltyRatio ≈ 1 − deficit/50
  skaliert ALLE Pyramid-Pact-Effekte herunter (religion.js pactsManager).
- Pact-Effekte wirken über die Black Pyramid × max(TT−24, 1)
  (religion.js:1000-1012 cashPreDeficitEffects).
- Siphoning ist die Policy "siphoning" (Effekt repayDebtOnNecrocornGeneration,
  religion.js:374-392): korruptierte Necrocorns tilgen sofort die Schuld.
"""

from __future__ import annotations

import math

from player.state import access as A

from . import shadow, simulate

EPS = 1e-9

# UnlimitedDR-Stripe der Epiphany-Formeln (religion.js:1524/1656):
DR_STRIPE = 0.1
# Adore-BonusRatio des Agenten — wie reset.py/actor: resetFaith(1.01, false):
ADORE_BONUS_RATIO = 1.01
# Adore erst ab diesem Worship-Stand (Altverhalten aus reset.py TAP-light):
ADORE_MIN_WORSHIP = 1000.0
# Praise nur, wenn nennenswert Live-Faith im Pool liegt:
PRAISE_MIN_FAITH = 1.0

# Batchgrößen der Konvertierungen (religion.js:3032 / 3057 / 3021):
ALICORN_SAC_BATCH = 25.0
TEARS_REFINE_BATCH = 10000.0
UNICORN_SAC_BATCH = 2500.0

# Pacts (religion.js pactsManager):
PACT_NECROCORN_PER_DAY = 0.0005      # effectsBase pactNecrocornConsumption (1459)
FRACTURE_DEFICIT = 50.0              # fractureNecrocornDeficit (Manager-Feld)
SECONDS_PER_DAY = 2.0                # wie state/derived.py / simulate.py

# REFERENZSCHÄTZUNG (ehrlich gekennzeichnet, wie challenge.py): Sekundenwert
# eines Necrocorns ohne λ-Daten. Corruption erzeugt ~1 Necrocorn in Tagen
# bis Wochen Spielzeit — 1800 s ist bewusst hoch angesetzt, damit Upkeep
# ohne bessere Daten abschreckend wirkt (konservativ gegen Pact-Käufe).
NECROCORN_VALUE_S = 1800.0

# Aggregierte Nutzenraten je Pact: Summe der BREITEN Ratio-Effekte aus
# religion.js (pactsManager.pacts, effects-Blöcke). Schmale Spezialeffekte
# (BlackLibraryBoost, UniversalKnowHow, umbraBoost …) gehen als
# REFERENZSCHÄTZUNG mit Gewicht 0.2 der nominellen Ratio ein — sie wirken
# nur auf Teilsysteme, nicht auf die Gesamtproduktion.
PACT_UTILITY_RATIO: dict[str, float] = {
    # pactGlobalResourceRatio 0.0005 (religion.js pactOfCleansing.effects):
    "pactOfCleansing": 0.0005,
    # pactGlobalProductionRatio 0.0005 (pactOfDestruction.effects):
    "pactOfDestruction": 0.0005,
    # pactFaithRatio 0.001 — nur Faith → Gewicht 0.2 (REFERENZSCHÄTZUNG):
    "pactOfExtermination": 0.001 * 0.2,
    # pactBlackLibraryBoost 0.0005 + pactSpaceCompendiumRatio 0.001 — nur
    # Teilsysteme → Gewicht 0.2 (REFERENZSCHÄTZUNG):
    "pactOfPurity": (0.0005 + 0.001) * 0.2,
    # pactcraftRatio 0.001 (+ UniversalKnowHow) — Gewicht 0.2:
    "pactOfArcane": 0.001 * 0.2,
    # pactPerYearRatio 0.003 (+ umbraBoost/pacttimeRatio) — Gewicht 0.2:
    "pactOfChronicler": 0.003 * 0.2,
    # payDebt/fractured sind special-Einträge, keine Kauf-Kandidaten.
}


# ================================================================ Grundformeln

def unlimited_dr(value: float, stripe: float) -> float:
    """getUnlimitedDR (gamefiles/game.js:5270-5276)."""
    return (math.sqrt(1.0 + (value / stripe) * 8.0) - 1.0) / 2.0


def inverse_unlimited_dr(value: float, stripe: float) -> float:
    """getInverseUnlimitedDR (gamefiles/game.js:5277-5279)."""
    return stripe / 2.0 * value * (value + 1.0)


def transcend_total_price(tier: int) -> float:
    """_getTranscendTotalPrice (religion.js:1655-1657)."""
    return inverse_unlimited_dr(math.exp(tier) / 10.0, DR_STRIPE)


def transcend_next_price(tier: int) -> float:
    """_getTranscendNextPrice (religion.js:1659-1661): Epiphany-Kosten des
    Aufstiegs von `tier` auf `tier + 1`."""
    return transcend_total_price(tier + 1) - transcend_total_price(tier)


def apocrypha_bonus(epiphany: float) -> float:
    """getApocryphaBonus (religion.js:1523-1525)."""
    return unlimited_dr(max(0.0, epiphany), DR_STRIPE) * 0.1


# ================================================================ Snapshot-Zugriff

def _religion(snap: dict) -> dict:
    rel = snap.get("religion")
    return rel if isinstance(rel, dict) else {}


def _ru_on(snap: dict, name: str) -> bool:
    """Religion-Upgrade aktiv? (religion.upgrades aus snapshot.js)."""
    for u in _religion(snap).get("upgrades", []):
        if u.get("name") == name:
            return bool(u.get("on") or u.get("val"))
    return False


def _apocrypha_on(snap: dict) -> bool:
    """Apocrypha aktiv? Direktes Snapshot-Flag (religion.apocrypha.on aus
    snapshot.js) oder der Upgrade-Listen-Eintrag „apocripha" (sic)."""
    apo = _religion(snap).get("apocrypha")
    if isinstance(apo, dict) and apo.get("on"):
        return True
    return _ru_on(snap, "apocripha")


def _transcendence_on(snap: dict) -> bool:
    """Transcendence-RU aktiv? (Gate von religion.transcend, religion.js:1626)."""
    if _religion(snap).get("transcendenceOn"):
        return True
    return _ru_on(snap, "transcendence")


def _ziggurat_val(snap: dict, name: str) -> int:
    for z in _religion(snap).get("ziggurat", []):
        if z.get("name") == name:
            return int(z.get("val", 0))
    return 0


def _ziggurat_unlocked(snap: dict, name: str) -> bool:
    for z in _religion(snap).get("ziggurat", []):
        if z.get("name") == name:
            return bool(z.get("unlocked") or z.get("val"))
    return False


def has_anachronomancy(snap: dict) -> bool:
    return any(p.get("name") == "anachronomancy" and p.get("researched")
               for p in snap.get("prestige", {}).get("perks", []))


def tc_survives_reset(snap: dict) -> bool:
    """TC-Schutzgate (I-02, wie reset.evaluate): Time Crystals überleben den
    Reset nur mit Anachronomancy (game.js _resetInternal: timeCrystal wird
    ohne den Perk NICHT übertragen); < 3 TC gelten als unkritisch."""
    return A.res_value(snap, "timeCrystal") < 3 or has_anachronomancy(snap)


# ================================================================ TAP (15.2)

def _adore_gain(worship: float, tier: int, transcendence_on: bool) -> float:
    """Epiphany-Gewinn eines Adore (religion.js:1617-1621): worship/1e6 ·
    (tt+1)² · bonusRatio; ohne Transcendence-RU zählt tt = 0."""
    ttp1 = (tier if transcendence_on else 0) + 1
    return worship / 1e6 * ttp1 * ttp1 * ADORE_BONUS_RATIO


def _worship_recovery_seconds(snap: dict, apo_after: float,
                              worship: float) -> float:
    """Wiederanlaufzeit der Worship nach TAP (EV-Projektion): Zeit, bis die
    Faith-Produktion — über Praise mit dem NEUEN Apocrypha-Bonus gewandelt
    (religion.js:1571) — den heutigen Worship-Stand wieder erreicht.
    Näherung: effektive Faith-Rate aus simulate.project über den
    Run-Horizont (Cap-Klemmen wirken konservativ), sonst Netto-perSec."""
    if worship <= 0:
        return 0.0
    if simulate.has_projection_data(snap):
        horizon = shadow.run_horizon(snap)
        proj = simulate.project(snap, horizon)
        faith_now = A.res_value(snap, "faith")
        rate = max(0.0, proj.final.get("faith", faith_now) - faith_now) / max(horizon, EPS)
    else:
        rate = max(0.0, A.res_rate(snap, "faith"))
    if rate <= EPS:
        return math.inf
    return worship / (rate * (1.0 + apo_after))


def transcend_value(snap: dict) -> dict:
    """Epiphany-/Worship-Bilanz eines Transcend VOR dem Adore (Spec 15.2).

    Kriterien:
    - erreichbar: Transcendence-RU aktiv UND epiphany > nextPrice
      (strikt >, wie religion.js:1635).
    - Bilanz: Der Tier wirkt quadratisch auf den Adore-Gewinn
      (religion.js:1618 ttPlus1²). balance = adoreGain(tier+1) −
      adoreGain(tier) − nextPrice, alles in Epiphany-Einheiten. Die
      verbleibende Struktur verbessert den Restplan genau dann, wenn
      balance > 0 — nach TAP steht mehr permanente Epiphany da als ohne
      Transcend.
    - Wiederanlaufzeit: Worship ist nach Adore in beiden Fällen weg; die
      prognostizierte Wiederaufbauzeit (EV-Projektion der Faith-Produktion)
      muss innerhalb des Run-Horizonts liegen, sonst kein Transcend
      (Milestone-Zeit würde sich verschlechtern).
    """
    rel = _religion(snap)
    tier = int(rel.get("transcendenceTier", 0) or 0)
    worship = float(rel.get("worship", 0.0) or 0.0)
    epiphany = float(rel.get("epiphany", 0.0) or 0.0)
    transcendence_on = _transcendence_on(snap)
    # Spielwert bevorzugen (snapshot.js: religion.transcendenceNextPrice),
    # sonst die Referenzformel:
    price = rel.get("transcendenceNextPrice")
    if not isinstance(price, (int, float)) or price <= 0:
        price = transcend_next_price(tier)
    reachable = transcendence_on and epiphany > price
    gain_old = _adore_gain(worship, tier, transcendence_on)
    gain_new = _adore_gain(worship, tier + 1, True)
    balance = gain_new - gain_old - price
    apo_after = apocrypha_bonus(max(0.0, epiphany - price + gain_new))
    recovery_s = _worship_recovery_seconds(snap, apo_after, worship)
    recovery_ok = recovery_s <= shadow.run_horizon(snap)
    worth = bool(reachable and balance > 0 and recovery_ok)
    if not transcendence_on:
        reason = "Transcendence-Upgrade fehlt (religion.js:1626)"
    elif not reachable:
        reason = (f"Epiphany {epiphany:.4f} ≤ Preis {price:.4f} "
                  f"(Tier {tier} → {tier + 1})")
    elif balance <= 0:
        reason = (f"Bilanz {balance:+.4f} Epiphany — Adore-Mehrgewinn "
                  f"deckt den Tier-Preis nicht (15.2)")
    elif not recovery_ok:
        reason = (f"Worship-Wiederanlauf {recovery_s:.0f} s über dem "
                  f"Run-Horizont — Milestone-Zeit würde leiden (15.2)")
    else:
        reason = (f"Tier {tier} → {tier + 1}: Bilanz {balance:+.4f} Epiphany, "
                  f"Wiederanlauf {recovery_s:.0f} s")
    return {
        "worth": worth,
        "reachable": bool(reachable),
        "tier": tier,
        "nextPrice": round(float(price), 6),
        "epiphany": epiphany,
        "adoreGainOld": round(gain_old, 6),
        "adoreGainNew": round(gain_new, 6),
        "balance": round(balance, 6),
        "recoveryS": (None if math.isinf(recovery_s) else round(recovery_s, 1)),
        "reason": reason,
    }


def tap_plan(snap: dict) -> list[dict]:
    """TAP-Schritte in Spec-Reihenfolge Transcend → Adore → Praise (15.2),
    jeweils mit Begründung und Wert. Leere Liste = TAP nicht anwendbar."""
    steps: list[dict] = []
    rel = _religion(snap)
    worship = float(rel.get("worship", 0.0) or 0.0)
    epiphany = float(rel.get("epiphany", 0.0) or 0.0)
    tier = int(rel.get("transcendenceTier", 0) or 0)
    transcendence_on = _transcendence_on(snap)

    tv = transcend_value(snap)
    adore_tier = tier
    epiphany_after = epiphany
    if tv["worth"]:
        adore_tier = tier + 1
        epiphany_after = epiphany - tv["nextPrice"]
        steps.append({"step": "transcend", "value": tv["balance"],
                      "reason": tv["reason"]})

    if _apocrypha_on(snap) and worship >= ADORE_MIN_WORSHIP:
        gain = _adore_gain(worship, adore_tier, transcendence_on or tv["worth"])
        epiphany_after += gain
        steps.append({
            "step": "adore", "value": round(gain, 6),
            "reason": (f"Worship {worship:.0f} → +{gain:.4f} permanente "
                       f"Epiphany (religion.js:1617-1621, Tier {adore_tier})"),
        })

    faith_live = A.res_value(snap, "faith")
    if faith_live >= PRAISE_MIN_FAITH:
        worship_gain = faith_live * (1.0 + apocrypha_bonus(epiphany_after))
        steps.append({
            "step": "praise", "value": round(worship_gain, 2),
            "reason": (f"Rest-Faith {faith_live:.0f} → +{worship_gain:.0f} "
                       f"Worship (religion.js:1569-1583) statt Verfall"),
        })
    return steps


# ================================================================ Konvertierungen

def alicorn_conversion_due(snap: dict, lam: dict[str, float] | None,
                           pre_reset: bool = False) -> tuple[bool, dict]:
    """Alicorns → Time Crystals (Spec 15.4).

    Regel: Konvertieren genau dann, wenn der λ-Grenzwert der Time Crystals
    den Grenzwert der verbleibenden Alicorn-/Corruption-Produktion übersteigt
    UND der TC-Bestand den nächsten Reset überlebt (Anachronomancy — Gate
    wie reset.py, game.js _resetInternal überträgt TC nur mit dem Perk).

    pre_reset=True: unmittelbar vor dem Reset ist der Haltewert der
    Alicorns 0 (persists: false, resources.js:236-240) — mit Anachronomancy
    ist die Konvertierung dann immer fällig. Ohne λ-Daten im Normalbetrieb:
    konservativ halten (dokumentierter Fallback)."""
    alicorns = A.res_value(snap, "alicorn")
    batches = int(alicorns // ALICORN_SAC_BATCH)
    ratio = float(_religion(snap).get("tcRefineRatio", 0.0) or 0.0)
    yield_per_batch = 1.0 + ratio
    detail: dict = {"batches": batches, "yieldPerBatch": round(yield_per_batch, 4),
                    "gainS": 0.0, "keepS": 0.0}
    if batches < 1:
        detail["reason"] = f"unter Batchgröße ({alicorns:.1f} / {ALICORN_SAC_BATCH:.0f} Alicorns)"
        return False, detail
    if not has_anachronomancy(snap):
        detail["reason"] = ("Anachronomancy fehlt — TC überleben den Reset "
                            "nicht (game.js _resetInternal), halten")
        return False, detail
    lam = lam or {}
    lam_tc = lam.get("timeCrystal", 0.0)
    gain = lam_tc * yield_per_batch
    keep = lam.get("alicorn", 0.0) * ALICORN_SAC_BATCH
    detail["gainS"] = round(gain, 2)
    detail["keepS"] = round(keep, 2)
    if pre_reset:
        detail["reason"] = ("Pre-Reset: Alicorns verfallen (persists: false), "
                            "TC bleiben (Anachronomancy) — konvertieren")
        return True, detail
    if lam_tc <= 0:
        detail["reason"] = "kein λ_TC am aktiven Ziel — konservativ halten"
        return False, detail
    if gain <= keep:
        detail["reason"] = (f"λ-Grenzwert der Alicorn-Produktion ({keep:.1f} s) "
                            f"≥ TC-Gewinn ({gain:.1f} s) — halten (15.4)")
        return False, detail
    detail["reason"] = (f"λ_TC-Gewinn {gain:.1f} s > Alicorn-Haltewert "
                        f"{keep:.1f} s je Batch (15.4)")
    return True, detail


def tears_refine_due(snap: dict, lam: dict[str, float] | None,
                     pre_reset: bool = False) -> tuple[bool, dict]:
    """Tears → Black Liquid Sorrow (10 000 : 1, religion.js:3052-3062),
    Grenzwertregel analog 15.4. Gates wie im Spiel: Black Pyramid
    freigeschaltet (RefineBtn-Sichtbarkeit, religion.js:3058) und Sorrow
    unter dem Cap (religion.js:2271-2276). Vor dem Reset trivial fällig:
    Tears persists: false, Sorrow persists: true (resources.js)."""
    tears = A.res_value(snap, "tears")
    batches = int(tears // TEARS_REFINE_BATCH)
    detail: dict = {"batches": batches, "gainS": 0.0, "keepS": 0.0}
    if batches < 1:
        detail["reason"] = f"unter Batchgröße ({tears:.0f} / {TEARS_REFINE_BATCH:.0f} Tears)"
        return False, detail
    if not _ziggurat_unlocked(snap, "blackPyramid"):
        detail["reason"] = "Black Pyramid nicht freigeschaltet (religion.js:3058)"
        return False, detail
    sorrow = A.resource(snap, "sorrow")
    if sorrow is not None and sorrow.get("maxValue", 0) > 0:
        headroom = int(sorrow["maxValue"] - sorrow.get("value", 0))
        if headroom < 1:
            detail["reason"] = "Sorrow am Cap (religion.js:2271-2276)"
            return False, detail
        batches = min(batches, headroom)
        detail["batches"] = batches
    lam = lam or {}
    gain = lam.get("sorrow", 0.0) * 1.0
    keep = lam.get("tears", 0.0) * TEARS_REFINE_BATCH
    detail["gainS"] = round(gain, 2)
    detail["keepS"] = round(keep, 2)
    if pre_reset:
        detail["reason"] = ("Pre-Reset: Tears verfallen (persists: false), "
                            "Sorrow bleibt (persists: true) — refinen")
        return True, detail
    if gain <= 0:
        detail["reason"] = "kein λ_Sorrow am aktiven Ziel — konservativ halten"
        return False, detail
    if gain <= keep:
        detail["reason"] = (f"Tear-Haltewert {keep:.1f} s ≥ BLS-Gewinn "
                            f"{gain:.1f} s — halten")
        return False, detail
    detail["reason"] = f"BLS-Gewinn {gain:.1f} s > Tear-Haltewert {keep:.1f} s"
    return True, detail


# ================================================================ Pacts (15.5)

def _pacts_section(snap: dict) -> dict | None:
    p = snap.get("pacts")
    if not isinstance(p, dict) or "list" not in p or "necrocorns" not in p:
        return None
    return p


def _pact_utility_seconds(ratio_sum: float, snap: dict, horizon: float) -> float:
    """Nutzwert in Sekunden: eine globale Produktionsratio r über Horizont H
    spart r·H Sekunden Produktionszeit. Pact-Effekte wirken über die Black
    Pyramid × max(TT−24, 1) (religion.js:1000-1012)."""
    tier = int(_religion(snap).get("transcendenceTier", 0) or 0)
    tt_mod = max(tier - 24, 1)
    pyramids = _ziggurat_val(snap, "blackPyramid")
    return ratio_sum * tt_mod * pyramids * horizon


def pact_value(snap: dict, name: str, lam: dict[str, float] | None = None,
               horizon: float | None = None) -> dict | None:
    """PactValue = ΔBlackPyramidUtility − DebtCost − UpkeepCost −
    AlternativeNecrocornValue (Spec 15.5), alles in Sekunden.

    None ohne Pact-Snapshot-Daten oder für special-Pacts (payDebt/fractured)
    — dann bleibt die Pact-Ökonomie inaktiv (kein Kauf ohne Daten).
    - ΔBPU: Nutzenrate des Pacts (PACT_UTILITY_RATIO, religion.js-Effekte)
      × max(TT−24,1) × Pyramiden × Horizont.
    - UpkeepCost: 0.0005 Necrocorn/Tag (religion.js:1459) über den Horizont,
      bewertet mit λ_necrocorn (Fallback NECROCORN_VALUE_S).
    - DebtCost: prognostiziertes Defizit (Bestand vs. Verbrauch ALLER Pacts
      inkl. des neuen) / 50 (fractureNecrocornDeficit) × gefährdeter
      Pyramid-Nutzen — getDebtPenaltyRatio skaliert alle Pact-Effekte.
    - AlternativeNecrocornValue: Upfront-Necrocorn-Kosten
      (pactNecrocornUpfrontCost, PactsBtnController.getPrices) × Necrocorn-Wert.
    """
    pacts = _pacts_section(snap)
    if pacts is None:
        return None
    ratio = PACT_UTILITY_RATIO.get(name)
    if ratio is None:
        return None
    if pacts.get("fractured"):
        return {"name": name, "pactValueS": -math.inf, "positive": False,
                "reason": "Pacts fractured — keine Käufe mehr (religion.js)"}
    horizon = horizon or shadow.run_horizon(snap)
    days = horizon / SECONDS_PER_DAY
    delta_bpu = _pact_utility_seconds(ratio, snap, horizon)
    necro_value = (lam or {}).get("necrocorn", 0.0) or NECROCORN_VALUE_S
    consumed = PACT_NECROCORN_PER_DAY * days
    upkeep = consumed * necro_value
    upfront = float(pacts.get("necrocornUpfrontCost", 0.0) or 0.0)
    alt_necro = upfront * necro_value
    active = sum(int(p.get("on", 0) or 0) for p in pacts.get("list", [])
                 if p.get("name") in PACT_UTILITY_RATIO)
    existing_util = sum(
        PACT_UTILITY_RATIO[p["name"]] * int(p.get("on", 0) or 0)
        for p in pacts.get("list", []) if p.get("name") in PACT_UTILITY_RATIO)
    existing_util_s = _pact_utility_seconds(existing_util, snap, horizon)
    deficit_now = float(pacts.get("necrocornDeficit", 0.0) or 0.0)
    stock = float(pacts.get("necrocorns", 0.0) or 0.0)
    projected_deficit = max(0.0, deficit_now
                            + PACT_NECROCORN_PER_DAY * (active + 1) * days
                            - stock)
    debt_cost = min(1.0, projected_deficit / FRACTURE_DEFICIT) \
        * (delta_bpu + existing_util_s)
    value = delta_bpu - debt_cost - upkeep - alt_necro
    return {
        "name": name,
        "deltaBpuS": round(delta_bpu, 2),
        "debtCostS": round(debt_cost, 2),
        "upkeepCostS": round(upkeep, 2),
        "altNecrocornS": round(alt_necro, 2),
        "projectedDeficit": round(projected_deficit, 4),
        "pactValueS": round(value, 2),
        "positive": value > 0,
    }


def siphoning_due(snap: dict, lam: dict[str, float] | None = None) -> tuple[bool, dict]:
    """Siphoning-Regel (Spec 15.5): aktivieren, wenn die Verringerung der
    Schuldkosten größer ist als der unmittelbare Nutzen freier Necrocorns.

    Mechanik der Referenz (religion.js:374-392): Mit Siphoning tilgen
    korruptierte Necrocorns SOFORT die Schuld (repayDebtOnNecrocornGeneration)
    statt in den Bestand zu gehen. Schuldkosten-Reduktion ≈ Debt-Penalty-
    Anteil (deficit/50, getDebtPenaltyRatio) × gefährdeter Pyramid-Nutzen;
    entgangener Nutzen = deficit × Necrocorn-Wert. Ohne Pact-Daten:
    dokumentiert konservativ AUS."""
    pacts = _pacts_section(snap)
    detail: dict = {"reductionS": 0.0, "foregoneS": 0.0}
    if pacts is None:
        detail["reason"] = "keine Pact-Daten im Snapshot — Siphoning bleibt konservativ AUS"
        return False, detail
    if pacts.get("siphoning"):
        detail["reason"] = "Siphoning-Policy bereits aktiv"
        return False, detail
    deficit = float(pacts.get("necrocornDeficit", 0.0) or 0.0)
    if deficit <= 0:
        detail["reason"] = "keine Necrocorn-Schuld — kein Siphoning nötig"
        return False, detail
    horizon = shadow.run_horizon(snap)
    existing_util = sum(
        PACT_UTILITY_RATIO[p["name"]] * int(p.get("on", 0) or 0)
        for p in pacts.get("list", []) if p.get("name") in PACT_UTILITY_RATIO)
    reduction = min(1.0, deficit / FRACTURE_DEFICIT) \
        * _pact_utility_seconds(existing_util, snap, horizon)
    necro_value = (lam or {}).get("necrocorn", 0.0) or NECROCORN_VALUE_S
    foregone = deficit * necro_value
    detail["reductionS"] = round(reduction, 2)
    detail["foregoneS"] = round(foregone, 2)
    if reduction > foregone:
        detail["reason"] = (f"Schuldkosten-Reduktion {reduction:.0f} s > "
                            f"entgangener Necrocorn-Nutzen {foregone:.0f} s (15.5)")
        return True, detail
    detail["reason"] = (f"Necrocorn-Nutzen {foregone:.0f} s ≥ Schuldkosten-"
                        f"Reduktion {reduction:.0f} s — Siphoning AUS")
    return False, detail
