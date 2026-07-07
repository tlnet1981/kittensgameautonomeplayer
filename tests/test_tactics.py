"""Tests des taktischen Optimierers (brain/tactics.py) — inkl. der beiden
im Live-Test gefundenen Deadlock-Szenarien."""

from player.brain import meta, safety, tactics
from tests.helpers import make_snap


def _generate(snap):
    sres = safety.check(snap)
    mview = meta.evaluate(snap)
    cands, bn = tactics.generate(snap, mview, sres)
    selected = next(c for c in cands if c.feasible)
    return cands, bn, selected, mview


def test_first_action_is_gathering():
    """Frisches Spiel: keine Felder, kein Catnip → sammeln."""
    snap = make_snap(resources={"catnip": {"value": 0, "max": 5000, "rate": 0}},
                     buildings={"field": {"val": 0, "prices": {"catnip": 10}}})
    cands, bn, selected, _ = _generate(snap)
    assert selected.action.id == "gather:catnip"


def test_milestone_build_selected_when_affordable():
    snap = make_snap(resources={"catnip": {"value": 100, "max": 5000, "rate": 1}},
                     buildings={"field": {"val": 0, "prices": {"catnip": 10}}})
    cands, bn, selected, mv = _generate(snap)
    assert mv.active.id == "field_1"
    assert selected.action.id == "build:field"
    assert selected.components.get("milestone", 0) > 0


def test_wood_deadlock_resolved_by_refine():
    """Deadlock 1 aus dem Live-Test: Holz nur über Refine erreichbar."""
    snap = make_snap(
        resources={"catnip": {"value": 300, "max": 5000, "rate": 10},
                   "wood": {"value": 1, "max": 200, "rate": 0}},
        buildings={"field": {"val": 15, "prices": {"catnip": 60}}},
        catnip_field_base=10,
    )
    cands, bn, selected, mv = _generate(snap)
    assert mv.active.id == "wood_first"
    assert bn["resource"] == "wood"
    assert selected.action.id == "refine:catnip"


def test_kitten_bootstrap_banking_mode():
    """Kitten-Bootstrap (0 Kitten, Job-Ressource als Engpass): Felder, die
    die Projektion verbessern, sind Engpasslöser; Catnip ist reserviert
    (generische Catnip-Käufe bestraft); Refine läuft nur fürs Housing-Holz."""
    snap = make_snap(
        resources={"catnip": {"value": 300, "max": 5000, "rate": 10},
                   "wood": {"value": 1, "max": 200, "rate": 0}},
        buildings={"field": {"val": 15, "prices": {"catnip": 60}},
                   "hut": {"val": 0, "prices": {"wood": 5}},
                   "aqueduct": {"val": 0, "prices": {"catnip": 75}}},
        catnip_field_base=10, kittens=0, max_kittens=0,
    )
    cands, bn, selected, _ = _generate(snap)
    assert bn["resource"] == "wood"   # wood ist Job-Ressource → Banking aktiv
    field = next(c for c in cands if c.action.id == "build:field")
    assert field.components.get("bottleneck", 0) > 0   # verbessert die Bank
    # Refine-Ausnahme fürs Hütten-Holz existiert:
    refine = next(c for c in cands if c.action.id == "refine:catnip")
    assert refine.feasible and refine.score > 0
    # generischer Catnip-Kauf (Aqueduct) wird bestraft und fällt unter 0:
    aqueduct = next(c for c in cands if c.action.id == "build:aqueduct")
    assert aqueduct.components.get("opportunity", 0) < 0
    assert aqueduct.score < 0


def test_free_kitten_assigned_to_bottleneck_job():
    snap = make_snap(
        resources={"catnip": {"value": 2000, "max": 5000, "rate": 15},
                   "wood": {"value": 5, "max": 200, "rate": 0.2}},
        buildings={"field": {"val": 20, "prices": {"catnip": 60}},
                   "hut": {"val": 1, "prices": {"wood": 10}},
                   "library": {"val": 0, "prices": {"wood": 25}}},
        jobs={"woodcutter": 0}, free_kittens=2, kittens=2, max_kittens=2,
        catnip_field_base=15,
    )
    cands, bn, selected, mv = _generate(snap)
    assert bn["resource"] == "wood"
    assert selected.action.exec_spec.get("kind") == "assign_job"
    assert selected.action.exec_spec.get("job") == "woodcutter"


