"""Tests der Spec-Gap-Runde #16/#23/#29/#30/#33: alle 13 Run-Typen,
Phasen P0–P8, Risikoterme (6.2), Craft-EffectiveCost/Cap-NetValue (11.2/11.4),
Optionswert (8.4) und generische Deadlock-Auflösung (22.3)."""

import math

import pytest

from player.brain import actions, meta, safety, simulate, tactics
from player.brain.meta import Milestone
from player.brain.records import Candidate
from tests.helpers import make_snap
from tests.test_endgame import frontier_snap


def _with_prestige(snap, paragon=0, karma=0, perks=None):
    snap["prestige"] = {"paragon": paragon, "burnedParagon": 0, "karma": karma,
                        "perks": perks or []}
    return snap


def _perks(names, researched=True):
    return [{"name": n, "label": n, "researched": researched, "unlocked": True,
             "prices": [{"name": "paragon", "val": 5}]} for n in names]


def _generate(snap, target=None):
    """Kandidaten mit injiziertem Ziel (target=None → kein aktives Ziel)."""
    mview = meta.evaluate(snap)
    mview.active = (Milestone("test", "Testziel", lambda s: False, target)
                    if target else None)
    return tactics.generate(snap, mview, safety.check(snap))


AB_PERK = {"name": "adjustmentBureau", "label": "Adjustment Bureau",
           "researched": True, "unlocked": True, "prices": []}
LEVIATHANS = {"name": "leviathans", "title": "Leviathans",
              "buys": [{"name": "unobtainium", "val": 5000}],
              "sells": [{"name": "timeCrystal", "value": 0.25, "chance": 98}]}


def _time_section(rr=1):
    return {"heat": 0, "heatMax": 100, "voidspace": [],
            "chronoforge": [{"name": "ressourceRetrieval",
                             "label": "Resource Retrieval", "val": rr,
                             "unlocked": True,
                             "prices": [{"name": "timeCrystal", "val": 1000}]}]}


# ================================================================ Run-Typen (8.2)
# Zulässigkeit aller 13 Typen — je Typ ein eigenes Fixture.

def test_first_run_admissible():
    snap = _with_prestige(make_snap())
    assert meta._admissible_run_types(snap) == ["FIRST_RUN"]


def test_price_ratio_run_admissible():
    snap = _with_prestige(make_snap(), paragon=40, karma=1)
    assert meta._admissible_run_types(snap) == ["PRICE_RATIO_RUN"]


def test_core_meta_run_after_price_ratio_chain():
    # Price-Ratio-Kette fertig, Pfad-Metas (Chronomancy…) offen → CORE_META.
    snap = _with_prestige(make_snap(), paragon=100, karma=2,
                          perks=_perks(meta.PRICE_RATIO_ORDER))
    assert meta._admissible_run_types(snap)[0] == "CORE_META_RUN"


def test_core_meta_run_for_extra_perks_beyond_chain():
    # Ganze 9.1-Kette fertig, aber Megalomania offen → CORE_META (8.2).
    perks = _perks(meta.METAPHYSICS_ORDER) + [
        {"name": "megalomania", "label": "Megalomania", "researched": False,
         "unlocked": True, "prices": [{"name": "paragon", "val": 10}]}]
    snap = _with_prestige(make_snap(kittens=5), paragon=50, karma=2, perks=perks)
    assert meta._admissible_run_types(snap)[0] == "CORE_META_RUN"
    # Restzeit-Ziel ist der günstigste offene Extra-Perk (finanzierbar → 0):
    proj = simulate.project(snap, 600.0)
    assert meta._plan_restzeit(snap, "CORE_META_RUN", proj, 600.0) == 0.0


def test_paragon_run_when_everything_bought():
    snap = _with_prestige(make_snap(), paragon=100, karma=2,
                          perks=_perks(meta.METAPHYSICS_ORDER))
    assert meta._admissible_run_types(snap) == ["PARAGON_RUN"]


