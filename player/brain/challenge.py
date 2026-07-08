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

import math

from player.state import access as A

from . import shadow

# Iron Will: Sonderregeln, kein pending-Toggle (challenges.js:885-888).
EXCLUDED = frozenset({"ironWill"})

# Mindest-Completion eines dedizierten Challenge-Runs (#38): auch wenn die
# Zielbedingung im aktuellen Zustand sofort erfüllbar scheint, braucht ein
# Challenge-RUN den Neustart + Wiederaufbau — Floor analog zur Speedrun-
# Mindestlaufzeit (reset.PARAGON_RUN_MIN_SECONDS).
CHALLENGE_MIN_RUN_S = 1200.0
# Helios-Reisezeit: routeDays = 1200 (gamefiles/js/space.js, helios-Planet)
# × 2 s/Tag (state/derived.py) — die Mission selbst dauert diese Zeit.
HELIOS_ROUTE_S = 1200 * 2.0

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
    """Erwartete Completion-Zeit (Referenzkonstante, konservativ) —
    seit #38 nur noch FALLBACK, wenn completion_eta die Zielobjekte im
    Snapshot gar nicht sieht (Alt-Fixtures, frühe Spielphasen)."""
    prof = CHALLENGE_PROFILES.get(name)
    return prof["est_completion_s"] if prof else float("inf")


# ---- Zielprojektion (#38, Spec 18.2): Completion-Zeit aus dem Zustand ----

def _eta_prices_observed(snap: dict, prices: list[dict]) -> float:
    """ETA eines Preisvektors über BEOBACHTETE Raten (need/rate je Position,
    max über Positionen — wie UNICORN/SHATTER in meta._plan_restzeit;
    die EV-Projektion trackt Space-/Zeitressourcen nicht). Bestand deckt
    alles → 0; eine Position ohne Rate → inf (ehrlich)."""
    worst = 0.0
    for p in prices or []:
        need = p["val"] - A.res_value(snap, p["name"])
        if need <= 0:
            continue
        rate = A.res_rate(snap, p["name"])
        if rate <= 1e-9:
            return math.inf
        worst = max(worst, need / rate)
    return worst


def _space_program(snap: dict, name: str) -> dict | None:
    return next((p for p in snap.get("space", {}).get("programs", [])
                 if p.get("name") == name), None)


def _space_building(snap: dict, name: str) -> dict | None:
    for planet in snap.get("space", {}).get("planets", []):
        for b in planet.get("buildings", []):
            if b.get("name") == name:
                return b
    return None


def _planet(snap: dict, name: str) -> dict | None:
    return next((pl for pl in snap.get("space", {}).get("planets", [])
                 if pl.get("name") == name), None)


def _policy(snap: dict, name: str) -> dict | None:
    return next((p for p in snap.get("policies", [])
                 if p.get("name") == name), None)


def _voidspace(snap: dict, name: str) -> dict | None:
    return next((u for u in snap.get("time", {}).get("voidspace", [])
                 if u.get("name") == name), None)


# Energie-Kette der energy-Challenge (challenges.js:136-148) — Bonfire- und
# Space-Gebäude, die alle > 0 stehen müssen. Stage-Prüfung (Pasture→Solar
# Farm, Aqueduct→Hydro) ist aus dem Snapshot nicht ablesbar — val > 0 des
# Basisgebäudes ist die dokumentierte UNTERE Schranke der Rest-ETA.
_ENERGY_CHAIN_BLD = ("pasture", "aqueduct", "steamworks", "magneto", "reactor")
_ENERGY_CHAIN_SPACE = ("sattelite", "sunlifter", "tectonic", "hrHarvester")