def test_storage_only_when_cap_blocks():
    """Storage-Regel 11.3 A: Barn nur bauen, wenn ein Cap das Ziel blockiert."""
    base = dict(
        jobs={"woodcutter": 2}, kittens=2, max_kittens=4,
        catnip_field_base=15,
        techs={"calendar": {"researched": True, "prices": {"science": 30}},
               "agriculture": {"researched": True, "prices": {"science": 100}}},
    )
    # Fall A: kein Cap blockiert das Ziel → weiterer (generischer) Barn unzulässig.
    # (barn val=1, damit der barn_1-Meilenstein nicht selbst das Ziel ist)
    snap = make_snap(
        resources={"catnip": {"value": 500, "max": 5000, "rate": 15},
                   "wood": {"value": 100, "max": 400, "rate": 0.5}},
        buildings={"field": {"val": 20, "prices": {"catnip": 300}},
                   "barn": {"val": 1, "prices": {"wood": 50}}},
        **base,
    )
    cands, _, _, _ = _generate(snap)
    assert not any(c.action.id == "build:barn" and c.feasible for c in cands)

    # Fall B: Ziel braucht 400 wood, Cap ist 200 → Barn zulässig und hoch bewertet
    snap = make_snap(
        resources={"catnip": {"value": 500, "max": 5000, "rate": 15},
                   "wood": {"value": 200, "max": 200, "rate": 0.5}},
        buildings={"hut": {"val": 2, "prices": {"wood": 400}},
                   "barn": {"val": 0, "prices": {"wood": 50}}},
        **base,
    )
    # aktives Ziel manuell auf hut setzen (Meilensteinliste wäre hier weiter):
    sres = safety.check(snap)
    mview = meta.evaluate(snap)
    if not (mview.active and mview.active.target == {"kind": "build", "name": "hut"}):
        from player.brain.meta import Milestone
        mview.active = Milestone("hut_x", "Hütte", lambda s: False,
                                 {"kind": "build", "name": "hut"})
    cands, bn = tactics.generate(snap, mview, sres)
    barn = next(c for c in cands if c.action.id == "build:barn")
    assert barn.components.get("storage", 0) > 0


def test_wait_has_reason_and_is_last_resort():
    snap = make_snap(
        resources={"catnip": {"value": 10, "max": 5000, "rate": 3},
                   "wood": {"value": 0, "max": 200, "rate": 0}},
        buildings={"field": {"val": 15, "prices": {"catnip": 600}}},
        catnip_field_base=10,
    )
    cands, bn, selected, _ = _generate(snap)
    wait = next(c for c in cands if c.action.id == "wait")
    assert "Warte" in wait.action.exec_spec["reason"] or "Kein Kandidat" in wait.action.exec_spec["reason"]


def test_deterministic_ordering():
    snap = make_snap(
        resources={"catnip": {"value": 100, "max": 5000, "rate": 5}},
        buildings={"field": {"val": 0, "prices": {"catnip": 10}}},
    )
    c1, _, s1, _ = _generate(snap)
    c2, _, s2, _ = _generate(snap)
    assert [c.action.id for c in c1] == [c.action.id for c in c2]
    assert s1.action.id == s2.action.id


# ---------------------------------------------------------------- Deadlock-Regression (Live-Fund)

