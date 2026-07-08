"""Tests der Spec-Gaps #10/#11/#13: Storage-Bedingungen B–D (11.3),
Energie-Drosselung (16.4) und Leader-Wahl (12.3)."""

from player.brain import meta, safety, tactics
from player.brain.meta import Milestone
from player.state.derived import derive
from tests.helpers import make_snap


def _generate(snap, target=None):
    sres = safety.check(snap)
    mview = meta.evaluate(snap)
    if target is not None:
        mview.active = Milestone("test", "Testziel", lambda s: False, target)
    cands, bn = tactics.generate(snap, mview, sres)
    return cands, bn


def _clear_target(mview):
    # Seit #34 speist auch open_targets den Pfad-λ — für „keine λ-Daten"
    # müssen beide Quellen weg (der Fallback bleibt so testbar).
    mview.active = None
    mview.open_targets = None
    return mview


# ================================================================ Storage 11.3

def _storage_b_snap(chronospheres: int):
    """Ziel braucht 400 Wood (Cap 1000 blockiert NICHT → kein A); Barn ist
    leistbar; λ_wood > 0 über den Zielpreisvektor."""
    return make_snap(
        resources={"catnip": {"value": 500, "max": 5000, "rate": 5},
                   "wood": {"value": 60, "max": 1000, "rate": 0.5}},
        buildings={"hut": {"val": 2, "prices": {"wood": 400}},
                   "barn": {"val": 1, "prices": {"wood": 50}},
                   "chronosphere": {"val": chronospheres,
                                    "prices": {"unobtainium": 2500}}},
        jobs={"woodcutter": 2}, kittens=2, max_kittens=4,
        catnip_field_base=15,
    )


def test_storage_b_fires_with_chronospheres_and_lambda():
    """11.3 B: Carryover-Wert (Cap-Zuwachs × k·1,5 % × λ) > Baukosten →
    Barn zulässig, storageB-Sekundenwert sichtbar."""
    snap = _storage_b_snap(chronospheres=20)
    cands, _ = _generate(snap, {"kind": "build", "name": "hut"})
    barn = next(c for c in cands if c.action.id == "build:barn")
    assert barn.feasible
    assert barn.components.get("storage", 0) > 0
    assert barn.components.get("storageB", 0) > 0
    # storageB ist Anzeige-Sekundenwert und zählt nicht additiv in den Score:
    assert barn.score < barn.components["storageB"]


def test_storage_b_not_without_chronospheres():
    """Ohne Chronosphere existiert kein Carryover → B greift nicht, keine
    andere Bedingung erfüllt → Barn unzulässig."""
    snap = _storage_b_snap(chronospheres=0)
    cands, _ = _generate(snap, {"kind": "build", "name": "hut"})
    barn = next(c for c in cands if c.action.id == "build:barn")
    assert not barn.feasible
    assert "storageB" not in barn.components


def test_storage_rejection_names_conditions_a_to_d():
    snap = _storage_b_snap(chronospheres=0)
    cands, _ = _generate(snap, {"kind": "build", "name": "hut"})
    barn = next(c for c in cands if c.action.id == "build:barn")
    assert not barn.feasible
    assert "11.3 A–D" in barn.reject_reason
    for cond in ("(A)", "(B)", "(C)", "(D)"):
        assert cond in barn.reject_reason


def test_storage_c_fires_on_imminent_cap_overflow():
    """11.3 C: Catnip (λ > 0) läuft in ~5 s ans Cap (< 60-s-Puffer) →
    bewerteter Verlust übersteigt die Baukosten → Barn zulässig."""
    snap = make_snap(
        resources={"catnip": {"value": 4900, "max": 5000, "rate": 20},
                   "wood": {"value": 60, "max": 1000, "rate": 0}},
        buildings={"barn": {"val": 1, "prices": {"wood": 50}}},
        jobs={"farmer": 2}, kittens=2, max_kittens=4,
        catnip_field_base=15,
    )
    cands, _ = _generate(snap, {"kind": "resource", "name": "catnip",
                                "amount": 4950})
    barn = next(c for c in cands if c.action.id == "build:barn")
    assert barn.feasible
    assert barn.components.get("storage", 0) > 0
    assert barn.components.get("storageC", 0) > 0


