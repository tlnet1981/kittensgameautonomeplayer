"""Challenge-Katalog und -Bewertung (Spielmechanik-Spec 18.1–18.4).

Katalog CHALLENGE_PROFILES: aus gamefiles/js/challenges.js (challenges-
Array, Zeilen 42-489 der Referenzversion 1.5.0.2 r3). Je Challenge:
Einschränkung und Zielbedingung als Text (direkt aus calculateEffects /
checkCompletionCondition abgelesen), die Erstbelohnung als maschinell
prüfbare Referenz (Effektname + Wert aus challenges.js) und zwei
REFERENZSCHÄTZUNGEN (ehrlich gekennzeichnet, keine Spielkonstanten):

- reward_tf_reduction_s: ΔE[T_F]-Proxy — wie viele Sekunden erwartete
  Restzeit bis zur Progressionsfront der permanente Erstbelohnungseffekt
  spart. Grobe, dokumentierte Gewichtung (kein λ verfügbar: die Effekte
  wirken run-übergreifend, außerhalb des Ziel-λ des laufenden Runs).
- est_completion_s: erwartete Completion-Zeit eines dedizierten
  Challenge-Runs. Bewusst KONSERVATIV (Stunden), damit CHALLENGE_RUN im
  Meta-Scoring nur gewinnt, wenn PRICE_RATIO/PARAGON schlechter abschneiden.

Auswahlregel (18.2):  ChallengeValue(c) = reward_tf_reduction_s /
est_completion_s — nur Erstabschlüsse (researched == False).

Kombinationen (18.3): Kombination erst, wenn eine Simulation sie besser
bewertet als getrennte Abschlüsse. Unsere EV-Projektion simuliert keine
Challenge-Einschränkungen ⇒ es wird IMMER genau EINE Challenge gewählt
(dokumentierte Vereinfachung; die 18.3-Bedingung „Summe separater
Abschlüsse" ist damit trivial erfüllt).

Iron Will ist ausgenommen: der Button resettet SOFORT statt pending zu
togglen (challenges.js:885-888, applyPending(true)) und hat eigene Regeln.

Fallbacks: ohne `challenges`-Sektion im Snapshot liefern alle Funktionen
None/0/False — kein Kandidat, kein Crash.
"""

from __future__ import annotations

# Iron Will: Sonderregeln, kein pending-Toggle (challenges.js:885-888).
EXCLUDED = frozenset({"ironWill"})

