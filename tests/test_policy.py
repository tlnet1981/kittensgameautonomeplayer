"""Tests der Policy-Wahl (Spec 13.4 + Invariante I-07, brain/policy.py)."""

from player.brain import actions, meta, policy, tactics
from player.brain.records import Candidate
from tests.helpers import make_snap

HORIZON = 3600.0
# λ-Setup: Science ist dem Ziel viel wert, Culture etwas — damit trennt
# die Bewertung Liberty (globaler Proxy, wirkt auch auf Science) klar von
# Tradition (nur Culture).
LAM = {"culture": 10.0, "science": 20.0}


def _snap(policies, culture=500.0):
    return make_snap(
        resources={
            "culture": {"value": culture, "max": 10000, "rate": 2.0},
            "science": {"value": 100, "max": 10000, "rate": 5.0},
        },
        policies=policies,
    )


def _liberty(**over):
    d = {"name": "liberty", "label": "Liberty", "blocks": ["tradition"],
         "prices": {"culture": 150}}
    d.update(over)
    return d


def _tradition(**over):
    d = {"name": "tradition", "label": "Tradition", "blocks": ["liberty"],
         "prices": {"culture": 150}}
    d.update(over)
    return d


# ------------------------------------------------------------ I-07

def test_i07_prefers_more_valuable_alternative():
    """I-07: gewählt wird nur, wenn PolicyValue(gewählt) ≥ PolicyValue jeder
    Alternative — die wertvollere Alternative gewinnt, auch wenn der
    13.4-Prior (FIRST_RUN: Tradition) den schwächeren Kandidaten nennt."""
    snap = _snap([_liberty(), _tradition()])
    best = policy.best_policy(snap, "FIRST_RUN", LAM, HORIZON)
    assert best is not None
    pol, value, alt_values = best
    assert pol["name"] == "liberty"
    assert value > 0
    # Die Alternative wurde bewertet (I-07: berücksichtigt, nicht ignoriert):
    assert "tradition" in alt_values
    assert value >= alt_values["tradition"]


def test_i07_rejects_weaker_policy_directly():
    snap = _snap([_liberty(), _tradition()])
    ok_lib, alts_lib = policy.i07_check(snap, _make_snap_policy(snap, "liberty"),
                                        LAM, HORIZON)
    ok_trad, alts_trad = policy.i07_check(snap, _make_snap_policy(snap, "tradition"),
                                          LAM, HORIZON)
    assert ok_lib and "tradition" in alts_lib
    assert not ok_trad and "liberty" in alts_trad


def _make_snap_policy(snap, name):
    return next(p for p in snap["policies"] if p["name"] == name)


def test_i07_evaluates_missing_alternative_via_reference():
    """Alternative fehlt im Snapshot (noch nicht sichtbar) → Bewertung über
    die Referenztabelle (POLICY_REF_PRICES/POLICY_EFFECTS), kein Blindkauf."""
    snap = _snap([_tradition()])   # liberty nicht im Snapshot
    ok, alts = policy.i07_check(snap, _make_snap_policy(snap, "tradition"),
                                LAM, HORIZON)
    assert not ok                       # Liberty (Referenz) wäre wertvoller
    assert "liberty" in alts


# ------------------------------------------------------------ Gates

def test_blocked_policy_never_candidate():
    snap = _snap([_liberty(blocked=True), _tradition(blocked=True)])
    assert policy.best_policy(snap, "FIRST_RUN", LAM, HORIZON) is None


def test_unaffordable_policy_never_candidate():
    snap = _snap([_liberty(), _tradition()], culture=100.0)   # < 150 Culture
    assert policy.best_policy(snap, "FIRST_RUN", LAM, HORIZON) is None


def test_researched_policy_never_candidate():
    snap = _snap([_liberty(researched=True), _tradition(blocked=True)])
    assert policy.best_policy(snap, "FIRST_RUN", LAM, HORIZON) is None


def test_negative_value_never_candidate():
    # Monarchy: goldPolicyRatio −0.1 (science.js) → negativer Wert bei
    # laufender Goldproduktion; wird nie gewählt. λ_culture 0.01 lässt die
    # Kulturpreise der Unlock-Stubs (liberalism/fascism, #37) minimal
    # zählen — sonst stünde der Zweigwert exakt auf 0 (Kantenfall).
    snap = make_snap(
        resources={"culture": {"value": 5000, "max": 10000, "rate": 2.0},
                   "gold": {"value": 10, "max": 100, "rate": 1.0}},
        policies=[{"name": "monarchy", "label": "Monarchy",
                   "blocks": [], "prices": {"culture": 1500}}],
    )
    assert policy.best_policy(snap, "FIRST_RUN",
                              {"gold": 10.0, "culture": 0.01}, HORIZON) is None


