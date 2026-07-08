"""Tests des Economy-Kern-Pakets (#34+#35+#36, docs/spec-gaps.md):
Pfad-Schattenpreise (10.2/11.1), echte Gebäudeeffekte (13.1/13.2) und
wachsende Bevölkerung in Projektion und Housing (5.2/12.1)."""

import math

import pytest

from player.brain import meta, safety, shadow, tactics
from player.brain.meta import Milestone
from tests.helpers import make_snap


def _mview(active_target=None, open_targets=None):
    """Minimal-MetaView für deterministische path_targets-Tests."""
    active = (Milestone("test", "Testziel", lambda s: False, active_target)
              if active_target else None)
    return meta.MetaView(phase="P0", run_type="FIRST_RUN", active=active,
                         milestones=[], open_targets=open_targets)


# ================================================================ Pfad-λ (#34)

def test_path_weight_is_one_then_falls():
    assert shadow.path_weight(0) == 1.0
    assert shadow.path_weight(1) == pytest.approx(0.5)
    assert shadow.path_weight(3) > shadow.path_weight(7) > 0


def test_path_shadow_prices_weighted_max():
    """λ_i = max_k(w_k·λ_i^k): Rang-0-Ziel voll, Rang-1-Ziel halb gewichtet;
    dieselbe Ressource in mehreren Rängen → das stärkste Gewicht gewinnt."""
    snap = make_snap(resources={
        "wood": {"value": 0, "max": 1000, "rate": 0.5},
        "science": {"value": 0, "max": 1000, "rate": 0.1},
    })
    path = [
        {"prices": [{"name": "wood", "val": 25}], "weight": shadow.path_weight(0)},
        {"prices": [{"name": "science", "val": 10}], "weight": shadow.path_weight(1)},
        # wood nochmal weiter hinten — darf das Rang-0-λ nicht schmälern:
        {"prices": [{"name": "wood", "val": 100}], "weight": shadow.path_weight(2)},
    ]
    lam = shadow.path_shadow_prices(snap, path)
    assert lam["wood"] == pytest.approx(2.0, rel=0.01)       # 1/0.5, w=1
    assert lam["science"] == pytest.approx(5.0, rel=0.01)    # (1/0.1)·0.5


def test_path_targets_assembly_order_housing_and_research_fallback():
    """Rang 0 aktives Ziel, Rang 1 Housing (nur bei voller Kapazität),
    dann offene Meilensteine; unsichtbare Forschung → EIN Referenzeintrag."""
    snap = make_snap(
        resources={"wood": {"value": 0, "max": 500, "rate": 0.5}},
        buildings={"hut": {"val": 1, "prices": {"wood": 10}, "unlocked": True}},
        kittens=2, max_kittens=2,
    )
    mv = _mview(active_target={"kind": "resource", "name": "wood", "amount": 40},
                open_targets=[{"kind": "research", "name": "unsichtbar_a"},
                              {"kind": "research", "name": "unsichtbar_b"},
                              {"kind": "build", "name": "hut"}])
    pt = tactics.path_targets(snap, mv)
    labels = [e["label"] for e in pt]
    assert labels[0] == "active"
    assert labels[1] == "housing:hut"
    # genau EIN Referenz-Science-Eintrag für die unsichtbare Forschung:
    assert labels.count("research:unsichtbar_a") == 1
    assert "research:unsichtbar_b" not in labels
    ref = next(e for e in pt if e["label"] == "research:unsichtbar_a")
    assert ref["prices"] == [{"name": "science",
                              "val": tactics.REFERENCE_RESEARCH_SCIENCE}]
    # Gewichte fallen streng mit dem Rang:
    weights = [e["weight"] for e in pt]
    assert weights == sorted(weights, reverse=True) and weights[0] == 1.0


def test_path_targets_no_housing_when_capacity_free_and_capped_at_max():
    snap = make_snap(
        resources={"wood": {"value": 0, "max": 500, "rate": 0.5}},
        buildings={"hut": {"val": 1, "prices": {"wood": 10}, "unlocked": True},
                   **{f"b{i}": {"val": 0, "prices": {"wood": 5 + i},
                                "unlocked": True} for i in range(20)}},
        kittens=1, max_kittens=3,   # Kapazität frei → kein Housing-Rang
    )
    mv = _mview(active_target={"kind": "resource", "name": "wood", "amount": 40},
                open_targets=[{"kind": "build", "name": f"b{i}"}
                              for i in range(20)])
    pt = tactics.path_targets(snap, mv)
    assert not any(e["label"].startswith("housing:") for e in pt)
    assert len(pt) <= tactics.PATH_MAX_TARGETS