def completion_eta(snap: dict, name: str) -> tuple[float, bool]:
    """(etaS, observable) — Zeit bis zur Zielbedingung der Challenge im
    AKTUELLEN Zustand (#38, Spec 18.2), je Ziel aus challenges.js:

    observable=False: die Zielobjekte fehlen im Snapshot komplett (frühe
    Phase/Alt-Fixture) — der Aufrufer fällt auf die Referenzschätzung
    zurück. observable=True mit math.inf: beobachtbar, aber im aktuellen
    Zustand unerreichbar — ehrlich ∞ statt Konstante."""
    if name == "winterIsComing":
        # Ziel: helios reached (challenges.js:83). Snapshot hat kein
        # reached-Flag; Proxys: Planet gelistet + Gebäude gebaut → erreicht
        # (Gebäude erst nach reached baubar); Planet gelistet ohne Gebäude
        # → Reise läuft (routeDays 1200, space.js:559); sonst über die
        # heliosMission (val ≥ 1 → unterwegs, sonst Preis-ETA + Reise).
        planet = _planet(snap, "helios")
        if planet is not None:
            if any((b.get("val") or 0) > 0 for b in planet.get("buildings", [])):
                return 0.0, True
            return HELIOS_ROUTE_S, True
        mission = _space_program(snap, "heliosMission")
        if mission is not None:
            if (mission.get("val") or 0) >= 1:
                return HELIOS_ROUTE_S, True
            return (_eta_prices_observed(snap, mission.get("prices"))
                    + HELIOS_ROUTE_S), True
        return math.inf, False
    if name == "anarchy":
        # Ziel: aiCore.val > 0 (challenges.js:109).
        b = A.building(snap, "aiCore")
        if b is None:
            return math.inf, False
        if (b.get("val") or 0) > 0:
            return 0.0, True
        return _eta_prices_observed(snap, b.get("prices")), True
    if name == "energy":
        # Ziel: volle Energie-Kette (challenges.js:136-148); max über die
        # Preis-ETAs der fehlenden Glieder; ein Glied unsichtbar → nicht
        # beobachtbar (Referenzschätzung ist dann der ehrliche Stand).
        worst = 0.0
        for bname in _ENERGY_CHAIN_BLD:
            b = A.building(snap, bname)
            if b is None:
                return math.inf, False
            if (b.get("val") or 0) < 1:
                worst = max(worst, _eta_prices_observed(snap, b.get("prices")))
        for sname in _ENERGY_CHAIN_SPACE:
            b = _space_building(snap, sname)
            if b is None:
                return math.inf, False
            if (b.get("val") or 0) < 1:
                worst = max(worst, _eta_prices_observed(snap, b.get("prices")))
        return worst, True
    if name == "atheism":
        # Ziel: Reset mit Cryochambers (challenges.js:179-181) — erfüllt
        # sich BEIM Reset; Rest-ETA = Cryochamber beschaffen.
        u = _voidspace(snap, "cryochambers")
        if u is None:
            return math.inf, False
        if (u.get("val") or 0) >= 1:
            return 0.0, True
        return _eta_prices_observed(snap, u.get("prices")), True
    if name == "1000Years":
        # Ziel: Jahr 1000 per Shatter (Kalender klemmt bei 500,
        # calendar.js:457). TC-Bedarf ≈ (1000 − Jahr) × 1,5 (1 TC/Jahr
        # Basispreis + 50 % Shatter-Malus WÄHREND der Challenge,
        # challenges.js:205-212) über die beobachtete TC-Rate.
        if A.resource(snap, "timeCrystal") is None:
            return math.inf, False
        years = 1000 - snap.get("calendar", {}).get("year", 0)
        if years <= 0:
            return 0.0, True
        need = years * 1.5 - A.res_value(snap, "timeCrystal")
        if need <= 0:
            return 0.0, True
        rate = A.res_rate(snap, "timeCrystal")
        return (need / rate if rate > 1e-9 else math.inf), True
    if name == "blackSky":
        # Ziel: spaceBeacon.val > bisherige Abschlusszahl (challenges.js:
        # 252-254) — `on` der Challenge zählt die Abschlüsse.
        b = _space_building(snap, "spaceBeacon")
        if b is None:
            return math.inf, False
        done = (get(snap, name) or {}).get("on") or 0
        if (b.get("val") or 0) > done:
            return 0.0, True
        return _eta_prices_observed(snap, b.get("prices")), True
    if name == "pacifism":
        # Ziel: Outer-Space-Treaty-Policy (challenges.js:299-312, on reset).
        p = _policy(snap, "outerSpaceTreaty")
        if p is None:
            return math.inf, False
        if p.get("researched"):
            return 0.0, True
        if p.get("blocked"):
            return math.inf, True    # I-07: Alternative gewählt — ehrlich ∞
        return _eta_prices_observed(snap, p.get("prices")), True
    if name == "unicornTears":
        # Ziel: 1 Necrocorn (challenges.js:450-452). Produktion über
        # pacts.necrocornPerDay (Marker-Netto, 1 Tag = 2 s).
        necro = A.resource(snap, "necrocorn")
        pacts = snap.get("pacts") if isinstance(snap.get("pacts"), dict) else None
        if necro is None and pacts is None:
            return math.inf, False
        value = float((necro or {}).get("value", 0.0))
        if value >= 1.0:
            return 0.0, True
        per_day = float((pacts or {}).get("necrocornPerDay", 0.0) or 0.0)
        if per_day > 1e-12:
            return (1.0 - value) / (per_day / 2.0), True
        return math.inf, True
    if name == "postApocalypse":
        # Ziel: cathPollution == 0 (challenges.js:475-477) — der Zielzustand
        # entsteht erst DURCH die Challenge-Startbedingung (Start mit
        # maximaler Pollution); eine Ist-Projektion wäre gelogen → ehrlich ∞.
        return math.inf, True
    return math.inf, False


