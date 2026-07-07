"""Golden-Fixtures + Replay-Tests (Spielmechanik-Spec 24.1 / Gap #32).

Drei eingefrorene Snapshots (tests/fixtures/*.json, erzeugt aus
make_snap-Szenarien, deterministisch, ohne Zeitstempel):
    early — frisches Spiel (kein Feld, kein Catnip)
    mid   — 2 freie Kitten, Holz-Engpass am Bibliotheks-Ziel
    late  — 106 Kitten (knapp vor Reset), ausgebaute Wirtschaft
"""

import pytest

from player.brain import meta, safety, tactics
from player.brain.records import state_hash
from tests.helpers import load_fixture

FIXTURES = ["early", "mid", "late"]

# Golden-Gewinner je Fixture: Bei BEWUSSTEN Verhaltensänderungen der Taktik
# (neue Gewichte/Regeln) diese Erwartungen prüfen und anpassen — der Test
# schützt vor UNBEABSICHTIGTEN Verschiebungen (Regression, Spec 24.2).
GOLDEN_WINNERS = {
    "early": "gather:catnip",
    "mid": "job:woodcutter",
    "late": "research:math",
}


def _run(snap):
    mview = meta.evaluate(snap)
    sres = safety.check(snap)
    cands, bn = tactics.generate(snap, mview, sres)
    selected = next((c for c in cands if c.feasible and c.score > 0),
                    next(c for c in cands if c.action.type == "WAIT"))
    return cands, bn, selected


@pytest.mark.parametrize("name", FIXTURES)
def test_generate_is_deterministic(name):
    """(a) Determinismus: zweimal generieren ⇒ identische Kandidatenliste
    (IDs, Scores, Feasibility) und identische Auswahl."""
    c1, _, s1 = _run(load_fixture(name))
    c2, _, s2 = _run(load_fixture(name))
    key = lambda cands: [(c.action.id, round(c.score, 9), c.feasible) for c in cands]
    assert key(c1) == key(c2)
    assert s1.action.id == s2.action.id


@pytest.mark.parametrize("name", FIXTURES)
def test_golden_winner(name):
    """(b) Golden: erwartete Gewinner-Action-ID je Fixture."""
    _, _, selected = _run(load_fixture(name))
    assert selected.action.id == GOLDEN_WINNERS[name], \
        f"{name}: Gewinner {selected.action.id} ≠ Golden {GOLDEN_WINNERS[name]}"


@pytest.mark.parametrize("name", FIXTURES)
def test_state_hash_stable(name):
    """(c) state_hash: stabil über zwei Läufe (Replay-Anker, Spec 23)."""
    assert state_hash(load_fixture(name)) == state_hash(load_fixture(name))


def test_state_hash_changes_on_resource_change():
    snap = load_fixture("mid")
    h1 = state_hash(snap)
    snap["resources"][0]["value"] += 1.0
    assert state_hash(snap) != h1


def test_state_hash_ignores_tick_noise():
    """Rundung (value/max auf 2, perSec auf 3 Nachkommastellen) filtert
    Sub-Cent-Rauschen zwischen zwei Reads."""
    snap = load_fixture("mid")
    h1 = state_hash(snap)
    snap["resources"][0]["value"] += 0.001
    assert state_hash(snap) == h1
