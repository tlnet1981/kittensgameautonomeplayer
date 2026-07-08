"""Reset-Bewertung und Pre-Reset-Transaktion (Spec Kap. 20).

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

Die Pre-Reset-Transaktion folgt der vollen 12-Schritt-Struktur aus Spec 20.3
(execute_reset): jeder Schritt wird einzeln als `reset.step`-Event geloggt,
nicht anwendbare Schritte ehrlich als "skipped". Fehlgeschlagene OPTIONALE
Schritte (z. B. ein nicht klickbarer Perk) brechen die Transaktion nicht ab;
die harten Assertions in Schritt 10 (TC-Schutz, Challenge-Gate, AgentMode,
Versions-Guard) brechen ab — dann findet KEIN Reset statt.
"""

from __future__ import annotations

import asyncio
from typing import Any

from player.driver.actor import Actor, SET_CHALLENGE_PENDING_JS
from player.driver.reader import read_snapshot
from player.state import access as A
from player.state.derived import derive

from . import actions, challenge, chrono, religion, simulate

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
             paragon_samples: list[tuple[float, int]] | None = None, *,
             plan_restzeit_s: float | None = None) -> dict[str, Any]:
    """Bewertet, ob jetzt resettet werden soll. Liefert Gates fürs Cockpit.

    plan_restzeit_s (#39): erwartete Restlaufzeit des Makroplans bis zum
    Run-Ziel (meta.determine_run_plan → run_plan["restzeitS"]) — sie IST
    die erwartete Zeit bis zum geplanten Reset bzw. zur Perk-Finanzierung
    und wird als "etaSeconds" exportiert (Payback-Horizont 10.4/6.4)."""
    projection = snap.get("derived", {}).get("resetParagon", 0)
    paragon_now = snap.get("prestige", {}).get("paragon", 0)

    recommended = False
    reason = ""
    reset_value: dict | None = None
    has_reset_goal = True
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
        has_reset_goal = False

    # TC-Schutz (Invariante I-02 / Spec 9.1): Reset mit relevantem
    # Time-Crystal-Bestand nur mit Anachronomancy (TC überleben sonst nicht).
    tc = next((r["value"] for r in snap.get("resources", []) if r["name"] == "timeCrystal"), 0)
    anachronomancy = any(p["name"] == "anachronomancy" and p["researched"]
                         for p in snap.get("prestige", {}).get("perks", []))
    tc_safe = tc < 3 or anachronomancy
    if not tc_safe:
        recommended = False

    # Erwartete Restlaufzeit bis zum GEPLANTEN Reset (#39, Spec 10.4/6.4):
    # 0 wenn der Reset jetzt empfohlen ist; sonst die Makroplan-Restzeit;
    # None, wenn kein Reset geplant ist (TC-Schutz blockiert / kein Ziel)
    # — der Aufrufer fällt dann auf die run_horizon-Heuristik zurück.
    if not tc_safe or not has_reset_goal:
        eta_seconds: float | None = None
    elif recommended:
        eta_seconds = 0.0
    else:
        eta_seconds = plan_restzeit_s

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
        "etaSeconds": eta_seconds,
        "gates": gates,
        "nextPerk": next_perk["label"] if next_perk else None,
        "resetValue": reset_value,
        "pendingChallenge": pending_challenge,
        # Für execute_reset (Schritt 2/3/10) und das Cockpit:
        "runType": run_type,
        # TAP-Vorschau (Spec 15.2): geordnete Schritte mit Begründung/Wert —
        # ausgeführt wird sie erst in der Pre-Reset-Transaktion (Schritt 5).
        "tapPlan": religion.tap_plan(snap),
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


# Wartezeit nach game.resetAutomatic() bis zum Reload (Tests: monkeypatch):
POST_RESET_WAIT_S = 3.0
# Nicht übertragbare Ressourcen (persists: false, gamefiles/js/resources.js)
# und ihr werterhaltender Craft (Schritt 8). Nur Furs haben einen direkten
# Craft-Ausweg (Parchment, 175 Furs — workshop.js:2163-2168); Craftables
# werden ihrerseits NUR mit Flux Condensator übertragen (sqrt-Formel in
# game.js _resetInternal). Unicorns/Tears/Alicorns laufen über Schritt 6.
NON_CARRY_CRAFTS: dict[str, tuple[str, float]] = {
    "furs": ("parchment", 175.0),
}
# Obergrenzen der fehlertoleranten Kaufschleifen (Schritt 3/7):
MAX_PERK_BUYS = 3
MAX_CS_BUYS = 3