def test_without_policy_data_no_candidate():
    snap = make_snap()          # kein policies-Key (Alt-Snapshot)
    assert policy.best_policy(snap, "FIRST_RUN", LAM, HORIZON) is None
    cands: list[Candidate] = []
    tactics._policy_candidates(snap, "FIRST_RUN", cands, LAM, HORIZON)
    assert cands == []


def test_without_lambda_no_candidate():
    snap = _snap([_liberty(), _tradition()])
    assert policy.best_policy(snap, "FIRST_RUN", {}, HORIZON) is None


def test_prior_limits_search_space():
    # SEED_RUN-Prior (Technocracy/Expansionism/Handel) enthält weder Liberty
    # noch Tradition → Suchraumreduktion nach 13.4 lässt keinen Kandidaten zu.
    snap = _snap([_liberty(), _tradition()])
    assert policy.best_policy(snap, "SEED_RUN", LAM, HORIZON) is None


# ------------------------------------------------------------ Kandidat/Aktion

def test_policy_candidate_is_irreversible_with_value_component():
    snap = _snap([_liberty(), _tradition()])
    cands: list[Candidate] = []
    tactics._policy_candidates(snap, "FIRST_RUN", cands, LAM, HORIZON)
    assert len(cands) == 1              # höchstens EINE Policy pro Zyklus (10.5)
    c = cands[0]
    assert c.action.id == "policy:liberty"
    assert c.action.atomicity == actions.IRREVERSIBLE
    assert c.action.irreversible
    assert c.components["policyValue"] > 0
    # policyValue ist Anzeige-Sekundenwert (SHADOW_INFO_KEYS), Score bleibt fix:
    assert "policyValue" in tactics.SHADOW_INFO_KEYS
    assert c.score == c.components["policy"]
    # Prognose aus den Preisen (G-10):
    assert c.action.predicted["deltas"]["culture"] == -150.0


def test_select_policy_action_shape():
    act = actions.select_policy("liberty", "Liberty",
                                prices=[{"name": "culture", "val": 150}])
    assert act.atomicity == actions.IRREVERSIBLE
    assert act.exec_spec["kind"] == "select_policy"
    assert act.exec_spec["name"] == "liberty"


def test_challenge_run_uses_early_prior():
    # CHALLENGE_RUN zählt als „Früher Reset"-Kontext (13.4-Prior):
    assert policy.POLICY_PRIOR["CHALLENGE_RUN"] == policy.POLICY_PRIOR["FIRST_RUN"]
    # und der Meta-Controller kennt CHALLENGE_RUN als aktiven Run-Typ:
    assert "CHALLENGE_RUN" in meta.ACTIVE_RUN_TYPES


# ------------------------------------------------------------ Vollabdeckung (#37)

def test_full_coverage_invariant():
    """POLICY_EFFECTS deckt ALLE 66 Policies des policies-Arrays der
    Referenzversion ab (science.js:850-2189); jeder Eintrag nennt seine
    Quelle, nicht-unratable Einträge tragen eine Ratio-Übersetzung."""
    assert len(policy.POLICY_EFFECTS) == 66
    assert set(policy.POLICY_EFFECTS) == set(policy.POLICY_REF_PRICES)
    for name, eff in policy.POLICY_EFFECTS.items():
        assert eff.get("source"), name
        if eff.get("unratable"):
            assert "rate_ratio" not in eff and "global_ratio" not in eff, name
        else:
            assert "rate_ratio" in eff or "global_ratio" in eff, name
            assert "estimate" in eff, name
    # Referenz-Preisvektoren sind nicht leer und positiv:
    for name, prices in policy.POLICY_REF_PRICES.items():
        assert prices and all(v > 0 for v in prices.values()), name
    # blocks-/unlocks-Namen zeigen nur auf bekannte Policies:
    for name, blocks in policy.POLICY_REF_BLOCKS.items():
        assert name in policy.POLICY_EFFECTS, name
        for b in blocks:
            assert b in policy.POLICY_EFFECTS, (name, b)
    for name, unlocked in policy.POLICY_UNLOCKS.items():
        assert name in policy.POLICY_EFFECTS, name
        for u in unlocked:
            assert u in policy.POLICY_EFFECTS, (name, u)


def test_previously_uncovered_policy_becomes_candidate_and_wins():
    """Pflichttest #37: rationality (vor #37 nicht in POLICY_EFFECTS —
    nie Kandidat) wird Kandidat und schlägt die schwächere abgedeckte
    diplomacy: sciencePolicyRatio 0.05 exakt auf die Science-Rate."""
    snap = make_snap(
        resources={
            "culture": {"value": 5000, "max": 20000, "rate": 2.0},
            "science": {"value": 100, "max": 10000, "rate": 5.0},
            "manpower": {"value": 50, "max": 200, "rate": 2.0},
        },
        policies=[
            {"name": "rationality", "label": "Rationality",
             "blocks": ["mysticism"], "prices": {"culture": 3000}},
            {"name": "diplomacy", "label": "Diplomacy",
             "blocks": ["isolationism"], "prices": {"culture": 1600}},
        ],
    )
    lam = {"science": 20.0, "culture": 1.0, "manpower": 1.0}
    best = policy.best_policy(snap, "FIRST_RUN", lam, HORIZON)
    assert best is not None
    pol, value, _ = best
    assert pol["name"] == "rationality"
    # und ist klar wertvoller als der diplomacy-Zweig:
    dip = next(p for p in snap["policies"] if p["name"] == "diplomacy")
    assert value > policy.branch_value(snap, dip, lam, HORIZON)


