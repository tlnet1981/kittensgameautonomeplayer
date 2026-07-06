"""Tests der M7-Logik: Paragon-Speedrun-Regel (Spec 20.4) und Run-Typ-Wechsel."""

import time

from player.brain import meta, reset
from tests.helpers import make_snap


def test_paragon_run_after_metaphysics_chain():
    perks = [{"name": n, "label": n, "researched": True, "unlocked": True,
              "prices": [{"name": "paragon", "val": 1}]}
             for n in meta.METAPHYSICS_ORDER]
    snap = make_snap()
    snap["prestige"] = {"paragon": 500, "burnedParagon": 0, "karma": 10, "perks": perks}
    assert meta.determine_run(snap) == "PARAGON_RUN"


def _samples(rates):
    """Baut (ts, projection)-Verlauf aus (dauer_s, rate_pro_s)-Segmenten."""
    samples = []
    t = 1000.0
    p = 0.0
    for dur, rate in rates:
        steps = int(dur // 30)
        for _ in range(steps):
            t += 30
            p += rate * 30
            samples.append((t, int(p)))
    return samples


def _snap_with_projection(projection):
    snap = make_snap(kittens=70 + projection)
    snap["prestige"] = {"paragon": 0, "burnedParagon": 0, "karma": 1, "perks": []}
    return snap


def test_speedrun_resets_when_marginal_rate_collapses():
    # 25 min gute Rate, dann 6 min fast nichts → marginal << Ø → Reset
    samples = _samples([(25 * 60, 0.05), (6 * 60, 0.001)])
    snap = _snap_with_projection(int(samples[-1][1]))
    ev = reset.evaluate(snap, "PARAGON_RUN", None, samples)
    assert ev["recommended"], ev["reason"]


def test_speedrun_continues_while_rate_holds():
    samples = _samples([(31 * 60, 0.05)])
    snap = _snap_with_projection(int(samples[-1][1]))
    ev = reset.evaluate(snap, "PARAGON_RUN", None, samples)
    assert not ev["recommended"], ev["reason"]


def test_speedrun_needs_minimum_runtime():
    samples = _samples([(5 * 60, 0.05), (5 * 60, 0.0)])
    snap = _snap_with_projection(int(samples[-1][1]))
    ev = reset.evaluate(snap, "PARAGON_RUN", None, samples)
    assert not ev["recommended"]