def test_lambda_furs_positive_when_hunting_useful_on_path():
    """Auftragstest (#34): λ_furs > 0, sobald ein Pfadziel Manuscripts
    braucht (Kaskade manuscript → parchment → furs) — und die Jagd läuft
    dann im λ-Zweig (huntValue) statt im 85-%-Fallback."""
    crafts = [
        {"name": "parchment", "label": "Parchment", "unlocked": True,
         "prices": [{"name": "furs", "val": 175}]},
        {"name": "manuscript", "label": "Manuscript", "unlocked": True,
         "prices": [{"name": "parchment", "val": 25},
                    {"name": "culture", "val": 400}]},
    ]
    snap = make_snap(
        resources={"catnip": {"value": 5000, "max": 5000, "rate": 10},
                   "manpower": {"value": 150, "max": 1000, "rate": 0.3},
                   "furs": {"value": 0, "max": 0, "rate": 0},
                   "parchment": {"value": 0, "max": 0, "rate": 0, "craftable": True},
                   "manuscript": {"value": 0, "max": 0, "rate": 0, "craftable": True},
                   "culture": {"value": 0, "max": 800, "rate": 0.1}},
        crafts=crafts, jobs={"farmer": 2}, kittens=2, max_kittens=4,
        catnip_field_base=40,
    )
    mv = _mview(active_target={"kind": "resource", "name": "manuscript",
                               "amount": 5})
    lam, lam_rate = tactics.path_lambdas(snap, mv)
    assert lam.get("furs", 0.0) > 0
    assert lam_rate.get("furs", 0.0) > 0
    # Integration: der Hunt-Kandidat trägt den λ-Erwartungswert (14.2):
    mv2 = meta.evaluate(snap)
    mv2.active = Milestone("test", "Testziel", lambda s: False,
                           {"kind": "resource", "name": "manuscript",
                            "amount": 5})
    cands, _ = tactics.generate(snap, mv2, safety.check(snap))
    hunt = next(c for c in cands if c.action.type == "HUNT")
    assert hunt.components.get("huntValue", 0.0) > 0


def test_lambda_top_sorted_and_capped():
    lam = {"wood": 5.0, "science": 12.0, "gold": 5.0, "iron": 0.0}
    lam_rate = {"wood": 100.0, "science": 300.0}
    top = tactics.lambda_top(lam, lam_rate, n=2)
    assert top == [{"name": "science", "lam": 12.0, "lamRate": 300.0},
                   {"name": "gold", "lam": 5.0, "lamRate": 0.0}]
    assert all(r["lam"] > 0 for r in tactics.lambda_top(lam, lam_rate))


# ================================================ Echte Gebäudeeffekte (#35)

def _gen_with_target(snap, target, open_targets=None):
    mv = _mview(active_target=target, open_targets=open_targets)
    return tactics.generate(snap, mv, safety.check(snap))[0]


def test_steamworks_gets_positive_netvalue_from_effects():
    """Auftragstest (#35): Steamworks bekommt über manuscriptPerTickProd
    einen echten positiven NetValue statt economy 0.6 (Ziel bepreist
    Manuscripts, keine Kohle-Produktion → coalRatioGlobal wirkungslos)."""
    snap = make_snap(
        resources={"catnip": {"value": 5000, "max": 5000, "rate": 10},
                   "wood": {"value": 100, "max": 1000, "rate": 0.5},
                   "manuscript": {"value": 0, "max": 0, "rate": 0,
                                  "craftable": True}},
        buildings={"steamworks": {"val": 0, "prices": {"wood": 10},
                                  "unlocked": True,
                                  "effects": {"manuscriptPerTickProd": 0.002,
                                              "coalRatioGlobal": -0.8,
                                              "energyProduction": 1,
                                              "cathPollutionPerTickProd": 1}}},
        jobs={"woodcutter": 1}, kittens=1, max_kittens=2, catnip_field_base=40,
    )
    cands = _gen_with_target(snap, {"kind": "resource", "name": "manuscript",
                                    "amount": 5})
    sw = next(c for c in cands if c.action.id == "build:steamworks")
    assert sw.feasible
    assert sw.components.get("netValue", 0) > 0
    assert sw.components.get("benefitTime", 0) > 0


