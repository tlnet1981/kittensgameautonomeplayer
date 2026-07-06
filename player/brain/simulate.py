"""Deterministische EV-Vorwärtsprojektion als Makro-Planbewerter (Spec 5/6.2).

Bewusst KEIN Monte-Carlo: Der Grundsatz „das Spiel ist das Modell" gilt
weiter für die Taktik (dort wird der echte Zustand gelesen, nicht simuliert).
Diese Projektion dient ausschließlich der MAKRO-Planbewertung (Spec 8.3):
sie integriert die wichtigsten Ressourcenbestände stückweise über einen
Horizont — Erwartungswerte statt Verteilungen, jede Eingabe kommt aus dem
Snapshot, jede Annahme steht dokumentiert im Code.

Ereignispunkte der stückweisen Integration (Spec 5.3, reduziert):
- Saisonwechsel (Konstanten wie state/derived.py: 5 Ticks/s, 1 Tag = 2 s,
  100 Tage/Saison, 4 Saisons/Jahr) — betrifft die Catnip-Feldproduktion.
- Erwartete Kitten-Ankünfte: NUR wenn der Snapshot eine Ankunftsrate
  (village.kittensPerSec) UND eine bekannte Housing-Kapazität (maxKittens)
  liefert; der Standard-Snapshot (driver/snapshot.js) enthält keine
  Ankunftsrate → dann werden Ankünfte konservativ ignoriert (Kittenzahl
  bleibt konstant, keine geschätzte Mehrlast, keine geschenkte Paragonrate).
  Ankommende Kitten erhöhen die Catnip-Mehrlast (0,85/Tick × 5 Ticks/s).

policy = {"invest": 0..1} ist der leichte Hebel für Makro-Varianten
(Spec 8.3 a/b/c): der Anteil f der laufenden Produktion, der rechnerisch
in Ausbau fließt. Approximation: dem Bestand kommt nur (1−f) der Produktion
zu, dafür wachsen die Produktionsraten linear mit m(t) = 1 + f·t/INVEST_TAU.
Begründung der Konstante INVEST_TAU = 300 s: im Frühspiel verzinst sich
reinvestierte Produktion extrem schnell (ein Catnip-Feld: ~16 Catnip Kosten,
+0,625/s Ertrag → Payback < 30 s; echtes Reinvestieren wäre exponentiell).
Die lineare Rampe „+100 % Raten je 300 s bei f = 1" ist dagegen stark
gedämpft und deterministisch integrierbar; sie ist so gewählt, dass sich
die drei Standardvarianten (0,15/0,35/0,6) innerhalb des Horizontfensters
[10 min, 4 h] tatsächlich unterscheiden (Minimalpfad dominiert kurze,
investitionsstarker Pfad lange Horizonte). Verbrauch (negative Netto-Raten)
wird nicht mitskaliert — Investition frisst keinen Konsum weg.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from player.state import access as A

EPS = 1e-9
SECONDS_PER_DAY = 2.0                      # wie state/derived.py
DEFAULT_SEASON_MODS = [1.5, 1.0, 1.0, 0.25]
# Verbrauch eines Kittens (0,85 Catnip/Tick × 5 Ticks/s), wie tactics.py:
CATNIP_PER_KITTEN_PER_SEC = 4.25
# invest-Rampe: bei f = 1 wachsen die Raten um +100 % je INVEST_TAU Sekunden.
INVEST_TAU = 300.0

# Projizierte Kernressourcen (Cap-Klemmen!); alles andere gilt als konstant.
TRACKED = ("catnip", "wood", "minerals", "science", "faith", "gold", "manpower")


def has_projection_data(snap: dict) -> bool:
    """Reicht der Snapshot für eine sinnvolle Projektion? (Alt-Tests nutzen
    leere Snapshots — dort greift der Fallback auf die feste Ableitung.)"""
    if snap.get("village", {}).get("kittens", 0) > 0:
        return True
    return any(r["name"] in TRACKED for r in snap.get("resources", []))


def run_elapsed_seconds(snap: dict) -> float:
    """Bisherige Run-Spielzeit aus dem Kalender (Reset setzt ihn auf null)."""
    cal = snap.get("calendar", {})
    dps = float(cal.get("daysPerSeason", 100)) or 100.0
    return (cal.get("year", 0) * 4 * dps + cal.get("season", 0) * dps
            + cal.get("day", 0)) * SECONDS_PER_DAY


@dataclass
class Projection:
    """Ergebnis der stückweisen Integration: Checkpoints an Segmentgrenzen.

    Zwischen Checkpoints verlaufen die Bestände (nahezu) linear — eta_of
    und paragon_eta interpolieren linear (die invest-Rampe macht Segmente
    leicht konvex; die Näherung ist konservativ klein, Segmente ≤ 200 s).
    """
    horizon_s: float
    invest: float
    times: list[float] = field(default_factory=list)
    series: list[dict[str, float]] = field(default_factory=list)
    kittens: list[float] = field(default_factory=list)
    year0: int = 0
    day_into_year: float = 0.0
    days_per_year: float = 400.0
    static_values: dict[str, float] = field(default_factory=dict)

    # ------------------------------------------------------------ Bestände
    @property
    def final(self) -> dict[str, float]:
        """Endbestände der projizierten Ressourcen."""
        return self.series[-1] if self.series else {}

    def _value_at(self, idx: int, name: str) -> float:
        row = self.series[idx]
        if name in row:
            return row[name]
        return self.static_values.get(name, 0.0)   # nicht projiziert → konstant

    def _kittens_at(self, t: float) -> float:
        for i in range(1, len(self.times)):
            if t <= self.times[i] + EPS:
                t0, t1 = self.times[i - 1], self.times[i]
                frac = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
                return self.kittens[i - 1] + frac * (self.kittens[i] - self.kittens[i - 1])
        return self.kittens[-1] if self.kittens else 0.0

    # ------------------------------------------------------------ Paragon
    def paragon_projection(self, t: float) -> float:
        """Reset-Paragon zum Zeitpunkt t: max(0, kittens−70) + year//1000
        (Formel wie derived.py resetParagon, Anhang D)."""
        year = self.year0 + int((self.day_into_year + t / SECONDS_PER_DAY)
                                // self.days_per_year)
        return max(0.0, self._kittens_at(t) - 70.0) + year // 1000

    def paragon_eta(self, target: float) -> float:
        """Zeit bis Reset-Paragon ≥ target (inf, wenn nicht im Horizont)."""
        if self.paragon_projection(0.0) >= target - EPS:
            return 0.0
        for i in range(1, len(self.times)):
            p1 = self.paragon_projection(self.times[i])
            if p1 >= target - EPS:
                t0, t1 = self.times[i - 1], self.times[i]
                p0 = self.paragon_projection(t0)
                frac = 1.0 if p1 <= p0 else (target - p0) / (p1 - p0)
                return t0 + max(0.0, min(1.0, frac)) * (t1 - t0)
        return math.inf

    # ------------------------------------------------------------ ETA
    def eta_of(self, prices: list[dict]) -> float:
        """Zeit bis der Preisvektor innerhalb der Projektion bezahlbar ist
        (inf, wenn nicht im Horizont). Nicht projizierte Ressourcen zählen
        mit ihrem konstanten Snapshot-Bestand."""
        if not prices:
            return 0.0

        def ok(idx: int) -> bool:
            return all(self._value_at(idx, p["name"]) + EPS >= p["val"] for p in prices)

        if ok(0):
            return 0.0
        for i in range(1, len(self.times)):
            if not ok(i):
                continue
            t0, t1 = self.times[i - 1], self.times[i]
            worst = t0
            for p in prices:
                v0 = self._value_at(i - 1, p["name"])
                if v0 + EPS >= p["val"]:
                    continue
                v1 = self._value_at(i, p["name"])
                frac = 1.0 if v1 <= v0 else (p["val"] - v0) / (v1 - v0)
                worst = max(worst, t0 + frac * (t1 - t0))
            return worst
        return math.inf

    def summary(self) -> dict:
        """Kompaktes Ergebnis für Records/Cockpit."""
        return {
            "horizonS": round(self.horizon_s, 1),
            "invest": self.invest,
            "final": {k: round(v, 1) for k, v in self.final.items()},
            "kittensEnd": round(self.kittens[-1], 2) if self.kittens else 0,
            "paragonEnd": round(self.paragon_projection(self.horizon_s), 2),
        }


def _integral(rate: float, invest: float, t0: float, t1: float) -> float:
    """∫ rate·(1−f)·(1+f·t/τ) dt über [t0,t1]; Verbrauch (rate ≤ 0) wächst
    nicht mit und wird auch nicht um (1−f) gekürzt (Konsum ist kein Invest)."""
    dt = t1 - t0
    if rate <= 0.0 or invest <= 0.0:
        return rate * dt
    return rate * (1.0 - invest) * (dt + invest * (t1 * t1 - t0 * t0) / (2.0 * INVEST_TAU))


def project(snap: dict, horizon_s: float, *, policy: dict | None = None) -> Projection:
    """Stückweise EV-Projektion der Kernressourcen über horizon_s Sekunden."""
    invest = max(0.0, min(1.0, float((policy or {}).get("invest", 0.0))))
    cal = snap.get("calendar", {})
    tps = snap.get("meta", {}).get("ticksPerSecond", 5)
    mods = cal.get("seasonCatnipModifiers") or DEFAULT_SEASON_MODS
    season = int(cal.get("season", 0)) % 4
    day = float(cal.get("day", 0))
    dps = float(cal.get("daysPerSeason", 100)) or 100.0
    field_base = snap.get("effects", {}).get("catnipPerTickBase", 0.0) * tps
    mod_now = mods[season] if season < len(mods) else 1.0

    village = snap.get("village", {})
    kittens0 = float(village.get("kittens", 0))
    max_kittens = float(village.get("maxKittens", 0))
    # Ankunftsrate nur, wenn der Snapshot sie liefert (siehe Modul-Docstring):
    arrival = float(village.get("kittensPerSec", 0.0) or 0.0)
    if max_kittens <= 0:
        arrival = 0.0   # ohne bekannte Kapazität keine Ankünfte (konservativ)

    stocks: dict[str, float] = {}
    rates: dict[str, float] = {}
    caps: dict[str, float] = {}
    for name in TRACKED:
        r = A.resource(snap, name)
        if r is None:
            continue
        stocks[name] = float(r.get("value", 0.0))
        rates[name] = float(r.get("perSec", 0.0))
        caps[name] = float(r.get("maxValue", 0.0))

    proj = Projection(
        horizon_s=horizon_s, invest=invest,
        times=[0.0], series=[dict(stocks)], kittens=[kittens0],
        year0=int(cal.get("year", 0)),
        day_into_year=season * dps + day,
        days_per_year=4 * dps,
        static_values={r["name"]: r.get("value", 0.0)
                       for r in snap.get("resources", [])},
    )

    # Segmentgrenzen: Rest der aktuellen Saison, dann volle Saisons.
    kittens = kittens0
    t = 0.0
    seg_season = season
    seg_end = min(horizon_s, max((dps - day) * SECONDS_PER_DAY, EPS))
    while t < horizon_s - EPS:
        mod = mods[seg_season % 4] if seg_season % 4 < len(mods) else 1.0
        k_start = kittens
        if arrival > 0 and kittens < max_kittens:
            # Ankunftsrate wächst mit der invest-Rampe (Ausbau = auch Housing):
            kittens = min(max_kittens,
                          kittens + arrival * (1.0 + invest * t / INVEST_TAU) * (seg_end - t))
        for name, stock in stocks.items():
            rate = rates[name]
            if name == "catnip":
                # Saisonrenormierung wie derived.project_catnip + Mehrlast
                # der bereits angekommenen Kitten (Stand Segmentanfang):
                rate = (rate - field_base * mod_now + field_base * mod
                        - (k_start - kittens0) * CATNIP_PER_KITTEN_PER_SEC)
            v = stock + _integral(rate, invest, t, seg_end)
            cap = caps[name]
            if cap > 0:
                v = min(v, cap)             # Cap-Klemme
            stocks[name] = max(0.0, v)
        t = seg_end
        proj.times.append(t)
        proj.series.append(dict(stocks))
        proj.kittens.append(kittens)
        seg_season += 1
        seg_end = min(horizon_s, t + dps * SECONDS_PER_DAY)
    return proj
