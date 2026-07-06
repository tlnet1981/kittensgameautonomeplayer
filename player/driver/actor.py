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

# Button per Titel finden, Glow setzen, Klickposition liefern.
FIND_BUTTON_JS = """
(args) => {
    const btns = Array.from(document.querySelectorAll('div.btn'));
    const el = btns.find(b => {
        const t = b.querySelector('.btnTitle');
        return t && t.textContent.trim().toLowerCase().startsWith(args.title.toLowerCase());
    });
    if (!el) return { error: "not_found" };
    if (el.classList.contains('disabled')) return { error: "disabled" };
    el.scrollIntoView({ block: 'center' });
    el.classList.add('kgp-glow');
    setTimeout(() => el.classList.remove('kgp-glow'), args.glowMs);
    const r = el.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
}
"""

# Spiel-Tab aktivieren (a.tab.<TabId>), Glow + Klickposition.
FIND_TAB_JS = """
(args) => {
    const el = document.querySelector('a.tab.' + args.tab);
    if (!el) return { error: "not_found" };
    if (el.classList.contains('activeTab')) return { already: true };
    el.classList.add('kgp-glow');
    setTimeout(() => el.classList.remove('kgp-glow'), args.glowMs);
    const r = el.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
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
            return {"ok": False, "method": "none", "detail": f"Unbekannter kind: {kind}"}
        except Exception as exc:
            return {"ok": False, "method": "error", "detail": str(exc)}

    # ------------------------------------------------------------ Grundbausteine

    async def _ensure_tab(self, tab: str) -> bool:
        res = await self.browser.evaluate(FIND_TAB_JS, {"tab": tab, "glowMs": self.glow_ms})
        if res.get("already"):
            return True
        if res.get("error"):
            return False
        await asyncio.sleep(0.25)   # Glow kurz sichtbar lassen
        await self.browser.page.mouse.click(res["x"], res["y"])
        await asyncio.sleep(0.35)   # Tab-Rendering abwarten
        return True

    async def _click_button(self, spec: dict) -> dict:
        tab = spec.get("tab", "Bonfire")
        title = spec["title"]
        batch = int(spec.get("batch", 1))
        if not await self._ensure_tab(tab):
            return {"ok": False, "method": "dom", "detail": f"Tab {tab} nicht verfügbar"}
        clicks = 0
        for i in range(batch):
            res = await self.browser.evaluate(FIND_BUTTON_JS, {"title": title, "glowMs": self.glow_ms})
            if res.get("error"):
                if clicks > 0:
                    break   # Teilcharge ok (z. B. Ressourcen aufgebraucht)
                return {"ok": False, "method": "dom",
                        "detail": f"Button „{title}“: {res['error']}"}
            if i == 0:
                await asyncio.sleep(0.25)  # ersten Glow zeigen
            await self.browser.page.mouse.click(res["x"], res["y"])
            clicks += 1
            if batch > 1:
                await asyncio.sleep(0.09)
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
        res = await self.browser.evaluate(FIND_BUTTON_JS,
                                          {"title": "Send hunters", "glowMs": self.glow_ms})
        if not res.get("error"):
            await asyncio.sleep(0.25)
            await self.browser.page.mouse.click(res["x"], res["y"])
            return {"ok": True, "method": "dom", "detail": "Send hunters geklickt"}
        await self.browser.evaluate("() => game.village.huntAll()")
        return {"ok": True, "method": "js-fallback", "detail": "huntAll()"}

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