def test_steamworks_coal_malus_only_on_first_copy():
    """coalRatioGlobal wird im Spiel NICHT mit der Gebäudezahl gestaffelt
    (buildings.js getEffect: effect = effectValue) — nur das erste Exemplar
    trägt den −80-%-Kohle-Malus; netto-negativer Nutzen wird transparent
    per Payback abgelehnt (kein Crash)."""
    def _snap(val, on):
        return make_snap(
            resources={"catnip": {"value": 5000, "max": 5000, "rate": 10},
                       "wood": {"value": 100, "max": 1000, "rate": 0.5},
                       "coal": {"value": 0, "max": 0, "rate": 10},
                       "manuscript": {"value": 0, "max": 0, "rate": 0,
                                      "craftable": True}},
            buildings={"steamworks": {"val": val, "on": on,
                                      "prices": {"wood": 10}, "unlocked": True,
                                      "effects": {"manuscriptPerTickProd": 0.002,
                                                  "coalRatioGlobal": -0.8}}},
            jobs={"woodcutter": 1}, kittens=1, max_kittens=2,
            catnip_field_base=40,
        )

    # Erstes Exemplar, Ziel bepreist Kohle → Malus dominiert; da der
    # Kaufpreis (Kohle) selbst λ trägt, lehnt das Payback-Gate ab:
    snap0 = _snap(0, 0)
    for r in snap0["resources"]:
        if r["name"] == "coal":
            r["value"] = 100      # Preis bezahlbar, Ziel weiter offen
    b0 = next(x for x in snap0["buildings"] if x["name"] == "steamworks")
    b0["prices"] = [{"name": "coal", "val": 50}]
    cands = _gen_with_target(snap0, {"kind": "resource", "name": "coal",
                                     "amount": 10000})
    sw = next(c for c in cands if c.action.id == "build:steamworks")
    assert not sw.feasible and "Payback" in sw.reject_reason
    assert sw.components.get("benefitTime", 0) < 0
    # Zweites Exemplar (on == 1): kein Kohle-Malus mehr im ΔRate:
    b = next(x for x in make_snap(
        buildings={"steamworks": {"val": 1, "on": 1, "prices": {"wood": 10},
                                  "unlocked": True,
                                  "effects": {"manuscriptPerTickProd": 0.002,
                                              "coalRatioGlobal": -0.8}}},
        resources={"coal": {"value": 0, "max": 0, "rate": 10},
                   "manuscript": {"value": 0, "max": 0, "rate": 0,
                                  "craftable": True}},
    )["buildings"] if x["name"] == "steamworks")
    snap2 = _snap(1, 1)
    delta = tactics._building_rate_delta(snap2, next(
        x for x in snap2["buildings"] if x["name"] == "steamworks"))
    assert "coal" not in delta
    assert delta.get("manuscript", 0) > 0


def test_mint_and_brewery_no_longer_skipped_by_whitelist():
    """Mint/Brewery liefen bisher nie durch die Ökonomie (Whitelist-Skip);
    jetzt echte Sekundenwerte: Mint mit Pelz-/Elfenbein-Ertrag positiv,
    Brewery mit reinem Catnip-Verbrauch transparent per Payback abgelehnt."""
    snap = make_snap(
        resources={"catnip": {"value": 50000, "max": 60000, "rate": 20},
                   "wood": {"value": 500, "max": 1000, "rate": 0.5},
                   "furs": {"value": 0, "max": 0, "rate": 0},
                   "ivory": {"value": 0, "max": 0, "rate": 0},
                   "gold": {"value": 50, "max": 100, "rate": 0.1},
                   "manpower": {"value": 100, "max": 1000, "rate": 0.3}},
        buildings={"mint": {"val": 0, "prices": {"wood": 20}, "unlocked": True,
                            "effects": {"goldPerTickCon": -0.005,
                                        "manpowerPerTickCon": -0.75,
                                        "fursPerTickProd": 0.00875,
                                        "ivoryPerTickProd": 0.0021,
                                        "goldMax": 100}},
                   "brewery": {"val": 0, "prices": {"wood": 20}, "unlocked": True,
                               "effects": {"catnipPerTickCon": -1,
                                           "festivalRatio": 0.01}}},
        jobs={"woodcutter": 1}, kittens=1, max_kittens=2, catnip_field_base=40,
    )
    # Pfad bepreist Furs (aktiv) sowie Catnip und Wood (offene Meilensteine)
    # — damit tragen Brauerei-Verbrauch UND Holzpreis λ:
    cands = _gen_with_target(
        snap, {"kind": "resource", "name": "furs", "amount": 1000},
        open_targets=[{"kind": "resource", "name": "catnip", "amount": 55000},
                      {"kind": "resource", "name": "wood", "amount": 800}])
    mint = next(c for c in cands if c.action.id == "build:mint")
    assert mint.feasible and mint.components.get("netValue", 0) > 0
    brewery = next(c for c in cands if c.action.id == "build:brewery")
    assert not brewery.feasible and "Payback" in brewery.reject_reason
    assert brewery.components.get("benefitTime", 0) < 0