def test_religion_run_admissible_and_restzeit():
    # Transcend-Bilanz positiv (15.2): Epiphany > Preis, Adore-Mehrgewinn
    # deckt den Tier-Preis, Worship-Wiederanlauf im Horizont.
    snap = make_snap(
        resources={"faith": {"value": 0, "max": 1e9, "rate": 500.0}},
        kittens=5,
        religion={"worship": 100000.0, "epiphany": 1.0,
                  "transcendenceTier": 0, "transcendenceOn": True})
    snap = _with_prestige(snap, paragon=10, karma=1)
    adm = meta._admissible_run_types(snap)
    assert "RELIGION_RUN" in adm
    proj = simulate.project(snap, 600.0)
    rz = meta._plan_restzeit(snap, "RELIGION_RUN", proj, 600.0)
    assert math.isfinite(rz) and rz > 0
    # Ohne positiven transcend_value-Pfad: nicht zulässig.
    snap2 = _with_prestige(make_snap(religion={"worship": 100.0}), paragon=10)
    assert "RELIGION_RUN" not in meta._admissible_run_types(snap2)


def test_unicorn_run_admissible_and_restzeit():
    snap = make_snap(
        resources={"unicorns": {"value": 0, "max": 0, "rate": 5.0}},
        buildings={"ziggurat": {"val": 1, "prices": {"megalith": 50}}},
        kittens=5)
    snap = _with_prestige(snap, paragon=10, karma=1)
    adm = meta._admissible_run_types(snap)
    assert "UNICORN_RUN" in adm
    # Zeit bis zum nächsten Opfer-Batch: 2500 Unicorns / 5 pro s = 500 s.
    proj = simulate.project(snap, 600.0)
    assert meta._plan_restzeit(snap, "UNICORN_RUN", proj, 600.0) == pytest.approx(500.0)
    # Ohne sichtbares Ziggurat: nicht zulässig.
    assert "UNICORN_RUN" not in meta._admissible_run_types(
        _with_prestige(make_snap(), paragon=10))


def test_challenge_run_admissible_and_binding():
    snap = _with_prestige(make_snap(challenges=[{"name": "winterIsComing"}]),
                          perks=[AB_PERK])
    assert "CHALLENGE_RUN" in meta._admissible_run_types(snap)
    active = _with_prestige(
        make_snap(challenges=[{"name": "winterIsComing", "active": True}]),
        perks=[AB_PERK])
    assert meta._admissible_run_types(active) == ["CHALLENGE_RUN"]


def test_leviathan_run_admissible():
    snap = make_snap(races=[LEVIATHANS])
    assert "LEVIATHAN_RUN" in meta._admissible_run_types(snap)


def test_shatter_run_admissible():
    snap = make_snap(resources={"timeCrystal": {"value": 30, "max": 0, "rate": 0.5}})
    snap["time"] = _time_section(rr=1)
    assert "SHATTER_RUN" in meta._admissible_run_types(snap)


def test_relic_station_run_admissible():
    snap = make_snap(resources={"antimatter": {"value": 100, "max": 500, "rate": 0}})
    assert "RELIC_STATION_RUN" in meta._admissible_run_types(snap)


def test_seed_and_positive_cs_run_admissible():
    snap = make_snap(
        resources={"unobtainium": {"value": 10000, "max": 20001, "rate": 1.0},
                   "void": {"value": 10, "max": 0, "rate": 0}},
        buildings={"chronosphere": {"val": 2, "prices": {"unobtainium": 100}}})
    adm = meta._admissible_run_types(snap)
    assert "SEED_RUN" in adm
    assert "POSITIVE_CS_RUN" in adm


def test_mature_endgame_run_admissible_after_frontier():
    assert "MATURE_ENDGAME_RUN" in meta._admissible_run_types(frontier_snap())
    assert "MATURE_ENDGAME_RUN" not in meta._admissible_run_types(make_snap())


def test_all_13_run_types_active():
    assert meta.ACTIVE_RUN_TYPES == meta.RUN_TYPES
    assert len(meta.RUN_TYPES) == 13


