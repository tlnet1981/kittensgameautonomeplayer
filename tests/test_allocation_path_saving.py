"""Regressionstest (Save-Analyse Decision #18): Die Sparregel 10.3 muss
ALLE höherwertigen Sparziele gleichzeitig schützen — nicht nur das
bestwertige. Im Live-Fund verdrängte das Meilensteinziel (Science,
pot 3.0) die Hütte (Holz, pot 2.8) als einziges Sparziel; die Library
verbrauchte kein Science und fraß ungestraft das Hütten-Holz."""

from player.brain import actions, tactics
from player.brain.records import Candidate
from tests.helpers import make_snap


def test_saving_rule_protects_all_targets_not_just_best():
    snap = make_snap(
        resources={"wood": {"value": 140, "max": 400, "rate": 0.25},
                   "science": {"value": 330, "max": 3250, "rate": 1.45}},
    )
    research = Candidate(
        actions.research("metal", "Metal Working",
                         prices=[{"name": "science", "val": 900}]),
        0.0, {"milestone": 0.0}, feasible=False,
        reject_reason="noch nicht bezahlbar", eta_seconds=452.0)
    hut = Candidate(
        actions.buy_building("hut", "Hut", 4,
                             prices=[{"name": "wood", "val": 390}]),
        0.0, {"housing": 1.6, "potential": 2.8}, feasible=False,
        reject_reason="Sparziel", eta_seconds=1000.0)
    lib = Candidate(
        actions.buy_building("library", "Library", 12,
                             prices=[{"name": "wood", "val": 134}]),
        1.8, {"economy": 0.6, "netValue": 848.9})
    wait = Candidate(actions.wait("Warten", "Test"), 0.01, {"base": 0.01})
    cands = [lib, research, hut, wait]

    tactics._apply_saving_rule(snap, cands)

    # Die Library kollidiert nur mit dem ZWEITBESTEN Ziel (Hütte/Holz) —
    # vor dem Fix blieb sie deshalb straffrei (score 1.8) und wurde gekauft:
    assert lib.components.get("delayPenalty", 0) < 0
    assert lib.score < 0
    # Das bestwertige Ziel (Meilenstein, Science) bleibt unberührt korrekt:
    assert research.score == 0.0