# name → Profil. restriction/goal/reward zitieren challenges.js;
# die *_s-Werte sind REFERENZSCHÄTZUNGEN (siehe Modul-Docstring).
CHALLENGE_PROFILES: dict[str, dict] = {
    "winterIsComing": {
        "restriction": "Ewiger Winter: coldChance 5 %, coldHarshness −2 % "
                       "(challenges.js calculateEffects, active-Zweig)",
        "goal": "Helios erreichen (challenges.js:83: "
                "game.space.getPlanet('helios').reached)",
        "reward": {"springCatnipRatio": 0.05, "summerSolarFarmRatio": 0.05,
                   "coldChance": 0, "coldHarshness": 0},
        "reward_tf_reduction_s": 2400.0,     # REFERENZSCHÄTZUNG
        "est_completion_s": 6 * 3600.0,      # REFERENZSCHÄTZUNG
    },
    "anarchy": {
        "restriction": "Kein Leader, Kitten zu 50 %+ faul (kittenLaziness, "
                       "challenges.js:100-107)",
        "goal": "AI Core bauen (challenges.js:109: game.bld.get('aiCore').val > 0)",
        "reward": {"masterSkillMultiplier": 0.2},
        "reward_tf_reduction_s": 2400.0,     # REFERENZSCHÄTZUNG
        "est_completion_s": 8 * 3600.0,      # REFERENZSCHÄTZUNG
    },
    "energy": {
        "restriction": "Energieverbrauch +10 % (energyConsumptionIncrease, "
                       "challenges.js:127-134)",
        "goal": "Volle Energie-Kette: Pasture/Aqueduct Stage 1, Steamworks, "
                "Magneto, Reactor, Satellit+solarSatellites, Sunlifter, "
                "Tectonic, HR Harvester (challenges.js:136-148)",
        "reward": {"energyConsumptionRatio": -0.02},
        "reward_tf_reduction_s": 2100.0,     # REFERENZSCHÄTZUNG
        "est_completion_s": 8 * 3600.0,      # REFERENZSCHÄTZUNG
    },
    "atheism": {
        "restriction": "Kein Religion-Bonus, Max-Caps und Happiness gesenkt "
                       "(challenges.js:164-177)",
        "goal": "Reset mit Cryochambers/Stasis-Pod (challenges.js:179-181, "
                "checkCompletionConditionOnReset — wird erst BEIM Reset erfüllt)",
        "reward": {"faithSolarRevolutionBoost": 0.1},
        "reward_tf_reduction_s": 3600.0,     # REFERENZSCHÄTZUNG
        "est_completion_s": 14 * 3600.0,     # REFERENZSCHÄTZUNG
    },
    "1000Years": {
        "restriction": "Shatter-Kosten +50 %, Void-Kosten +0.4 "
                       "(challenges.js:205-212)",
        "goal": "Jahr 1000 per Shatter erreichen (time.js:728-729; der "
                "Kalender klemmt aktiv bei Jahr 500, calendar.js:457)",
        "reward": {"shatterCostReduction": -0.02, "heatEfficiency": 0.1,
                   "heatCompression": 0.05, "temporalPressCap": 10},
        "reward_tf_reduction_s": 1800.0,     # REFERENZSCHÄTZUNG
        "est_completion_s": 12 * 3600.0,     # REFERENZSCHÄTZUNG
    },
    "blackSky": {
        "restriction": "Satelliten-Malus (bskSattelitePenalty, "
                       "challenges.js:242-250)",
        "goal": "Space Beacon > bisherige Abschlusszahl (challenges.js:252-254)",
        "reward": {"corruptionBoostRatioChallenge": 0.1},
        "reward_tf_reduction_s": 2400.0,     # REFERENZSCHÄTZUNG
        "est_completion_s": 14 * 3600.0,     # REFERENZSCHÄTZUNG
    },
    "pacifism": {
        "restriction": "Keine Waffen, Policies/Embassies teurer "
                       "(policyFakeBought/embassyFakeBought, challenges.js:276-294)",
        "goal": "Outer Space Treaty erforschen; Abschluss BEIM Reset "
                "(challenges.js:299-312, checkCompletionConditionOnReset)",
        "reward": {"alicornPerTickRatio": 0.1, "tradeKnowledge": 1},
        "reward_tf_reduction_s": 2700.0,     # REFERENZSCHÄTZUNG
        "est_completion_s": 12 * 3600.0,     # REFERENZSCHÄTZUNG
    },
    "unicornTears": {
        "restriction": "Bonfire-/Science-/Workshop-Preise in Tears "
                       "(challenges.js:350-368)",
        "goal": "1 Necrocorn (challenges.js:450-452: "
                "game.resPool.get('necrocorn').value >= 1)",
        "reward": {"zigguratIvoryPriceRatio": -0.003},
        "reward_tf_reduction_s": 1500.0,     # REFERENZSCHÄTZUNG
        "est_completion_s": 14 * 3600.0,     # REFERENZSCHÄTZUNG
    },
    "postApocalypse": {
        "restriction": "Start mit maximaler Pollution, arrivalSlowdown +10 "
                       "(challenges.js:463-470)",
        "goal": "Pollution auf 0 (challenges.js:475-477: "
                "game.bld.cathPollution == 0)",
        "reward": {"terraformingInsight/cryochamberExtraction":
                   "Policies nur nach Sieg (challenges.js:483-488)"},
        "reward_tf_reduction_s": 1500.0,     # REFERENZSCHÄTZUNG
        "est_completion_s": 14 * 3600.0,     # REFERENZSCHÄTZUNG
    },
}


# ------------------------------------------------------------ Snapshot-Zugriff

def challenge_list(snap: dict) -> list[dict]:
    """Challenge-Liste aus dem Snapshot ([] ohne Daten — Fallback)."""
    ch = snap.get("challenges")
    if not isinstance(ch, dict):
        return []
    return ch.get("list") or []


def get(snap: dict, name: str) -> dict | None:
    return next((c for c in challenge_list(snap) if c.get("name") == name), None)


def label_of(snap: dict, name: str) -> str:
    c = get(snap, name)
    return (c or {}).get("label") or name