# ================================================================ Phasen (Kap. 9)

def test_phase_p0_fresh_game():
    assert meta.determine_phase(make_snap()) == "P0"


def test_phase_p2_after_price_ratio_chain():
    snap = _with_prestige(make_snap(), paragon=100, karma=2,
                          perks=_perks(meta.PRICE_RATIO_ORDER))
    assert meta.determine_phase(snap) == "P2"


def test_phase_p5_before_relic_station():
    snap = make_snap(
        resources={"unobtainium": {"value": 100, "max": 5000, "rate": 1.0},
                   "timeCrystal": {"value": 10, "max": 0, "rate": 0.1}},
        buildings={"ziggurat": {"val": 1, "prices": {"megalith": 50}}},
        races=[LEVIATHANS],
        religion={"worship": 100.0,
                  "upgrades": [{"name": "solarRevolution", "label": "SR",
                                "unlocked": True, "on": 1, "val": 1,
                                "noStackable": True, "prices": []}]})
    snap = _with_prestige(snap, paragon=500, karma=10,
                          perks=_perks(meta.METAPHYSICS_ORDER))
    # P0–P4 verlassen, aber Relic Station fehlt → P5 (Relic & Shatter).
    assert meta.determine_phase(snap) == "P5"


def test_phase_conservative_on_missing_data():
    # Persistenter Fortschritt, aber keine Perk-Daten → höchstens P1;
    # der Agent markiert keine spätere Phase als operational (Kap. 9).
    snap = _with_prestige(make_snap(), paragon=40, karma=1)
    assert meta.determine_phase(snap) == "P1"


def test_metaview_inherits_phase():
    view = meta.evaluate(_with_prestige(make_snap()))
    assert view.phase == "P0"
    assert view.to_dict()["phase"] == "P0"


# ================================================================ Risiko (6.2)

def test_projection_flags_food_fatal():
    snap = make_snap(resources={"catnip": {"value": 100, "max": 5000, "rate": -2.0}},
                     kittens=5)
    assert simulate.project(snap, 600.0).food_fatal() is True
    ok = make_snap(resources={"catnip": {"value": 100, "max": 5000, "rate": 2.0}},
                   kittens=5)
    assert simulate.project(ok, 600.0).food_fatal() is False
    # Ohne Catnip-Daten: konservativ kein geratenes Desaster.
    assert simulate.project(make_snap(kittens=5), 600.0).food_fatal() is False


def test_risk_term_kappa_lowers_score_on_food_risk():
    def shatter_snap(catnip_rate):
        s = make_snap(resources={
            "timeCrystal": {"value": 30, "max": 0, "rate": 0.5},
            "catnip": {"value": 100, "max": 5000, "rate": catnip_rate}},
            kittens=5)
        s["time"] = _time_section(rr=1)
        return s

    ok = meta._score_plans(shatter_snap(2.0), ["SHATTER_RUN"], 600.0)
    bad = meta._score_plans(shatter_snap(-2.0), ["SHATTER_RUN"], 600.0)
    assert ok[0]["pFatal"] == 0.0 and ok[0]["score"] == pytest.approx(0.0)
    assert bad[0]["pFatal"] == 1.0
    assert bad[0]["score"] == pytest.approx(-meta.KAPPA_FATAL_S)


def test_risk_term_mu_charges_reset_loss():
    # FIRST_RUN mit erreichtem Reset-Ziel (Restzeit 0 ≤ Horizont): der
    # λ-lose Verlustproxy = Wiederbeschaffungszeit der nicht persistenten
    # Bestände (1000 Catnip / 2 pro s = 500 s), gewichtet mit μ.
    snap = _with_prestige(make_snap(
        resources={"catnip": {"value": 1000, "max": 5000, "rate": 2.0}},
        kittens=110))
    rows = meta._score_plans(snap, ["FIRST_RUN"], 600.0)
    assert rows[0]["restzeit"] == 0.0
    assert rows[0]["irrevLossS"] == pytest.approx(500.0)
    assert rows[0]["score"] == pytest.approx(-meta.MU_IRREVERSIBLE_LOSS * 500.0)
    # SHATTER_RUN plant keinen Reset im Horizont → kein Verlustterm:
    assert "SHATTER_RUN" not in meta.RESET_ENDING_RUN_TYPES