def test_wood_first_low_catnip_is_not_a_deadlock():
    """Live-Fund: Ziel 'Erstes Holz veredeln', Catnip < 100 (Refine noch
    unbezahlbar), keine Woodcutter (Holzrate 0). Früher: nur WAIT →
    Deadlock-Fehlalarm + Stillstand. Jetzt: Gather-Kandidat sammelt den
    Konversions-Input aktiv, und die Konversions-ETA ist eine endliche
    Weckbedingung (kein Deadlock, 22.3)."""
    from player.brain import meta, safety
    snap = make_snap(
        resources={"catnip": {"value": 60, "max": 5000, "rate": 1.2},
                   "wood": {"value": 0, "max": 200, "rate": 0.0}},
        buildings={"field": {"val": 12, "prices": {"catnip": 350},
                             "unlocked": True}},
    )
    mv = meta.evaluate(snap)
    assert mv.objective_label == "Erstes Holz veredeln"
    cands, bn = tactics.generate(snap, mv, safety.check(snap))[:2]
    positive = [c for c in cands if c.feasible and c.score > 0
                and c.action.type != "WAIT"]
    assert positive, "es muss einen aktiven Kandidaten geben (Gather)"
    assert any(c.action.id.startswith("gather") for c in positive)
    assert not tactics.is_deadlock(cands, bn, snap)
    # Refine ist sichtbar abgelehnt mit endlicher ETA im Grund:
    refine = next(c for c in cands if c.action.id.startswith("refine"))
    assert not refine.feasible and "catnip" in (refine.reject_reason or "")


def test_real_deadlock_without_conversion_still_detected():
    """Gegenprobe: Engpass ohne Rate UND ohne Konversionsrezept bleibt ein
    echter Deadlock (22.3) — die Konversions-ETA-Prüfung weicht das
    Kriterium nicht generell auf."""
    from player.brain.records import Candidate as C
    from player.brain import actions
    wait_c = C(actions.wait("x", "y"), 0.01, {"base": 0.01})
    snap = make_snap(resources={"uranium": {"value": 0, "max": 100, "rate": 0.0}})
    assert tactics.is_deadlock([wait_c], {"resource": "uranium",
                                          "etaSeconds": None}, snap)


def _user_stagnation_snap():
    """Exakter Live-Zustand aus dem Nutzer-Save (Jahr 8): 55 Felder, Catnip
    AM Cap, Science AM Cap, 0 Holz, beide Kitten Scholars, Ziel 'Erste
    Mine' — die Mine ist wegen unlockRatio (0 Holz < 15) unsichtbar."""
    from player.brain import meta, safety
    techs = {t: {"researched": True} for t in
             ["calendar", "agriculture", "archery", "mining", "animal"]}
    snap = make_snap(
        resources={"catnip": {"value": 5000, "max": 5000, "rate": 8.0},
                   "wood": {"value": 0, "max": 200, "rate": 0.0},
                   "science": {"value": 500, "max": 500, "rate": 0.35},
                   "minerals": {"value": 0, "max": 250, "rate": 0.0}},
        buildings={"field": {"val": 55, "prices": {"catnip": 5000}, "unlocked": True},
                   "hut": {"val": 1, "prices": {"wood": 12}, "unlocked": True},
                   "library": {"val": 1, "prices": {"wood": 40}, "unlocked": True}},
        techs=techs,
        jobs={"woodcutter": 0, "farmer": 0, "scholar": 2},
        kittens=2, max_kittens=2,
    )
    mv = meta.evaluate(snap)
    return snap, mv, safety.check(snap)


def test_stagnation_state_escapes_with_rebalance_and_refine():
    """Live-Regression (Nutzer-Save Jahr 8): Der Zustand darf kein Deadlock
    sein — Umschulung weg vom Cap-Job und Refine-Cap-Ventil müssen als
    positive Kandidaten existieren, der Engpass kommt aus den
    Referenzpreisen der unsichtbaren Mine."""
    snap, mv, sr = _user_stagnation_snap()
    assert mv.objective_label == "Erste Mine"
    cands, bn = tactics.generate(snap, mv, sr)[:2]
    assert bn and bn.get("resource") == "wood"      # Referenzpreis-Fallback
    best = max((c for c in cands if c.feasible), key=lambda c: c.score)
    assert best.action.id == "shift:scholar>woodcutter"
    assert any(c.action.id.startswith("refine") and c.feasible and c.score > 0
               for c in cands)
    assert not tactics.is_deadlock(cands, bn, snap)
    # Und: kein weiteres Feld — Catnip ist am Cap, Payback-Gate greift.
    field = next((c for c in cands if c.action.id == "build:field"), None)
    assert field is None or not field.feasible