# ---- Belohnungswert (#38): ΔE[T_F] über die Projektion mit Effekt ----

def reward_seconds(snap: dict, name: str, horizon: float) -> float | None:
    """Sekundenwert des Erstbelohnungseffekts über den Horizont —
    λ-freies Produktionszeit-Äquivalent Σ (ΔRate/Rate) × H (#38).

    Abgebildet werden Effekte mit seriöser Snapshot-Übersetzung:
    - winterIsComing springCatnipRatio 0.05 (challenges.js:77): +5 % auf
      die Feld-Basisproduktion, nur im Frühling (Saisonanteil ¼,
      Modifikator 1,5) — relativ zur beobachteten Catnip-Rate.
    - pacifism alicornPerTickRatio 0.1 (challenges.js:286): +10 % auf die
      Alicorn-Rate, sofern Alicorns überhaupt produziert werden.
    Nicht abbildbar (None → Aufrufer nutzt die Referenzschätzung):
    masterSkillMultiplier (Skill-Verteilung unbekannt), energy-/faith-/
    shatter-/corruption-/ivory-Effekte (wirken auf Systeme ohne
    beobachtbare Basisrate im Snapshot)."""
    if name == "winterIsComing":
        rate = A.res_rate(snap, "catnip")
        if rate <= 1e-9:
            return None
        tps = snap.get("meta", {}).get("ticksPerSecond", 5)
        field_base = snap.get("effects", {}).get("catnipPerTickBase", 0.0) * tps
        if field_base <= 0:
            return None
        delta = 0.05 * field_base * 1.5 * 0.25   # +5 % × Frühling(1,5) × ¼ Jahr
        return delta / rate * horizon
    if name == "pacifism":
        if A.res_rate(snap, "alicorn") > 1e-9:
            return 0.1 * horizon                 # Δrate/rate = ratio exakt
        return None
    return None


def challenge_value(snap: dict, name: str) -> float:
    """ChallengeValue(c) = ΔE[T_F] / E[Completion] (Spec 18.2, #38).

    Zähler: reward_seconds über den Run-Horizont (ohne Übersetzung →
    Referenzschätzung reward_tf_reduction_s als Fallback). Nenner:
    completion_eta — beobachtbar+endlich → max(eta, CHALLENGE_MIN_RUN_S);
    beobachtbar+∞ → Wert ehrlich 0 (Ziel im aktuellen Zustand
    unerreichbar); Zielobjekte gar nicht im Snapshot → Referenzschätzung
    est_completion_s. Begründung: „ehrlich math.inf statt Konstante" gilt
    für die RESTZEIT (sie konkurriert in Sekunden gegen echte
    Projektionen, meta._plan_restzeit); der dimensionslose ChallengeValue
    ordnet nur Challenges untereinander — ohne jegliche Zielobjekte ist
    die dokumentierte Referenz-Rangfolge der ehrliche Informationsstand
    (Leitplanke „Fallbacks ohne Daten"). Nur Erstabschlüsse
    (researched == False); ohne Daten/Profil/gesperrt: 0."""
    if name in EXCLUDED:
        return 0.0
    c = get(snap, name)
    if c is None or c.get("researched") or not c.get("unlocked"):
        return 0.0
    prof = CHALLENGE_PROFILES.get(name)
    if not prof:
        return 0.0
    eta, observable = completion_eta(snap, name)
    if observable:
        if not math.isfinite(eta):
            return 0.0
        denom = max(eta, CHALLENGE_MIN_RUN_S)
    else:
        denom = prof["est_completion_s"]
    reward = reward_seconds(snap, name, shadow.run_horizon(snap))
    if reward is None:
        reward = prof["reward_tf_reduction_s"]
    return reward / denom


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