def test_branch_valuation_flips_single_policy_decision():
    """Pflichttest #37: Einzelwert epicurianism > stoicism, aber der
    stoicism-Zweig (rationing: hunterRatio 0.1 auf hohe Manpower-Rate)
    kippt die Entscheidung — i07(epicurianism) scheitert am Zweigwert."""
    snap = make_snap(
        resources={
            "culture": {"value": 5000, "max": 20000, "rate": 2.0},
            "manpower": {"value": 100, "max": 500, "rate": 10.0},
        },
        policies=[
            {"name": "stoicism", "label": "Stoicism",
             "blocks": ["epicurianism"], "prices": {"culture": 2500}},
            {"name": "epicurianism", "label": "Epicurianism",
             "blocks": ["stoicism"], "prices": {"culture": 2500}},
        ],
    )
    lam = {"manpower": 10.0, "culture": 1.0}
    sto = next(p for p in snap["policies"] if p["name"] == "stoicism")
    epi = next(p for p in snap["policies"] if p["name"] == "epicurianism")
    # Einzelwerte: epicurianism (global 0.05) > stoicism (global 0.02):
    assert (policy.policy_value(snap, epi, lam, HORIZON)
            > policy.policy_value(snap, sto, lam, HORIZON) > 0)
    # Zweigwerte: stoicism gewinnt über den rationing-Stub; die gemeinsamen
    # Nachfolger rationality/mysticism neutralisieren sich:
    assert (policy.branch_value(snap, sto, lam, HORIZON)
            > policy.branch_value(snap, epi, lam, HORIZON))
    ok_epi, _ = policy.i07_check(snap, epi, lam, HORIZON)
    ok_sto, _ = policy.i07_check(snap, sto, lam, HORIZON)
    assert ok_sto and not ok_epi
    best = policy.best_policy(snap, "FIRST_RUN", lam, HORIZON)
    assert best is not None and best[0]["name"] == "stoicism"


def test_unratable_semantics_i07():
    """Pflichttest #37: unratable Alternativen (spiderRelationsChemists)
    zählen 0 und blockieren nicht mehr stillschweigend — ein erfundener
    blocks-Name führt weiterhin zur konservativen Ablehnung."""
    snap = make_snap(
        resources={
            "culture": {"value": 30000, "max": 50000, "rate": 2.0},
            "oil": {"value": 100, "max": 5000, "rate": 3.0},
        },
        policies=[{"name": "spiderRelationsPaleontologists",
                   "label": "Paleontologists",
                   "blocks": ["spiderRelationsChemists",
                              "spiderRelationsGeologists"],
                   "prices": {"culture": 20000}}],
    )
    lam = {"oil": 5.0, "culture": 0.1}
    pal = snap["policies"][0]
    assert policy.policy_value(
        snap, {"name": "spiderRelationsChemists", "prices": []},
        lam, HORIZON) == 0.0
    ok, alts = policy.i07_check(snap, pal, lam, HORIZON)
    assert ok
    assert alts["spiderRelationsChemists"] == 0.0
    # Erfundene Alternative (weder Snapshot noch Referenz) → Ablehnung:
    fake = dict(pal, blocks=["notARealPolicy"])
    ok, _ = policy.i07_check(snap, fake, lam, HORIZON)
    assert not ok


def test_run_plan_restzeit_drives_horizon():
    """Pflichttest #37: best_policy nutzt run_plan["restzeitS"] als
    Restplan-Horizont; ohne run_plan (oder ohne endliche Restzeit) gilt
    der übergebene Horizont."""
    snap = _snap([_liberty(), _tradition()])
    with_plan = policy.best_policy(snap, "FIRST_RUN", LAM, 600.0,
                                   run_plan={"restzeitS": 7200.0})
    explicit = policy.best_policy(snap, "FIRST_RUN", LAM, 7200.0)
    assert with_plan is not None and explicit is not None
    assert with_plan[1] == explicit[1]
    without_plan = policy.best_policy(snap, "FIRST_RUN", LAM, 600.0,
                                      run_plan={"restzeitS": None})
    baseline = policy.best_policy(snap, "FIRST_RUN", LAM, 600.0)
    assert without_plan is not None and baseline is not None
    assert without_plan[1] == baseline[1]
    assert with_plan[1] != baseline[1]   # der Horizont wirkt tatsächlich
