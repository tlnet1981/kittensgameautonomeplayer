"""Tests für #40: Job-Marginalraten aus dem Spiel (ratesPerKitten).

Auftrag (docs/spec-gaps.md, Paket 3): target_allocation/job_score nutzen
die BEOBACHTETEN effektiven Raten je Kitten aus dem Snapshot; die
statische Tabelle JOB_BASE_RATES ist nur noch Fallback. Pflichttest:
ein Fall mit Upgrade-Multiplikatoren, in dem die statische Tabelle die
falsche Zuteilung getroffen hätte.
"""

from player.brain import shadow

from tests.helpers import make_snap


# ------------------------------------------------- job_marginal_rates

def test_observed_rates_are_authoritative():
    """Snapshot-Feld ratesPerKitten gewinnt über die statische Tabelle —
    auch die Happiness steckt schon drin (kein doppeltes Multiplizieren)."""
    snap = make_snap(
        jobs={"geologist": {"value": 2, "rates": {"coal": 0.2, "gold": 0.004}}},
        kittens=2,
    )
    snap["village"]["happiness"] = 1.5
    rates = shadow.job_marginal_rates(snap, "geologist")
    assert rates == {"coal": 0.2, "gold": 0.004}
    # job_score multipliziert NICHT erneut mit Happiness:
    assert shadow.job_score(snap, "geologist", {"coal": 1.0}) == 0.2


def test_empty_observed_rates_are_authoritative():
    """Leeres ratesPerKitten heißt: der Job produziert ehrlich nichts pro
    Tick (z. B. engineer) — KEIN Rückfall auf die Tabelle."""
    snap = make_snap(jobs={"priest": {"value": 1, "rates": {}}}, kittens=1)
    assert shadow.job_marginal_rates(snap, "priest") == {}
    assert shadow.job_score(snap, "priest", {"faith": 100.0}) == 0.0


def test_fallback_identity_without_snapshot_field():
    """Ohne ratesPerKitten (alter Driver): Basisrate × Happiness —
    bitidentisch zum bisherigen Verhalten."""
    snap = make_snap(jobs={"woodcutter": 1}, kittens=1)
    assert shadow.job_marginal_rates(snap, "woodcutter") == {"wood": 0.09}
    snap["village"]["happiness"] = 1.3
    rates = shadow.job_marginal_rates(snap, "woodcutter")
    assert abs(rates["wood"] - 0.09 * 1.3) < 1e-12
    # Unbekannter Job ohne Tabelleneintrag → leer:
    assert shadow.job_marginal_rates(snap, "engineer") == {}


# ------------------------------------------------- job_score (Pflichttest 1)

def test_geologist_with_drills_beats_miner_where_static_table_fails():
    """Mit Mining-/Unobtainium-Drill liegt die effektive Geologist-Rate
    weit über den statischen 0.075/s — der Job-Vergleich muss kippen."""
    lam = {"coal": 1.0, "minerals": 1.0}
    # Statische Tabelle (kein ratesPerKitten): miner 0.25 > geologist 0.075.
    static = make_snap(jobs={"miner": 0, "geologist": 0}, kittens=2)
    assert (shadow.job_score(static, "miner", lam)
            > shadow.job_score(static, "geologist", lam))
    # Beobachtete Raten (Drills + Geodesy): geologist 0.30 > miner 0.25.
    observed = make_snap(
        jobs={
            "miner": {"value": 0, "rates": {"minerals": 0.25}},
            "geologist": {"value": 0, "rates": {"coal": 0.30, "gold": 0.006}},
        },
        kittens=2,
    )
    assert (shadow.job_score(observed, "geologist", lam)
            > shadow.job_score(observed, "miner", lam))


# ------------------------------------------- target_allocation (Pflichttest 2)

def _alloc_snap(observed: bool) -> dict:
    """3 Kitten, alle Woodcutter; Upgrade-Multiplikatoren heben die
    effektive Woodcutter-Rate auf 0.153/s (statt Basis 0.09). Die
    beobachtete Holz-Rate 0.459/s stammt KOMPLETT von den 3 Woodcuttern."""
    wc_rate = 0.153
    if observed:
        jobs = {
            "woodcutter": {"value": 3, "rates": {"wood": wc_rate}},
            "scholar": {"value": 0, "rates": {"science": 0.175}},
        }
    else:
        jobs = {"woodcutter": 3, "scholar": 0}
    return make_snap(
        resources={
            "wood": {"value": 0.0, "rate": 3 * wc_rate},
            "science": {"value": 0.0, "rate": 0.0},
        },
        jobs=jobs,
        kittens=3,
    )


def test_target_allocation_without_phantom_leftover_rate():
    """Mit beobachteten Raten ist die Holz-Restrate nach Abzug der
    Kitten-Beiträge ehrlich 0 — die Zuteilung trifft das Engpass-Optimum
    {woodcutter: 2, scholar: 1} (max-ETA 653 s statt 571+ s Alternativen)."""
    goal = [{"name": "wood", "val": 100.0}, {"name": "science", "val": 100.0}]
    alloc = shadow.target_allocation(_alloc_snap(observed=True), goal)
    assert alloc == {"woodcutter": 2, "scholar": 1}


def test_static_table_misallocates_with_upgrade_multipliers():
    """Kontrollfall: der Fallback zieht nur 3×0.09 ab und lässt eine
    Phantom-Restrate von 0.189/s Holz stehen, die niemand produziert —
    die Zuteilung schickt ein Kitten zu wenig aufs Holz. Dieser Test
    dokumentiert die Fehlallokation, die #40 behebt (er bricht bewusst,
    falls jemand den Fallback 'verbessert', ohne #40 zu lesen)."""
    goal = [{"name": "wood", "val": 100.0}, {"name": "science", "val": 100.0}]
    alloc = shadow.target_allocation(_alloc_snap(observed=False), goal)
    assert alloc == {"woodcutter": 1, "scholar": 2}