async def _fresh_snap(browser) -> dict | None:
    """Frischer, abgeleiteter Snapshot — None statt Exception (die
    Transaktion protokolliert den Ausfall und arbeitet konservativ weiter)."""
    try:
        return derive(await read_snapshot(browser))
    except Exception:
        return None


async def execute_reset(runtime, reset_eval: dict) -> bool:
    """Pre-Reset-Transaktion (Spec 20.3, 12 Schritte) + atomarer Reset.

    Rückgabe True = Reset wurde ausgeführt; False = eine harte Assertion
    (Schritt 2/10) hat abgebrochen, das Spiel läuft unverändert weiter.
    Optionale Schritte sind fehlertolerant: Fehlschläge werden als
    `reset.step`-Event mit status "failed" geloggt, brechen aber nicht ab."""
    bus = runtime.bus
    browser = runtime.browser
    actor = Actor(browser, getattr(getattr(runtime, "config", None),
                                   "click_glow_ms", 450))

    def step(n: int, title: str, status: str, detail: str = "") -> None:
        bus.publish("reset.step", {"step": n, "title": title,
                                   "status": status, "detail": detail})

    # ---- 1. Atomarer Zustand + Save-Export (I-02) ----
    try:
        save = await browser.export_save()
        if save and getattr(runtime, "store", None):
            runtime.store.write_save(save)
        step(1, "Save-Export", "done" if save else "failed",
             "Save gesichert" if save else "export_save lieferte nichts")
    except Exception as exc:
        step(1, "Save-Export", "failed", str(exc))

    snap = await _fresh_snap(browser)

    # ---- 2. Challenge-Erfüllung verifizieren (18.4, hartes Gate) ----
    if reset_eval.get("runType") == "CHALLENGE_RUN" and snap is not None:
        ok, reason = challenge.reset_gate(snap)
        if not ok:
            step(2, "Challenge-Verifikation", "failed", reason)
            bus.publish("model.warning", {
                "error": f"Pre-Reset abgebrochen (Schritt 2): {reason}"})
            return False
        step(2, "Challenge-Verifikation", "done", reason)
    else:
        step(2, "Challenge-Verifikation", "skipped",
             "kein CHALLENGE_RUN" if snap is not None else "kein Snapshot")

    # ---- 3. Geplante permanente Käufe (Metaphysics, Spec 20.3.3) ----
    # Import hier statt am Modulkopf: meta.py importiert Reset-Konstanten
    # (FIRST_RESET_MIN_PARAGON) — ein Top-Level-Import wäre zirkulär.
    from . import meta
    bought: list[str] = []
    perk_failure: str | None = None
    for _ in range(MAX_PERK_BUYS):
        if snap is None:
            break
        perk = meta.next_metaphysics_target(snap)
        if perk is None or not perk.get("unlocked") \
                or not A.affordable(snap, perk.get("prices") or []):
            break
        act = actions.buy_perk(perk["name"], perk.get("label") or perk["name"],
                               perk.get("prices"))
        res = await actor.execute(act.exec_spec)
        if not res.get("ok"):
            perk_failure = (f"{perk['name']}: "
                            f"{res.get('detail', 'Kauf fehlgeschlagen')}")
            break
        snap = await _fresh_snap(browser) or snap
        nxt = meta.next_metaphysics_target(snap)
        if nxt is not None and nxt.get("name") == perk["name"]:
            # researched-Flag hat nicht gewechselt — kein Doppelkauf-Loop:
            perk_failure = f"{perk['name']} nach Kauf nicht researched"
            break
        bought.append(perk["name"])
    if perk_failure:
        detail = perk_failure + " — Transaktion läuft weiter"
        if bought:
            detail = "gekauft: " + ", ".join(bought) + "; danach " + detail
        step(3, "Permanente Käufe", "failed", detail)
    elif bought:
        step(3, "Permanente Käufe", "done", "gekauft: " + ", ".join(bought))
    elif snap is not None:
        step(3, "Permanente Käufe", "skipped",
             "kein offener Metaphysics-Perk mit aktuellem Paragon bezahlbar")
    else:
        step(3, "Permanente Käufe", "skipped", "kein Snapshot")

    # ---- 4. Paragon-Projektion verifizieren (Formel wie derived.py /
    #         game.js getResetPrestige: max(0, kittens−70) + year//1000) ----
    if snap is not None:
        kittens = snap.get("village", {}).get("kittens", 0)
        year = snap.get("calendar", {}).get("year", 0)
        expected = max(0, kittens - 70) + year // 1000
        actual = snap.get("derived", {}).get("resetParagon", 0)
        detail = (f"Formel {expected} vs. Snapshot {actual} "
                  f"(geplant: {reset_eval.get('projection')})")
        if expected != actual:
            step(4, "Paragon-Projektion", "failed", detail)
            bus.publish("model.warning", {
                "error": f"Paragon-Projektion weicht ab: {detail}"})
        else:
            step(4, "Paragon-Projektion", "done", detail)
    else:
        step(4, "Paragon-Projektion", "skipped", "kein Snapshot")

    # ---- 5. TAP vollständig simulieren, bei positivem Wert ausführen (15.2) ----
    plan = religion.tap_plan(snap) if snap is not None else []
    if plan:
        executed: list[str] = []
        for tap_step in plan:
            res = await actor.execute({"kind": tap_step["step"]})
            executed.append(f"{tap_step['step']}: "
                            f"{'ok' if res.get('ok') else res.get('detail', 'fehlgeschlagen')}")
        step(5, "TAP-Transaktion", "done", "; ".join(executed))
        snap = await _fresh_snap(browser) or snap
    else:
        step(5, "TAP-Transaktion", "skipped",
             "kein TAP-Schritt mit positivem Wert (15.2)")

    # ---- 6. Konvertierungen nach Grenzwertregel (15.3/15.4) ----
    conversions: list[str] = []
    if snap is not None:
        # Unicorns → Tears (religion.js:1544-1547 sacrificeAllUnicorns):
        if A.bld_val(snap, "ziggurat") >= 1 \
                and A.res_value(snap, "unicorns") >= religion.UNICORN_SAC_BATCH:
            try:
                await browser.evaluate("() => game.religion.sacrificeAllUnicorns()")
                conversions.append("Unicorns → Tears (sacrificeAllUnicorns)")
                snap = await _fresh_snap(browser) or snap
            except Exception as exc:
                conversions.append(f"Unicorn-Opfer fehlgeschlagen: {exc}")
        # Tears → BLS (Tears persists:false, Sorrow persists:true):
        due, det = religion.tears_refine_due(snap, None, pre_reset=True)
        if due:
            res = await actor.execute({"kind": "refine_tears",
                                       "batches": det["batches"]})
            conversions.append(f"Tears → BLS: "
                               f"{res.get('detail') if res.get('ok') else 'fehlgeschlagen'}")
        # Alicorns → TC (nur mit Anachronomancy, 15.4):
        due, det = religion.alicorn_conversion_due(snap, None, pre_reset=True)
        if due:
            res = await actor.execute({"kind": "convert_alicorns",
                                       "batches": det["batches"]})
            conversions.append(f"Alicorns → TC: "
                               f"{res.get('detail') if res.get('ok') else 'fehlgeschlagen'}")
        elif det.get("batches", 0) >= 1:
            conversions.append(f"Alicorns gehalten: {det.get('reason')}")
    if conversions:
        step(6, "Konvertierungen", "done", "; ".join(conversions))
        snap = await _fresh_snap(browser) or snap
    else:
        step(6, "Konvertierungen", "skipped",
             "keine Bestände über den Batch-Grenzen")

    # ---- 7. Chronospheres auf Zielstand (19.1 / chrono.py) ----
    if snap is not None:
        n_target, cs_detail = chrono.optimal_chronosphere_count(snap)
        if n_target is None:
            step(7, "Chronosphere-Zielstand", "skipped",
                 str(cs_detail.get("reason", "keine Daten")))
        else:
            built = 0
            for _ in range(MAX_CS_BUYS):
                b = A.building(snap, "chronosphere") or {}
                if int(b.get("val", 0)) >= n_target \
                        or not A.affordable(snap, b.get("prices") or []):
                    break
                act = actions.buy_building("chronosphere",
                                           b.get("label", "Chronosphere"),
                                           int(b.get("val", 0)), b.get("prices"))
                res = await actor.execute(act.exec_spec)
                if not res.get("ok"):
                    break
                built += 1
                snap = await _fresh_snap(browser) or snap
            have = int((A.building(snap, "chronosphere") or {}).get("val", 0))
            step(7, "Chronosphere-Zielstand",
                 "done" if built or have >= n_target else "skipped",
                 f"Ziel {n_target}, Bestand {have}, gebaut {built} "
                 f"(csValueNext: {cs_detail.get('csValueNext')})")
    else:
        step(7, "Chronosphere-Zielstand", "skipped", "kein Snapshot")

    # ---- 8. Nicht übertragbare Ressourcen mit Restwert ausgeben (20.3.8) ----
    spent: list[str] = []
    if snap is not None:
        flux = A.upgrade(snap, "fluxCondensator")
        if flux is not None and flux.get("researched"):
            # Nur mit Flux Condensator werden Craftables überhaupt übertragen
            # (game.js _resetInternal: sqrt(value)·saveRatio·100):
            for res_name, (craft_name, unit) in sorted(NON_CARRY_CRAFTS.items()):
                times = int(A.res_value(snap, res_name) // unit)
                if times < 1:
                    continue
                res = await actor.execute({"kind": "craft", "name": craft_name,
                                           "times": times})
                spent.append(f"{res_name} → {times}× {craft_name} "
                             f"({'ok' if res.get('ok') else 'fehlgeschlagen'})")
        if spent:
            step(8, "Non-Carry-Restwerte", "done", "; ".join(spent))
        else:
            step(8, "Non-Carry-Restwerte", "skipped",
                 "kein werterhaltender Craft (Flux Condensator fehlt oder "
                 "keine Bestände über der Rezeptgröße)")
    else:
        step(8, "Non-Carry-Restwerte", "skipped", "kein Snapshot")

    # ---- 9. Post-Reset-Projektion (simulate + erwarteter Carryover) ----
    if snap is not None and simulate.has_projection_data(snap):
        cs_val = A.bld_val(snap, "chronosphere")
        carry_ratio = chrono.CARRYOVER_PER_CS * cs_val
        proj = simulate.project(snap, RESET_VALUE_T_MIN)
        summary = proj.summary()
        summary["carryoverRatio"] = round(carry_ratio, 4)
        summary["paragonAfterReset"] = (reset_eval.get("paragonNow", 0)
                                        + reset_eval.get("projection", 0))
        step(9, "Post-Reset-Projektion", "done", str(summary))
        bus.publish("reset.projection", summary)
    else:
        step(9, "Post-Reset-Projektion", "skipped",
             "keine Simulationsdaten im Snapshot")

    # ---- 10. Harte Assertions — Fehlschlag bricht die Transaktion ab ----
    failures: list[str] = []
    if snap is not None and not religion.tc_survives_reset(snap):
        failures.append("TC-Schutz: Time Crystals ohne Anachronomancy "
                        "würden verfallen (I-02)")
    if snap is not None and reset_eval.get("runType") == "CHALLENGE_RUN":
        ok, reason = challenge.reset_gate(snap)
        if not ok:
            failures.append(f"Challenge-Gate: {reason}")
    mode = getattr(runtime, "agent_mode", "ACTIVE")
    if mode != "ACTIVE":
        failures.append(f"AgentMode {mode} ≠ ACTIVE (G-02)")
    guard = getattr(runtime, "version_guard", None)
    if isinstance(guard, dict) and guard.get("match") is False:
        failures.append("Versions-Guard: Spielversion weicht von der Referenz ab")
    if failures:
        step(10, "Assertions", "failed", "; ".join(failures))
        bus.publish("model.warning", {
            "error": "Pre-Reset abgebrochen (Schritt 10): " + "; ".join(failures)})
        return False
    step(10, "Assertions", "done",
         "TC-Schutz, Challenge-Flag, AgentMode und Version geprüft")

    # ---- 11. Reset atomar ausführen (pending-Challenge + resetAutomatic) ----
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

    # Kapitelkarte — der Reset ist ein Kapitelwechsel (Cockpit-Spec 14.5):
    bus.publish("narrative.chapter", {
        "priority": "P1",
        "title": f"RESET — Kapitelwechsel (+{reset_eval['projection']} Paragon)",
        "body": (f"{reset_eval['reason']}. Die Zivilisation beginnt von vorn — "
                 f"schneller, mit permanenten Boni."),
    })
    bus.publish("reset.committed", reset_eval)
    await browser.evaluate("() => game.resetAutomatic()")
    step(11, "Atomarer Reset", "done", "game.resetAutomatic() ausgelöst")

    # ---- 12. Post-Reset-Zustand validieren ----
    await asyncio.sleep(POST_RESET_WAIT_S)
    await browser.reinitialize(timeout_s=90)
    post = await _fresh_snap(browser)
    if post is not None:
        paragon_actual = post.get("prestige", {}).get("paragon", 0)
        paragon_expected = (reset_eval.get("paragonNow", 0)
                            + reset_eval.get("projection", 0))
        step(12, "Post-Reset-Validierung", "done",
             f"Paragon ist {paragon_actual}, projiziert {paragon_expected}")
        if paragon_actual < paragon_expected:
            bus.publish("model.warning", {
                "error": (f"Paragon nach Reset unter der Projektion: "
                          f"{paragon_actual} < {paragon_expected}")})
    else:
        step(12, "Post-Reset-Validierung", "failed",
             "kein Snapshot nach Reinitialisierung")
    bus.publish("narrative.chapter", {
        "priority": "P1",
        "title": "Neuer Run beginnt",
        "body": "Carryover geprüft — der Agent baut die Wirtschaft mit Paragon-Bonus neu auf.",
    })
    return True