def test_storage_d_gate_inactive_without_challenge_data():
    """11.3 D ist ohne Challenge-Daten im Snapshot dokumentiert inaktiv —
    mit `challenges.activeRequiresCap` greift es."""
    snap = _storage_b_snap(chronospheres=0)
    snap["challenges"] = {"activeRequiresCap": ["wood"]}
    cands, _ = _generate(snap, {"kind": "build", "name": "hut"})
    barn = next(c for c in cands if c.action.id == "build:barn")
    assert barn.feasible
    assert barn.components.get("storage", 0) > 0


# ================================================================ Energie 16.4

def _energy_snap(with_energy_fields=True, deficit=True):
    """Zwei Verbraucher: Biolab (großer λ-Zielbeitrag: Science ist Engpass)
    und Calciner (Zielbeitrag 0: Iron ist nicht der Engpass) — plus ein
    lebenswichtiges Gebäude (Aqueduct) mit fiktivem Verbrauch."""
    snap = make_snap(
        resources={"catnip": {"value": 40000, "max": 50000, "rate": 50},
                   "science": {"value": 1000, "max": 0, "rate": 10},
                   "iron": {"value": 10, "max": 0, "rate": 1}},
        buildings={"biolab": {"val": 2, "prices": {"titanium": 100}},
                   "calciner": {"val": 2, "prices": {"titanium": 100}},
                   "aqueduct": {"val": 2, "prices": {"titanium": 100}}},
        techs={"foo": {"researched": False, "unlocked": True,
                       "prices": {"science": 10000, "iron": 500}}},
        jobs={"farmer": 5}, kittens=5, catnip_field_base=60,
    )
    if with_energy_fields:
        for b in snap["buildings"]:
            b["energyConsumption"] = 5 if b["name"] == "aqueduct" else 1
            b["energyProduction"] = 0
    snap["energy"] = {"prod": 2, "cons": 6} if deficit else {"prod": 3, "cons": 2}
    return derive(snap)


def test_energy_deficit_toggles_off_smallest_contribution():
    snap = _energy_snap()
    cands, _ = _generate(snap, {"kind": "research", "name": "foo"})
    off = [c for c in cands if c.action.id.startswith("toggle:")]
    assert len(off) == 1
    # Calciner hat den kleinsten λ-Zielbeitrag je Energieeinheit (Iron ist
    # nicht der Engpass) — Biolab (Science = Engpass) bleibt an:
    assert off[0].action.id == "toggle:calciner:off"
    assert off[0].components.get("energyRelief", 0) > 0


def test_energy_vital_buildings_never_toggled():
    """Aqueduct (Food-relevant) hat hier den größten Verbrauch und gar keinen
    Produktions-Zielbeitrag — wird trotzdem NIE abgeschaltet."""
    snap = _energy_snap()
    cands, _ = _generate(snap, {"kind": "research", "name": "foo"})
    assert not any(c.action.id == "toggle:aqueduct:off" for c in cands)


def test_energy_hysteresis_blocks_immediate_reactivation():
    """Nach dem Abschalten (Überschuss < Verbrauch + Marge) wird NICHT sofort
    reaktiviert; erst deutlicher Überschuss erzeugt den toggle_on-Kandidaten."""
    snap = _energy_snap(deficit=False)          # balance = +1
    calciner = next(b for b in snap["buildings"] if b["name"] == "calciner")
    calciner["on"] = 1                          # eine Einheit ist abgeschaltet
    cands, _ = _generate(snap, {"kind": "research", "name": "foo"})
    # Hysterese: 1 <= Verbrauch (1) + Marge (1) → kein Anschalt-Kandidat:
    assert not any(c.action.id.endswith(":on") for c in cands)

    snap["energy"] = {"prod": 10, "cons": 2}    # balance = +8 > 1 + 1
    derive(snap)
    cands, _ = _generate(snap, {"kind": "research", "name": "foo"})
    on = [c for c in cands if c.action.id.endswith(":on")]
    assert len(on) == 1
    assert on[0].action.id == "toggle:calciner:on"


def test_energy_reactivation_prefers_largest_contribution():
    """Grenznutzen-Reihenfolge (16.4 Schritt 5): sind mehrere Einheiten aus,
    wird zuerst die mit dem größten λ-Zielbeitrag angeschaltet."""
    snap = _energy_snap(deficit=False)
    snap["energy"] = {"prod": 10, "cons": 2}
    derive(snap)
    for name in ("biolab", "calciner"):
        next(b for b in snap["buildings"] if b["name"] == name)["on"] = 1
    cands, _ = _generate(snap, {"kind": "research", "name": "foo"})
    on = [c for c in cands if c.action.id.endswith(":on")]
    assert len(on) == 1
    assert on[0].action.id == "toggle:biolab:on"   # Science = Engpass