# ================================================================ Craft (11.2)

def _plate_snap(goal_prices):
    crafts = [{"name": "plate", "label": "Plate", "unlocked": True,
               "prices": [{"name": "iron", "val": 125}]}]
    return make_snap(
        resources={"iron": {"value": 130, "max": 0, "rate": 0.0},
                   "science": {"value": 200, "max": 1000, "rate": 1.0},
                   "plate": {"value": 0, "max": 0, "rate": 0.0, "craftable": True}},
        techs={"gate": {"researched": False, "unlocked": True,
                        "prices": goal_prices}},
        crafts=crafts, jobs={"farmer": 3}, kittens=3)


def test_craft_netvalue_beats_depth_score_on_expensive_input():
    # Der Input (Iron) steckt ZUGLEICH im Zielpreisvektor → OpportunityCost
    # mit seinem λ (11.2). NetValue tief negativ → Score unter der Kaufregel-
    # Schwelle; der alte Tiefen-Score (2.0) hätte den Craft gewählt.
    snap = _plate_snap({"iron": 200, "plate": 5})
    cands, _ = _generate(snap, {"kind": "research", "name": "gate"})
    plate = next(c for c in cands if c.action.id == "craft:plate")
    assert plate.components["netValue"] < 0
    assert plate.score < 0.5


def test_craft_netvalue_positive_when_input_free_for_goal():
    # Iron NICHT im Zielvektor: sein λ kommt nur über die Kaskade aus dem
    # Produkt und kürzt sich gegen den Produktnutzen → NetValue > 0.
    snap = _plate_snap({"plate": 5, "science": 100})
    cands, _ = _generate(snap, {"kind": "research", "name": "gate"})
    plate = next(c for c in cands if c.action.id == "craft:plate")
    assert plate.components["netValue"] > 0
    assert plate.score > 2.0


def test_craft_fallback_depth_score_without_product_lambda():
    # Cap blockiert die Zielposition → λ_Produkt = 0 (Storage ist der Fix,
    # 11.3 A) → dokumentierter Fallback auf den alten Tiefen-Score.
    snap = _plate_snap({"plate": 5, "science": 100})
    next(r for r in snap["resources"] if r["name"] == "plate")["maxValue"] = 3
    cands, _ = _generate(snap, {"kind": "research", "name": "gate"})
    plate = next(c for c in cands if c.action.id == "craft:plate")
    assert plate.score == pytest.approx(2.0)
    assert plate.components == {"milestone": 2.0}


# ================================================================ Cap (11.4)

def _wood_cap_snap():
    crafts = [{"name": "beam", "label": "Beam", "unlocked": True,
               "prices": [{"name": "wood", "val": 175}]}]
    return make_snap(
        resources={"wood": {"value": 1900, "max": 2000, "rate": 1.0},
                   "science": {"value": 100, "max": 1000, "rate": 1.0},
                   "beam": {"value": 0, "max": 0, "rate": 0.0, "craftable": True}},
        techs={"x": {"researched": False, "unlocked": True,
                     "prices": {"science": 500}}},
        crafts=crafts, jobs={"farmer": 3}, kittens=3)


def test_cap_relief_craft_is_accepted_loss_when_worthless():
    # Trigger (0.92) feuert, aber weder Produkt noch Ziel bewerten den
    # Craft (λ_beam = 0) → „akzeptierter Verlust" ist die beste 11.4-Option.
    cands, _ = _generate(_wood_cap_snap(), {"kind": "research", "name": "x"})
    beam = next(c for c in cands if c.action.id == "craft:beam")
    assert not beam.feasible
    assert "11.4" in beam.reject_reason
    assert beam.components["netValue"] <= 0


