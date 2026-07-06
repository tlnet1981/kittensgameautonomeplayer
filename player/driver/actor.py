"""Actor: führt Aktionen sichtbar im Spielfenster aus.

Prinzip (Cockpit-Erlebnis): erst der richtige Spiel-Tab, dann bekommt der
Ziel-Button einen Glow, dann ein echter Maus-Klick. So kann der Zuschauer
dem Agenten zusehen. Schlägt der DOM-Weg fehl, greift ein JS-API-Fallback —
das Ergebnis wird als method="js-fallback" markiert (Cockpit: „degraded").

Alle exec_spec-Kinds sind in brain/actions.py dokumentiert.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .browser import GameBrowser

# Button per Titel finden, Glow setzen und DIREKT im selben Aufruf klicken.
# Wichtig: Suche und Klick müssen atomar sein — das Spiel rendert seine
# Tabs laufend neu, Koordinaten aus einem früheren Aufruf wären veraltet
# (im Test verfehlten Maus-Klicks dadurch ihr Ziel).
# args.panel (optional) grenzt die Suche auf einen Panel-Container ein —
# wichtig bei Namenskollisionen (z. B. Policy „Diplomacy" vs. Metaphysics-
# Perk „Diplomacy" im selben Science-Tab!).
FIND_AND_CLICK_BUTTON_JS = """
(args) => {
    let root = document;
    if (args.panel) {
        const panels = Array.from(document.querySelectorAll('div.panelContainer'));
        root = panels.find(p => {
            const t = p.querySelector('div.title');
            return t && t.textContent.trim().toLowerCase().startsWith(args.panel.toLowerCase());
        });
        if (!root) return { error: "panel_not_found" };
    }
    const btns = Array.from(root.querySelectorAll('div.btn'));
    const el = btns.find(b => {
        const t = b.querySelector('.btnTitle');
        return t && t.textContent.trim().toLowerCase().startsWith(args.title.toLowerCase());
    });
    if (!el) return { error: "not_found" };
    if (el.classList.contains('disabled')) return { error: "disabled" };
    el.scrollIntoView({ block: 'center' });
    el.classList.add('kgp-glow');
    setTimeout(() => el.classList.remove('kgp-glow'), args.glowMs);
    if (args.click) { el.click(); }
    return { clicked: !!args.click };
}
"""

# Spiel-Tab aktivieren (a.tab.<TabId>), Glow + Klick atomar.
FIND_AND_CLICK_TAB_JS = """
(args) => {
    const el = document.querySelector('a.tab.' + args.tab);
    if (!el) return { error: "not_found" };
    if (el.classList.contains('activeTab')) return { already: true };
    el.classList.add('kgp-glow');
    setTimeout(() => el.classList.remove('kgp-glow'), args.glowMs);
    el.click();
    return { clicked: true };
}
"""

# Gebäude-Einheit an-/abschalten (Spec 16.4): direkt über bld.get(name).on,
# mit before/after-Verifikation. `on: true` aktiviert eine Einheit (on += 1),
# `on: false` deaktiviert eine (on -= 1). Grenzen werden geprüft.
TOGGLE_BUILDING_JS = """
(args) => {
    const g = window.gamePage || window.game;
    const bld = g && g.bld ? g.bld.get(args.name) : null;
    if (!bld) return { error: "not_found" };
    const before = bld.on;
    if (args.on) {
        if (before >= bld.val) return { error: "all_on" };
        bld.on = before + 1;
    } else {
        if (before <= 0) return { error: "all_off" };
        bld.on = before - 1;
    }
    return { before: before, after: bld.on, val: bld.val };
}
"""

# Leader setzen (Spec 12.3): über village.sim.kittens[index] + makeLeader
# (falls vorhanden — der censusPanel-DOM-Weg ist fragil), sonst manuell.
# before/after-Verifikation über die Leader-Identität.
SET_LEADER_JS = """
(args) => {
    const g = window.gamePage || window.game;
    const v = g ? g.village : null;
    const kitten = (v && v.sim && v.sim.kittens) ? v.sim.kittens[args.index] : null;
    if (!kitten) return { error: "kitten_not_found" };
    const label = (k) => k ? ((k.name || "") + " " + (k.surname || "")).trim() : null;
    const before = label(v.leader);
    if (typeof v.makeLeader === "function") {
        v.makeLeader(kitten);
    } else {
        if (v.leader) { v.leader.isLeader = false; }
        kitten.isLeader = true;
        v.leader = kitten;
    }
    return { ok: v.leader === kitten, before: before, after: label(v.leader) };
}
"""

SHIFT_JOB_JS = """
(args) => {
    const v = game.village;
    let removed = 0;
    for (const k of v.sim.kittens) {
        if (removed >= args.amount) break;
        if (k.job === args.from) { v.unassignJob(k); removed++; }
    }
    if (removed > 0) v.assignJob(v.getJob(args.to), removed);
    return removed;
}
"""


class Actor:
    def __init__(self, browser: GameBrowser, glow_ms: int = 450) -> None:
        self.browser = browser
        self.glow_ms = glow_ms

    async def execute(self, exec_spec: dict[str, Any]) -> dict[str, Any]:
        """Führt eine exec_spec aus. Ergebnis: {ok, method, detail}."""
        kind = exec_spec.get("kind")
        try:
            if kind == "wait":
                return {"ok": True, "method": "none", "detail": "WAIT"}
            if kind == "click_button":
                return await self._click_button(exec_spec)
            if kind == "assign_job":
                return await self._assign_job(exec_spec)
            if kind == "shift_job":
                return await self._shift_job(exec_spec)
            if kind == "hunt":
                return await self._hunt()
            if kind == "craft":
                return await self._craft(exec_spec)
            if kind == "trade":
                return await self._trade(exec_spec)
            if kind == "praise":
                return await self._praise()
            if kind == "adore":
                return await self._adore()
            if kind == "shatter":
                return await self._shatter(exec_spec)
            if kind == "toggle_building":
                return await self._toggle_building(exec_spec)
            if kind == "set_leader":
                return await self._set_leader(exec_spec)
            return {"ok": False, "method": "none", "detail": f"Unbekannter kind: {kind}"}
        except Exception as exc:
            return {"ok": False, "method": "error", "detail": str(exc)}

    # ------------------------------------------------------------ Grundbausteine

    async def _ensure_tab(self, tab: str) -> bool:
        res = await self.browser.evaluate(FIND_AND_CLICK_TAB_JS,
                                          {"tab": tab, "glowMs": self.glow_ms})
        if res.get("already"):
            return True
        if res.get("error"):
            return False
        await asyncio.sleep(0.35)   # Tab-Rendering abwarten (Glow läuft parallel)
        return True

    async def _click_button(self, spec: dict) -> dict:
        tab = spec.get("tab", "Bonfire")
        title = spec["title"]
        batch = int(spec.get("batch", 1))
        if not await self._ensure_tab(tab):
            return {"ok": False, "method": "dom", "detail": f"Tab {tab} nicht verfügbar"}
        clicks = 0
        for i in range(batch):
            res = await self.browser.evaluate(FIND_AND_CLICK_BUTTON_JS, {
                "title": title, "glowMs": self.glow_ms, "panel": spec.get("panel"),
                "click": True,
            })
            if res.get("error"):
                if clicks > 0:
                    break   # Teilcharge ok (z. B. Ressourcen aufgebraucht)
                return {"ok": False, "method": "dom",
                        "detail": f"Button „{title}“: {res['error']}"}
            clicks += 1
            # Glow/Reaktion sichtbar lassen; bei Chargen zügig weiter:
            await asyncio.sleep(0.12 if batch > 1 else 0.3)
        return {"ok": True, "method": "dom", "detail": f"{clicks}× geklickt"}

    # ------------------------------------------------------------ Spezialfälle

    async def _assign_job(self, spec: dict) -> dict:
        # Village-Tab sichtbar machen (Zuschauer sieht die Änderung), dann JS-API —
        # die Job-[+]-Links sind schwer stabil zu treffen, die API ist exakt.
        await self._ensure_tab("Village")
        ok = await self.browser.evaluate(
            """(args) => {
                const job = game.village.getJob(args.job);
                if (!job || !job.unlocked) return false;
                const before = job.value;
                game.village.assignJob(job, args.amount);
                return game.village.getJob(args.job).value > before;
            }""",
            {"job": spec["job"], "amount": int(spec.get("amount", 1))},
        )
        return {"ok": bool(ok), "method": "js",
                "detail": f"assignJob({spec['job']}, {spec.get('amount', 1)})"}

    async def _shift_job(self, spec: dict) -> dict:
        await self._ensure_tab("Village")
        moved = await self.browser.evaluate(SHIFT_JOB_JS, {
            "from": spec["from"], "to": spec["to"], "amount": int(spec.get("amount", 1)),
        })
        return {"ok": moved > 0, "method": "js",
                "detail": f"{moved} Kitten {spec['from']} → {spec['to']}"}

    async def _hunt(self) -> dict:
        await self._ensure_tab("Village")
        # Sichtbarer Versuch über den Button, sonst API:
        res = await self.browser.evaluate(FIND_AND_CLICK_BUTTON_JS,
                                          {"title": "Send hunters", "glowMs": self.glow_ms,
                                           "click": True})
        if not res.get("error"):
            await asyncio.sleep(0.25)
            return {"ok": True, "method": "dom", "detail": "Send hunters geklickt"}
        await self.browser.evaluate("() => game.village.huntAll()")
        return {"ok": True, "method": "js-fallback", "detail": "huntAll()"}

    async def _trade(self, spec: dict) -> dict:
        # Trade-Tab sichtbar machen; Ausführung über die exakte API
        # (Batch-Klicks im DOM wären fehleranfällig und langsam).
        await self._ensure_tab("Trade")
        ok = await self.browser.evaluate(
            """(args) => {
                const race = game.diplomacy.get(args.race);
                if (!race || !race.unlocked) return false;
                game.diplomacy.tradeMultiple(race, args.times);
                return true;
            }""",
            {"race": spec["race"], "times": int(spec.get("times", 1))},
        )
        return {"ok": bool(ok), "method": "js",
                "detail": f"tradeMultiple({spec['race']}, {spec.get('times', 1)})"}

    async def _praise(self) -> dict:
        await self._ensure_tab("Religion")
        res = await self.browser.evaluate(FIND_AND_CLICK_BUTTON_JS,
                                          {"title": "Praise the sun", "glowMs": self.glow_ms,
                                           "click": True})
        if not res.get("error"):
            await asyncio.sleep(0.25)
            return {"ok": True, "method": "dom", "detail": "Praise the sun geklickt"}
        await self.browser.evaluate("() => game.religion.praise()")
        return {"ok": True, "method": "js-fallback", "detail": "religion.praise()"}

    async def _adore(self) -> dict:
        """Adore the Galaxy — Worship → Epiphany (religion.resetFaith)."""
        await self._ensure_tab("Religion")
        res = await self.browser.evaluate(FIND_AND_CLICK_BUTTON_JS,
                                          {"title": "Adore the galaxy",
                                           "glowMs": self.glow_ms, "click": True})
        if not res.get("error"):
            await asyncio.sleep(0.25)
            return {"ok": True, "method": "dom", "detail": "Adore geklickt"}
        ok = await self.browser.evaluate(
            "() => { if (!game.religion.getRU('apocripha').on) return false;"
            " game.religion.resetFaith(1.01, false); return true; }")
        return {"ok": bool(ok), "method": "js-fallback", "detail": "resetFaith(1.01)"}

    async def _shatter(self, spec: dict) -> dict:
        """TC-Shatter über die exakte API (Batchgröße ist sicherheitsgeprüft)."""
        await self._ensure_tab("Time")
        done = await self.browser.evaluate(
            """(args) => {
                const before = game.calendar.year;
                game.time.shatter(args.batch);
                return game.calendar.year - before;
            }""",
            {"batch": int(spec.get("batch", 1))},
        )
        return {"ok": done > 0, "method": "js", "detail": f"+{done} Jahre geshattert"}

    async def _toggle_building(self, spec: dict) -> dict:
        """Eine Gebäude-Einheit an-/abschalten (Energie-Drosselung 16.4).
        Bonfire-Tab sichtbar machen (Zuschauer sieht die Änderung), dann die
        exakte API — die kleinen (+/−)-Links sind schwer stabil zu treffen."""
        await self._ensure_tab("Bonfire")
        res = await self.browser.evaluate(TOGGLE_BUILDING_JS, {
            "name": spec["name"], "on": bool(spec.get("on")),
        })
        if res.get("error"):
            return {"ok": False, "method": "js",
                    "detail": f"toggle {spec['name']}: {res['error']}"}
        ok = res.get("after") != res.get("before")   # before/after-Verifikation
        return {"ok": ok, "method": "js",
                "detail": (f"{spec['name']}.on: {res.get('before')} → "
                           f"{res.get('after')} (von {res.get('val')})")}

    async def _set_leader(self, spec: dict) -> dict:
        """Leader setzen (Spec 12.3) über village.makeLeader — der Weg über
        game.villageTab.censusPanel wäre DOM-fragil."""
        await self._ensure_tab("Village")
        res = await self.browser.evaluate(SET_LEADER_JS, {"index": int(spec["index"])})
        if res.get("error"):
            return {"ok": False, "method": "js",
                    "detail": f"set_leader: {res['error']}"}
        return {"ok": bool(res.get("ok")), "method": "js",
                "detail": f"Leader: {res.get('before')} → {res.get('after')}"}

    async def _craft(self, spec: dict) -> dict:
        # Workshop-Tab zeigen (falls sichtbar), Craft über die exakte API —
        # sie respektiert Craft Ratio und Ressourcenprüfung.
        await self._ensure_tab("Workshop")
        crafted = await self.browser.evaluate(
            """(args) => {
                const before = game.resPool.get(args.name).value;
                game.workshop.craft(args.name, args.times);
                return game.resPool.get(args.name).value - before;
            }""",
            {"name": spec["name"], "times": int(spec.get("times", 1))},
        )
        return {"ok": crafted > 0, "method": "js",
                "detail": f"craft({spec['name']}) → +{crafted:.2f}"}