def test_energy_fallback_without_snapshot_fields():
    """Ohne energyConsumption-Felder im Snapshot: Altverhalten, kein Toggle."""
    snap = _energy_snap(with_energy_fields=False)
    cands, _ = _generate(snap, {"kind": "research", "name": "foo"})
    assert not any(c.action.id.startswith("toggle:") for c in cands)


def test_energy_fallback_without_lambda_data():
    """Defizit, aber kein aktives Ziel (keine λ-Daten) → kein Toggle-Kandidat."""
    snap = _energy_snap()
    sres = safety.check(snap)
    mview = _clear_target(meta.evaluate(snap))
    cands, _ = tactics.generate(snap, mview, sres)
    assert not any(c.action.id.startswith("toggle:") for c in cands)


# ================================================================ Leader 12.3

def _leader_snap(science_value=100.0, science_rate=1.0, science_price=20000):
    snap = make_snap(
        resources={"catnip": {"value": 4000, "max": 5000, "rate": 15},
                   "science": {"value": science_value, "max": 0,
                               "rate": science_rate}},
        techs={"physics": {"researched": False, "unlocked": True,
                           "prices": {"science": science_price}}},
        jobs={"farmer": 5}, kittens=5, catnip_field_base=60,
    )
    snap["village"]["census"] = [
        {"index": 0, "name": "Miau Erstens", "trait": "none",
         "job": "farmer", "isLeader": False},
        {"index": 1, "name": "Miau Zweitens", "trait": "scientist",
         "job": "farmer", "isLeader": False},
    ]
    snap["village"]["censusTruncated"] = False
    return snap


def test_leader_first_choice_without_leader():
    """Erstwahl: kein Leader gesetzt → bestes Trait/Ziel-Paar wird ernannt
    (scientist adressiert den Science-Engpass des Forschungsziels)."""
    snap = _leader_snap()
    cands, _ = _generate(snap, {"kind": "research", "name": "physics"})
    leader = next(c for c in cands if c.action.id.startswith("leader:"))
    assert leader.action.id == "leader:1"
    assert leader.components.get("leader", 0) > 0
    assert leader.components.get("leaderValue", 0) > 0


def test_leader_switch_only_above_threshold():
    """Wechsel nur, wenn der Gewinn die Wechsel-/Interaktionskosten übersteigt
    (Anti-Flattern, Spec 12.3)."""
    # Kleiner Gewinn (λ und Fehlmenge winzig) → kein Wechsel-Kandidat:
    snap = _leader_snap(science_value=900, science_rate=10, science_price=1000)
    snap["village"]["leader"] = {"name": "Miau Erstens", "trait": "none",
                                 "job": "farmer"}
    snap["village"]["census"][0]["isLeader"] = True
    cands, _ = _generate(snap, {"kind": "research", "name": "physics"})
    assert not any(c.action.id.startswith("leader:") for c in cands)

    # Großer Gewinn (0.05 × λ × 19900 Science ≫ Schwelle) → Wechsel:
    snap = _leader_snap(science_value=100, science_rate=1, science_price=20000)
    snap["village"]["leader"] = {"name": "Miau Erstens", "trait": "none",
                                 "job": "farmer"}
    snap["village"]["census"][0]["isLeader"] = True
    cands, _ = _generate(snap, {"kind": "research", "name": "physics"})
    leader = next(c for c in cands if c.action.id.startswith("leader:"))
    assert leader.action.id == "leader:1"
    assert leader.components.get("leaderValue", 0) > tactics.LEADER_SWITCH_MIN_S


def test_leader_no_candidate_without_census():
    snap = _leader_snap()
    del snap["village"]["census"]
    cands, _ = _generate(snap, {"kind": "research", "name": "physics"})
    assert not any(c.action.id.startswith("leader:") for c in cands)


def test_leader_no_switch_when_best_already_leads():
    snap = _leader_snap()
    snap["village"]["leader"] = {"name": "Miau Zweitens", "trait": "scientist",
                                 "job": "farmer"}
    snap["village"]["census"][1]["isLeader"] = True
    cands, _ = _generate(snap, {"kind": "research", "name": "physics"})
    assert not any(c.action.id.startswith("leader:") for c in cands)