def test_cap_relief_craft_fallback_without_lambda():
    # Ohne aktives Ziel (keine λ-Daten) bleibt das Bestandsverhalten:
    # fester capLoss-Score 1.6 am 0.92-Trigger.
    cands, _ = _generate(_wood_cap_snap(), None)
    beam = next(c for c in cands if c.action.id == "craft:beam")
    assert beam.feasible
    assert beam.score == pytest.approx(1.6)


def test_cap_relief_selection_by_netvalue():
    # Zielt der Plan auf Scaffolds (aus Beams), trägt der werterhaltende
    # Beam-Craft den λ-Wert des Produkts → positive NetValue-Auswahl (11.4).
    # Der Kandidat kommt aus der Kaskade (11.2, gleiche NetValue-Formel);
    # der 11.4-Zweig deferiert per seen-Guard statt zu duplizieren.
    snap = _wood_cap_snap()
    snap["workshop"]["crafts"].append(
        {"name": "scaffold", "label": "Scaffold", "unlocked": True,
         "prices": [{"name": "beam", "val": 50}]})
    snap["resources"].append({"name": "scaffold", "title": "Scaffold",
                              "value": 0.0, "maxValue": 0.0, "craftable": True,
                              "unlocked": True, "perSec": 0.0})
    cands, _ = _generate(snap, {"kind": "resource", "name": "scaffold",
                                "amount": 2})
    beam = next(c for c in cands if c.action.id == "craft:beam")
    assert beam.feasible
    assert beam.components["netValue"] > 0
    assert beam.score > 1.6      # NetValue hebt den Craft über den Fixwert


def test_gold_cap_trade_accepted_loss_and_fallback():
    races = [{"name": "zebras", "title": "Zebras",
              "buys": [{"name": "slab", "val": 50}],
              "sells": [{"name": "titanium", "value": 1.5, "chance": 15}]}]
    snap = make_snap(
        resources={"gold": {"value": 96, "max": 100, "rate": 0.1},
                   "manpower": {"value": 200, "max": 1000, "rate": 0.5},
                   "slab": {"value": 500, "max": 0, "rate": 0, "craftable": True},
                   "science": {"value": 100, "max": 1000, "rate": 1.0}},
        races=races, jobs={"farmer": 3}, kittens=3)
    # Mit λ-Daten, aber wertlosem Angebot (λ_titanium = 0): akzeptierter
    # Verlust statt blindem 0.95-Trade (11.4).
    cands, _ = _generate(snap, {"kind": "resource", "name": "science",
                                "amount": 500})
    trade = next(c for c in cands if c.action.id == "trade:zebras")
    assert not trade.feasible
    assert "11.4" in trade.reject_reason
    # Fallback ohne λ-Daten: altes Verhalten (fester capLoss-Score 1.1).
    cands, _ = _generate(snap, None)
    trade = next(c for c in cands if c.action.id == "trade:zebras")
    assert trade.feasible
    assert trade.score == pytest.approx(1.1)


# ================================================================ Optionswert (8.4)

def _option_snap():
    return make_snap(
        resources={"catnip": {"value": 100, "max": 10000, "rate": 2.0},
                   "science": {"value": 200, "max": 1000, "rate": 1.0},
                   "minerals": {"value": 500, "max": 1000, "rate": 0.5}},
        techs={"gate": {"researched": False, "unlocked": True,
                        "prices": {"catnip": 5000}},
               "calendar": {"researched": False, "unlocked": True,
                            "prices": {"science": 30}},
               "agriculture": {"researched": False, "unlocked": True,
                               "prices": {"science": 100}}},
        jobs={"farmer": 3}, kittens=3)