def test_rate_delta_from_effects_mapping_matrix():
    """Effekt-Mapping (#35): PerTick-Klassen ×TPS, catnipPerTickBase
    ×Saisonmodifikator, DemandRatio ×Bedarf, Ratio ×beobachtete Rate,
    Max-/Skip-Effekte ohne ΔRate-Beitrag."""
    snap = make_snap(
        resources={"catnip": {"value": 1000, "max": 5000, "rate": 8},
                   "wood": {"value": 10, "max": 1000, "rate": 2.0},
                   "coal": {"value": 0, "max": 0, "rate": 1.0},
                   "beam": {"value": 0, "max": 0, "rate": 0.5,
                            "craftable": True}},
        kittens=4, max_kittens=4, season="spring",
    )
    b = {"name": "testbld", "val": 0, "on": 0, "effects": {
        "woodPerTickProd": 0.018,       # ×5 → +0.09
        "catnipPerTickCon": -1,         # ×5 → −5
        "catnipPerTickBase": 0.125,     # ×5×1.5 (Frühling) → +0.9375
        "woodRatio": 0.1,               # ×2.0 → +0.2
        "coalRatioGlobal": -0.8,        # on==0 → ×1.0 → −0.8
        "craftRatio": 0.05,             # craftbare Rate 0.5 → beam +0.025
        "goldMax": 100,                 # Storage → skip
        "tradeRatio": 0.015,            # Trade-EV → skip
        "energyProduction": 1,          # Energie-Regel → skip
    }}
    delta = tactics._building_rate_delta(snap, b)
    assert delta["wood"] == pytest.approx(0.09 + 0.2)
    assert delta["catnip"] == pytest.approx(-5 + 0.9375)
    assert delta["coal"] == pytest.approx(-0.8)
    assert delta["beam"] == pytest.approx(0.025)
    assert "gold" not in delta
    # Demand-Ratio gegen den echten Bedarf (derived.food.demandPerSec):
    demand = snap["derived"]["food"]["demandPerSec"]
    b2 = {"name": "pasture2", "val": 0, "on": 0,
          "effects": {"catnipDemandRatio": -0.005}}
    assert tactics._building_rate_delta(snap, b2)["catnip"] == pytest.approx(
        0.005 * demand)
    # Ohne effects-Key: Bestandsverhalten (beobachtete Rate / Anzahl):
    snap_old = make_snap(
        resources={"minerals": {"value": 10, "max": 500, "rate": 1.0}},
        buildings={"mine": {"val": 2, "prices": {"wood": 50}}})
    b_old = next(x for x in snap_old["buildings"] if x["name"] == "mine")
    assert tactics._building_rate_delta(snap_old, b_old) == {"minerals": 0.5}


def test_storage_cap_gains_prefer_snapshot_effects():
    b = {"name": "barn", "effects": {"catnipMax": 7500, "woodMax": 300,
                                     "energyConsumption": 1}}
    assert tactics._storage_cap_gains(b) == {"catnip": 7500, "wood": 300}
    assert tactics._storage_cap_gains({"name": "barn"}) == \
        tactics.STORAGE_CAP_GAINS["barn"]