def active_challenge(snap: dict) -> dict | None:
    """Aktive Challenge des laufenden Runs (Iron Will ausgenommen)."""
    for c in challenge_list(snap):
        if c.get("active") and c.get("name") not in EXCLUDED:
            return c
    return None


def challenges_available(snap: dict) -> bool:
    """Sind Challenges für den Spieler überhaupt erreichbar? Der Challenges-
    Tab hängt am Adjustment-Bureau-Perk (gamefiles/game.js:2680:
    challengesTab.visible = adjustmentBureau.researched || .reserve)."""
    for t in snap.get("tabs", []):
        if t.get("id") == "Challenges" and t.get("visible"):
            return True
    return any(p.get("name") == "adjustmentBureau" and p.get("researched")
               for p in snap.get("prestige", {}).get("perks", []))


# ------------------------------------------------------------ Bewertung (18.2)

def est_completion_s(name: str) -> float:
    """Erwartete Completion-Zeit (Referenzkonstante, konservativ)."""
    prof = CHALLENGE_PROFILES.get(name)
    return prof["est_completion_s"] if prof else float("inf")


def challenge_value(snap: dict, name: str) -> float:
    """ChallengeValue(c) = ΔE[T_F]-Proxy / E[Completion] (Spec 18.2).

    Nur Erstabschlüsse zählen (researched == False); ohne Snapshot-Daten,
    ohne Profil oder für gesperrte/ausgeschlossene Challenges: 0."""
    if name in EXCLUDED:
        return 0.0
    c = get(snap, name)
    if c is None or c.get("researched") or not c.get("unlocked"):
        return 0.0
    prof = CHALLENGE_PROFILES.get(name)
    if not prof:
        return 0.0
    return prof["reward_tf_reduction_s"] / prof["est_completion_s"]


def best_challenge(snap: dict) -> tuple[str, float] | None:
    """Beste unerledigte Challenge (18.2) — nur EINZELN (18.3-Gate: eine
    Kombination würde erst gewählt, wenn eine Simulation sie besser
    bewertet; unsere Projektion simuliert keine Challenge-Restriktionen,
    also immer einzeln). None ohne Daten oder ohne positiven Wert."""
    scored: list[tuple[float, str]] = []
    for c in challenge_list(snap):
        name = c.get("name")
        if not name or c.get("active"):
            continue
        val = challenge_value(snap, name)
        if val > 0:
            scored.append((val, name))
    if not scored:
        return None
    scored.sort(key=lambda t: (-t[0], t[1]))
    return scored[0][1], scored[0][0]


# ------------------------------------------------------------ Reset-Gate (18.4)

def reset_gate(snap: dict) -> tuple[bool, str]:
    """18.4: Der Reset-Executor prüft unmittelbar vor Reset, dass das SPIEL
    die Challenge als erfüllt markiert hat — eine bloß prognostizierte
    Erfüllung reicht nicht. Signal der Referenzversion: researchChallenge
    (challenges.js:648-665) setzt researched=True/on+=1 und active=False,
    sobald checkCompletionCondition greift.

    Regeln: (a) läuft noch eine Challenge (active) → kein Reset; das gilt
    auch für die On-Reset-Challenges Atheism/Pacifism (deren researched-Flag
    entsteht erst IM Reset — konservativ, dokumentiert). (b) Keine aktive
    Challenge, aber ein researched-Erstabschluss vorhanden → Reset zulässig
    (ohne Run-Gedächtnis ist der researched-Übergang des aktuellen Runs
    nicht von Alt-Abschlüssen unterscheidbar — dokumentierte Näherung)."""
    lst = challenge_list(snap)
    if not lst:
        return False, "Keine Challenge-Daten im Snapshot (18.4)"
    act = active_challenge(snap)
    if act is not None:
        return False, (f"Challenge {act.get('label') or act.get('name')} läuft — "
                       f"das Spiel hat das Ziel noch nicht als erfüllt markiert "
                       f"(researched=False, 18.4)")
    done = sorted(c.get("label") or c.get("name") or "?"
                  for c in lst
                  if c.get("researched") and (c.get("on") or 0) >= 1
                  and c.get("name") not in EXCLUDED)
    if done:
        return True, (f"Spiel markiert {done[0]} als erfüllt "
                      f"(researched-Flag, 18.4) — Challenge-Reset zulässig")
    return False, "Keine aktive oder vom Spiel bestätigte Challenge (18.4)"