def test_job_score_is_zero_for_capped_output():
    """Cap-Klausel (Spec 11.1): Ein Job, dessen Ertragsressource voll ist,
    hat Grenzwert 0 — auch mit hohem λ."""
    from player.brain import shadow
    snap = make_snap(resources={"science": {"value": 500, "max": 500, "rate": 0.3},
                                "wood": {"value": 0, "max": 200, "rate": 0.0}})
    lam_rate = {"science": 500.0, "wood": 500.0}
    assert shadow.job_score(snap, "scholar", lam_rate) == 0.0
    assert shadow.job_score(snap, "woodcutter", lam_rate) > 0.0


def test_cap_rebalance_fires_without_bottleneck():
    """Cap-Rebalance läuft auch ohne Engpass-Daten (bn null): Kitten am
    vollen Science-Cap wird zum dünnsten nicht-vollen Job umgeschult."""
    snap = make_snap(
        resources={"science": {"value": 500, "max": 500, "rate": 0.3},
                   "wood": {"value": 10, "max": 200, "rate": 0.0}},
        jobs={"woodcutter": 0, "scholar": 2},
    )
    cands = []
    village = snap.get("village", {})
    tactics._job_rebalance_candidate(snap, None, cands, village, False, None)
    assert any(c.action.id == "shift:scholar>woodcutter" for c in cands)


def test_saving_rule_holds_cheaper_purchase_for_housing():
    """Live-Fund #2: Library #3 (25 Holz, bezahlbar) darf das Holz nicht
    verbrauchen, auf das für Hütte #3 (31 Holz, ~6 s entfernt) gespart
    wird — DelayPenalty der Kaufregel 10.3. Käufe ohne Ressourcenkonflikt
    (Feld: nur Catnip) bleiben unbestraft."""
    from player.brain import meta, safety
    techs = {t: {"researched": True} for t in
             ["calendar", "agriculture", "archery", "mining", "animal"]}
    snap = make_snap(
        resources={"catnip": {"value": 3000, "max": 5000, "rate": 6.0},
                   "wood": {"value": 28, "max": 200, "rate": 0.5},
                   "science": {"value": 120, "max": 675, "rate": 0.35},
                   "minerals": {"value": 40, "max": 250, "rate": 0.2}},
        buildings={"field": {"val": 20, "prices": {"catnip": 900}, "unlocked": True},
                   "hut": {"val": 2, "prices": {"wood": 31}, "unlocked": True},
                   "library": {"val": 2, "prices": {"wood": 25}, "unlocked": True},
                   "mine": {"val": 1, "prices": {"wood": 115}, "unlocked": True}},
        techs=techs,
        jobs={"woodcutter": 2, "farmer": 1, "scholar": 1},
        kittens=4, max_kittens=4,
    )
    mv = meta.evaluate(snap)
    cands = tactics.generate(snap, mv, safety.check(snap))[0]
    hut = next(c for c in cands if c.action.id == "build:hut")
    lib = next(c for c in cands if c.action.id == "build:library")
    field = next(c for c in cands if c.action.id == "build:field")
    assert not hut.feasible and hut.components.get("potential", 0) > 0
    assert lib.score < 0 and lib.components.get("delayPenalty", 0) < 0
    assert field.score > 0 and "delayPenalty" not in field.components
    wait = next(c for c in cands if c.action.type == "WAIT")
    assert "Spare auf" in wait.action.exec_spec.get("reason", "")


def test_saving_rule_ignores_far_away_targets():
    """Sparziele jenseits SAVING_HORIZON_S frieren die Ökonomie nicht ein."""
    from player.brain import meta, safety
    snap = make_snap(
        resources={"catnip": {"value": 3000, "max": 5000, "rate": 6.0},
                   "wood": {"value": 1, "max": 500, "rate": 0.01}},
        buildings={"field": {"val": 20, "prices": {"catnip": 900}, "unlocked": True},
                   "hut": {"val": 2, "prices": {"wood": 400}, "unlocked": True},
                   "library": {"val": 2, "prices": {"wood": 0.5}, "unlocked": True}},
        jobs={"woodcutter": 1},
        kittens=1, max_kittens=1,
    )
    mv = meta.evaluate(snap)
    cands = tactics.generate(snap, mv, safety.check(snap))[0]
    lib = next((c for c in cands if c.action.id == "build:library"), None)
    assert lib is None or "delayPenalty" not in lib.components