def test_pollution_cost_zero_below_threshold_positive_above():
    """Pollution-Zeitkosten (#35): unterhalb der Spiel-Schwelle (5e8,
    buildings.js Level-2-Regime) ehrlich 0; darüber > 0 und wachsend."""
    def _snap(cath):
        return make_snap(
            resources={"wood": {"value": 10, "max": 1000, "rate": 2.0}},
            jobs={"woodcutter": 2}, kittens=2, max_kittens=4,
            kittens_per_sec=0.05, pollution={"cathPollution": cath},
        )
    effects = {"cathPollutionPerTickProd": 1.0}
    lam_rate = {"wood": 100.0}
    below = tactics._pollution_cost_time(_snap(1e8), effects, 1800.0, lam_rate)
    above = tactics._pollution_cost_time(_snap(6e8), effects, 1800.0, lam_rate)
    assert below == 0.0
    assert above > 0.0
    # Fallbacks → 0: keine pollution-Sektion / keine Rate / kein λ:
    snap_plain = make_snap(jobs={"woodcutter": 2}, kittens=2)
    assert tactics._pollution_cost_time(snap_plain, effects, 1800.0, lam_rate) == 0.0
    assert tactics._pollution_cost_time(_snap(6e8), effects, 1800.0, {}) == 0.0
    assert tactics._pollution_cost_time(_snap(6e8), {}, 1800.0, lam_rate) == 0.0


# ================================================== Wachsende Bevölkerung (#36/#41)

def test_first_run_restzeit_shortens_with_kitten_arrivals():
    """Auftragstest (#36): Mit exportierter Ankunftsrate wird die
    FIRST_RUN-Restzeit (paragon_eta bis 35) endlich/zustandsabhängig;
    ohne Rate bleibt sie ∞ (eingefrorene Population)."""
    from player.brain import simulate

    def _snap(kps):
        return make_snap(
            resources={"catnip": {"value": 500000, "max": 0, "rate": 50}},
            kittens=80, max_kittens=120, jobs={"farmer": 5},
            catnip_field_base=40, kittens_per_sec=kps,
        )

    horizon = 3600.0
    frozen = simulate.project(_snap(0.0), horizon)
    growing = simulate.project(_snap(0.05), horizon)
    rest_frozen = meta._plan_restzeit(_snap(0.0), "FIRST_RUN", frozen, horizon)
    rest_growing = meta._plan_restzeit(_snap(0.05), "FIRST_RUN", growing, horizon)
    assert math.isinf(rest_frozen)
    assert math.isfinite(rest_growing)
    # 25 fehlende Kitten (Paragon 10 → 35) bei 0,05/s ≈ 500 s:
    assert rest_growing == pytest.approx(500.0, rel=0.15)


def test_housing_benefit_uses_sequential_slot_fill():
    """Auftragstest (#41): benefitTime folgt der echten Ankunftsrate —
    Slots füllen sequenziell; ohne Rate bleibt die Sofort-Vollbelegung
    (Altverhalten als Fallback)."""
    horizon = 600.0
    lam_rate = {"wood": 100.0}

    def _benefit(kps):
        snap = make_snap(
            resources={"catnip": {"value": 50000, "max": 60000, "rate": 20},
                       "wood": {"value": 100, "max": 1000, "rate": 0.5}},
            buildings={"hut": {"val": 1, "prices": {"wood": 20},
                               "unlocked": True}},
            jobs={"woodcutter": 1}, kittens=2, max_kittens=2,
            catnip_field_base=40, kittens_per_sec=kps,
        )
        b = next(x for x in snap["buildings"] if x["name"] == "hut")
        comp, reject = tactics._housing_eval(snap, "hut", b, blocked=set(),
                                             lam={}, lam_rate=lam_rate,
                                             horizon=horizon)
        assert reject is None
        return comp.get("benefitTime", 0.0)

    full = _benefit(0.0)                      # Fallback: capacity × H
    assert full == pytest.approx(2 * horizon * shadow.JOB_BASE_RATES
                                 ["woodcutter"]["wood"] * 100.0)
    slow, faster = _benefit(0.01), _benefit(0.02)
    assert 0 < slow < faster < full           # monoton in der Ankunftsrate
    assert _benefit(1e-4) == 0.0              # Ankunft jenseits des Horizonts


def test_meta_evaluate_exposes_open_targets():
    """meta.evaluate verwirft die offenen Meilenstein-Targets nicht mehr."""
    snap = make_snap(resources={"catnip": {"value": 10, "max": 5000, "rate": 1}})
    mv = meta.evaluate(snap)
    assert mv.open_targets, "offene Meilensteine erwartet"
    open_states = {r["state"] for r in mv.milestones if r["state"] != "done"}
    assert open_states <= {"active", "pending"}
    assert len(mv.open_targets) >= 1
    assert all(isinstance(t, dict) and "kind" in t for t in mv.open_targets)
