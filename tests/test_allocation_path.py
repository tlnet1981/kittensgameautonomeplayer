"""Regressionstests für den Live-Fund „Forschungsziel ohne Scholars /
nie Miner / nie Hunter": Die Soll-Allokation (12.2) kennt seit dem
Pfad-Vektor alle offenen Pfad-Ressourcen (rang-diskontiert) plus
Manpower als Dauerposten, sobald der Hunter freigeschaltet ist."""

from player.brain import meta, safety, shadow, tactics
from tests.helpers import make_snap


def _alloc(snap):
    mv = meta.evaluate(snap)
    gp = tactics._target_prices(snap, mv.active.target if mv.active else None)
    pt = tactics.path_targets(snap, mv)
    ap = tactics._allocation_prices(snap, gp, mv.next_research, pt)
    return shadow.target_allocation(
        snap, ap, tactics._min_farmers(snap, snap.get("village", {}))), mv


def test_invisible_research_goal_still_staffs_scholar():
    """Aktives Ziel = Forschung, Tech noch UNSICHTBAR im Snapshot
    (Prerequisite fehlt): früher war der Zielvektor leer und kein Scholar
    wurde je zugeteilt. Jetzt trägt der Research-Referenz-Fallback des
    Pfadvektors Science in die Allokation."""
    techs = {t: {"researched": True} for t in
             ["calendar", "agriculture", "archery", "mining", "animal"]}
    snap = make_snap(
        resources={"catnip": {"value": 3000, "max": 5000, "rate": 6.0},
                   "wood": {"value": 30, "max": 400, "rate": 0.3},
                   "science": {"value": 120, "max": 675, "rate": 0.0}},
        buildings={"field": {"val": 20, "prices": {"catnip": 900}},
                   "hut": {"val": 3, "prices": {"wood": 45}},
                   "library": {"val": 2, "prices": {"wood": 25}},
                   "mine": {"val": 1, "prices": {"wood": 115}}},
        techs=techs,   # nächstes Ziel (z. B. metal) ist NICHT im Snapshot
        jobs={"woodcutter": 3, "farmer": 2, "scholar": 0},
        kittens=5, max_kittens=6,
    )
    alloc, mv = _alloc(snap)
    assert mv.active.target.get("kind") == "research"
    assert tactics._target_prices(snap, mv.active.target) is None
    assert alloc.get("scholar", 0) >= 1


def test_path_milestone_resource_staffs_miner():
    """Minerals kommen im Sofortziel nicht vor, wohl aber in einem offenen
    Pfad-Meilenstein (workshop/smelter): die tote Pfad-Ressource bekommt
    ein Kitten — früher blieb der Miner den ganzen Run leer."""
    snap = make_snap(
        resources={"catnip": {"value": 3000, "max": 5000, "rate": 8.0},
                   "wood": {"value": 50, "max": 400, "rate": 0.4},
                   "science": {"value": 100, "max": 675, "rate": 0.3},
                   "minerals": {"value": 5, "max": 500, "rate": 0.0}},
        buildings={"field": {"val": 15, "prices": {"catnip": 600}},
                   "hut": {"val": 3, "prices": {"wood": 45}},
                   "library": {"val": 2, "prices": {"wood": 25}},
                   "mine": {"val": 1, "prices": {"wood": 115}},
                   "workshop": {"val": 0, "prices": {"wood": 100,
                                                     "minerals": 400}}},
        techs={"calendar": {"researched": False, "unlocked": True,
                            "prices": {"science": 300}},
               "mining": {"researched": True, "unlocked": True,
                          "prices": {"science": 500}}},
        jobs={"woodcutter": 3, "farmer": 2, "scholar": 2, "miner": 0},
        kittens=7, max_kittens=8,
    )
    alloc, _ = _alloc(snap)
    assert alloc.get("miner", 0) >= 1


def test_hunter_staffed_once_unlocked():
    """Manpower steht in keinem Meilensteinpreis — ohne den Dauerposten
    (eine Jagdladung) gäbe es nie Hunter, nie Jagd, nie Furs/Happiness."""
    snap = make_snap(
        resources={"catnip": {"value": 3000, "max": 5000, "rate": 8.0},
                   "wood": {"value": 100, "max": 400, "rate": 0.5},
                   "science": {"value": 100, "max": 675, "rate": 0.3},
                   "manpower": {"value": 0, "max": 150, "rate": 0.0}},
        buildings={"field": {"val": 15, "prices": {"catnip": 600}},
                   "hut": {"val": 4, "prices": {"wood": 50}},
                   "library": {"val": 2, "prices": {"wood": 60}}},
        techs={"calendar": {"researched": False, "unlocked": True,
                            "prices": {"science": 300}},
               "agriculture": {"researched": True, "unlocked": True,
                               "prices": {"science": 100}}},
        jobs={"farmer": 2, "woodcutter": 3, "scholar": 2, "hunter": 0},
        kittens=7, max_kittens=8,
    )
    alloc, _ = _alloc(snap)
    assert alloc.get("hunter", 0) >= 1


def test_capped_and_unproducible_entries_do_not_paralyze_allocation():
    """Ein Cap-voller oder von keinem Job beeinflussbarer Posten (Gold)
    darf die Zeitsumme nicht dauerhaft dominieren — die übrigen Jobs
    werden weiter nach ETA verteilt."""
    snap = make_snap(
        resources={"catnip": {"value": 3000, "max": 5000, "rate": 8.0},
                   "wood": {"value": 20, "max": 400, "rate": 0.1},
                   "science": {"value": 250, "max": 250, "rate": 0.0},
                   "gold": {"value": 0, "max": 50, "rate": 0.0}},
        buildings={"field": {"val": 15, "prices": {"catnip": 600}},
                   "hut": {"val": 3, "prices": {"wood": 45}},
                   "library": {"val": 1, "prices": {"wood": 25}},
                   "tradepost": {"val": 0, "prices": {"wood": 500,
                                                      "minerals": 200,
                                                      "gold": 10}}},
        techs={"calendar": {"researched": False, "unlocked": True,
                            "prices": {"science": 400}}},
        jobs={"woodcutter": 1, "farmer": 2, "scholar": 2},
        kittens=5, max_kittens=6,
    )
    alloc, _ = _alloc(snap)
    # Science klebt am Cap (250/250) → Scholars sind dort wertlos, die
    # Kitten arbeiten an den beeinflussbaren Posten (Wood/Catnip):
    assert sum(alloc.values()) == 5
    assert alloc.get("woodcutter", 0) >= 1