def test_farmer_released_after_winter_danger_passes():
    """Nutzer-Fund: Winter-Notfarmer blieben nach der Gefahr sitzen. Ist die
    Projektion auch ohne einen Farmer deutlich sicher (Marge 1.5), wird er
    zum besten anderen Job zurückgeschult."""
    snap = make_snap(
        resources={"catnip": {"value": 4000, "max": 5000, "rate": 6.0},
                   "wood": {"value": 5, "max": 200, "rate": 0.0},
                   "science": {"value": 10, "max": 500, "rate": 0.0}},
        buildings={"field": {"val": 30, "prices": {"catnip": 900}, "unlocked": True}},
        jobs={"woodcutter": 0, "farmer": 3, "scholar": 0},
        kittens=3, max_kittens=4,
        season="spring", catnip_field_base=30 * 0.125,
    )
    cands = []
    village = snap.get("village", {})
    tactics._job_rebalance_candidate(snap, None, cands, village, False, None)
    shift = [c for c in cands if c.action.id.startswith("shift:farmer>")]
    assert shift, "Farmer muss nach der Gefahr freigegeben werden"
    assert "foodSafe" in shift[0].components


def test_farmer_kept_when_projection_tight():
    """Gegenprobe: Bleibt die Projektion ohne den Farmer unter der
    1.5-fachen Warnschwelle, wird NICHT umgeschult (Anti-Flattern)."""
    snap = make_snap(
        resources={"catnip": {"value": 200, "max": 5000, "rate": 0.3}},
        buildings={"field": {"val": 3, "prices": {"catnip": 90}, "unlocked": True}},
        jobs={"woodcutter": 0, "farmer": 2},
        kittens=2, max_kittens=2,
        season="autumn", catnip_field_base=3 * 0.125,
    )
    cands = []
    village = snap.get("village", {})
    tactics._job_rebalance_candidate(snap, None, cands, village, False, None)
    assert not any(c.action.id.startswith("shift:farmer>") for c in cands)


def test_allocation_includes_woodcutter_for_next_hut():
    """Nutzer-Fund: null Woodcutter im ganzen Run, weil λ nur am aktiven
    (Science-)Ziel hing. Die Soll-Allokation (12.2) bewertet Ziel PLUS
    nächste Housing-Stufe — Holz wird gebraucht, ein Kitten muss fällen."""
    from player.brain import meta, safety
    techs = {"calendar": {"researched": True},
             "agriculture": {"researched": True},
             "archery": {"researched": False, "prices": {"science": 300}}}
    snap = make_snap(
        resources={"catnip": {"value": 2000, "max": 5000, "rate": 5.0},
                   "wood": {"value": 3, "max": 200, "rate": 0.0},
                   "science": {"value": 50, "max": 500, "rate": 0.2}},
        buildings={"field": {"val": 15, "prices": {"catnip": 500}, "unlocked": True},
                   "hut": {"val": 1, "prices": {"wood": 12}, "unlocked": True},
                   "library": {"val": 1, "prices": {"wood": 40}, "unlocked": True}},
        techs=techs,
        jobs={"woodcutter": 0, "farmer": 0, "scholar": 2},
        kittens=2, max_kittens=2,
    )
    mv = meta.evaluate(snap)
    cands = tactics.generate(snap, mv, safety.check(snap))[0]
    shift = next((c for c in cands if c.action.id.startswith("shift:")), None)
    assert shift is not None and shift.action.exec_spec["to"] == "woodcutter"
    assert "allocDeficit" in shift.components