def test_option_value_boosts_research_on_goal_path():
    # Ziel ist Catnip-gebunden; Agriculture schaltet den Farmer-Job frei
    # (science.js:31-34) → berechneter OptionValue statt Pauschalbonus.
    cands, _ = _generate(_option_snap(), {"kind": "research", "name": "gate"})
    agri = next(c for c in cands if c.action.id == "research:agriculture")
    cal = next(c for c in cands if c.action.id == "research:calendar")
    assert agri.components["optionValue"] > 0
    assert agri.score > 1.9
    # Fallback: Tech ohne Referenz-Effekt behält den festen Unlock-Score.
    assert "optionValue" not in cal.components
    assert cal.score == pytest.approx(1.9)


def test_option_value_for_workshop_upgrade():
    snap = _option_snap()
    snap["workshop"]["upgrades"] = [
        {"name": "mineralHoes", "label": "Mineral Hoes", "unlocked": True,
         "researched": False,
         "prices": [{"name": "minerals", "val": 275}, {"name": "science", "val": 100}]}]
    cands, _ = _generate(snap, {"kind": "research", "name": "gate"})
    hoes = next(c for c in cands if c.action.id == "upgrade:mineralHoes")
    # ΔRate = 0.5 (catnipJobRatio, workshop.js:14) × 3 Farmer × 5/s.
    assert hoes.components["optionValue"] > 0
    assert hoes.score > 1.4


# ================================================================ Deadlock (22.3)

def test_is_deadlock_definition():
    wait_c = Candidate(actions.wait("x", "y"), 0.01, {"base": 0.01})
    pos = Candidate(actions.research("a", "A"), 1.9, {"unlock": 1.9})
    assert tactics.is_deadlock([wait_c], None)
    assert tactics.is_deadlock([wait_c], {"etaSeconds": None})
    assert not tactics.is_deadlock([wait_c, pos], None)         # positiver Kandidat
    assert not tactics.is_deadlock([wait_c], {"etaSeconds": 120})  # endlicher Weck


def _deadlock_snap(extra_buildings=None):
    """Kein positiver Kandidat: Engpass Wood ohne Rate (ETA ∞), nichts
    leistbar, keine Kitten. zebraForge (außerhalb der ECONOMY_WHITELIST)
    wird erst im gelockerten Suchraum sichtbar."""
    buildings = {"field": {"val": 10, "prices": {"catnip": 100}},
                 "barn": {"val": 0, "prices": {}}}
    buildings.update(extra_buildings or {})
    return make_snap(buildings=buildings)


def test_deadlock_stage_b_relaxes_whitelist_not_safety():
    snap = _deadlock_snap({"zebraForge": {"val": 0, "prices": {}}})
    mview = meta.evaluate(snap)
    sres = safety.check(snap)
    cands, bn = tactics.generate(snap, mview, sres)
    assert tactics.is_deadlock(cands, bn)
    # Normalzyklus kennt zebraForge nicht (Suchraum-Heuristik):
    assert not any(c.action.id == "build:zebraForge" for c in cands)

    cands, bn, dl = tactics.resolve_deadlock(snap, mview, sres)
    assert dl["stage"] == "b"                      # a (Horizont) reichte nicht
    forge = next(c for c in cands if c.action.id == "build:zebraForge")
    assert forge.feasible and forge.score > 0
    # Sicherheits-/Zulässigkeits-Gates bleiben UNGELOCKERT: Storage ohne
    # erfüllte 11.3-Bedingung wird auch im Deadlock-Modus abgelehnt.
    barn = next(c for c in cands if c.action.id == "build:barn")
    assert not barn.feasible
    assert "11.3" in barn.reject_reason


def test_deadlock_stage_c_publishes_frontier_notice():
    snap = _deadlock_snap()
    mview = meta.evaluate(snap)
    sres = safety.check(snap)
    cands, bn = tactics.generate(snap, mview, sres)
    assert tactics.is_deadlock(cands, bn)
    cands, bn, dl = tactics.resolve_deadlock(snap, mview, sres)
    assert dl["stage"] == "c"
    notice = dl["notice"]
    assert notice["id"] == "deadlock"
    assert "22.3" in notice["title"]
    assert notice["prompt"]
    # Auch nach der Eskalation bleibt WAIT die einzige Aktion:
    assert tactics.is_deadlock(cands, bn)
