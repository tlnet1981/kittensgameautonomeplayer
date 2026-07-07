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
    # laufender Goldproduktion; wird nie gewählt.
    snap = make_snap(
        resources={"culture": {"value": 5000, "max": 10000, "rate": 2.0},
                   "gold": {"value": 10, "max": 100, "rate": 1.0}},
        policies=[{"name": "monarchy", "label": "Monarchy",
                   "blocks": [], "prices": {"culture": 1500}}],
    )
    assert policy.best_policy(snap, "FIRST_RUN", {"gold": 10.0}, HORIZON) is None


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