def test_allocation_respects_min_farmers_and_sums():
    """Soll-Allokation: Summe == Kitten, Farmer nie unter der
    Food-Untergrenze, deterministisch bei Wiederholung."""
    from player.brain import shadow
    snap = make_snap(
        resources={"catnip": {"value": 300, "max": 5000, "rate": 0.5},
                   "wood": {"value": 0, "max": 200, "rate": 0.0},
                   "science": {"value": 0, "max": 500, "rate": 0.0}},
        buildings={"field": {"val": 4, "prices": {"catnip": 120}, "unlocked": True}},
        jobs={"woodcutter": 0, "farmer": 0, "scholar": 0},
        kittens=5, max_kittens=6, season="autumn",
        catnip_field_base=4 * 0.125,
    )
    prices = [{"name": "wood", "val": 100}, {"name": "science", "val": 60}]
    mf = tactics._min_farmers(snap, snap["village"])
    a1 = shadow.target_allocation(snap, prices, mf)
    a2 = shadow.target_allocation(snap, prices, mf)
    assert a1 == a2
    assert sum(a1.values()) == 5
    assert a1.get("farmer", 0) >= mf
    assert a1.get("woodcutter", 0) >= 1 and a1.get("scholar", 0) >= 1


def _flap_snap(catnip, jobs):
    return make_snap(
        resources={"catnip": {"value": catnip, "max": 5000, "rate": 2.0},
                   "wood": {"value": 3, "max": 200, "rate": 0.09},
                   "science": {"value": 50, "max": 500, "rate": 0.175}},
        buildings={"field": {"val": 10, "prices": {"catnip": 400}, "unlocked": True},
                   "hut": {"val": 2, "prices": {"wood": 31}, "unlocked": True}},
        techs={"calendar": {"researched": True}, "agriculture": {"researched": True},
               "archery": {"researched": False, "prices": {"science": 300}}},
        jobs=jobs, kittens=4, max_kittens=4,
        season="autumn", catnip_field_base=10 * 0.125,
    )


def test_no_farmer_flapping_inside_hysteresis_band():
    """Nutzer-Fund: 4. Kitten sprang Farmer↔Woodcutter. Im Band zwischen
    Farmer-Untergrenze (1.0×Warnschwelle) und Freigabe-Marge (1.5×) darf
    KEIN Farmer abgezogen werden, auch wenn die Allokation einen
    Überschuss sieht."""
    from player.brain import meta, safety
    snap = _flap_snap(1800, {"woodcutter": 1, "farmer": 2, "scholar": 1})
    v = snap["village"]
    assert tactics._min_farmers(snap, v) == 1          # Band-Vorbedingung
    assert not tactics._farmer_release_safe(snap, v)   # Band-Vorbedingung
    mv = meta.evaluate(snap)
    cands = tactics.generate(snap, mv, safety.check(snap))[0]
    assert not any(c.action.id.startswith("shift:farmer>") for c in cands
                   if c.feasible)


def test_no_shift_reversal_across_cycles():
    """Anti-Flattern-Simulation: Über mehrere Zyklen darf auf einen Tausch
    A→B nie unmittelbar der Rücktausch B→A folgen."""
    from player.brain import meta, safety
    jobs = {"woodcutter": 1, "farmer": 2, "scholar": 1}
    history = []
    for _ in range(6):
        snap = _flap_snap(1800, dict(jobs))
        mv = meta.evaluate(snap)
        cands = tactics.generate(snap, mv, safety.check(snap))[0]
        best = max((c for c in cands if c.feasible),
                   key=lambda c: (c.score, c.action.id))
        history.append(best.action.id)
        if not best.action.id.startswith("shift:"):
            break
        src, dst = best.action.exec_spec["from"], best.action.exec_spec["to"]
        jobs[src] -= 1
        jobs[dst] = jobs.get(dst, 0) + 1
    for a, b in zip(history, history[1:]):
        if a.startswith("shift:") and b.startswith("shift:"):
            sa = a.split(":", 1)[1].split(">")
            sb = b.split(":", 1)[1].split(">")
            assert sa != sb[::-1], f"Ping-Pong erkannt: {a} → {b}"
