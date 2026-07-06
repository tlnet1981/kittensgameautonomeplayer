"""Playwright-Lifecycle: startet das sichtbare Chromium-Spielfenster.

Das Spielfenster ist bewusst ein eigener, sichtbarer Browser — der Zuschauer
soll dem Agenten beim Klicken zusehen können (headed). Für Tests läuft
dasselbe headless.
"""

from __future__ import annotations

import asyncio
from typing import Any

from playwright.async_api import Browser, Page, Playwright, async_playwright

# CSS für das Klick-Highlight (Glow), wird einmalig ins Spiel injiziert.
GLOW_CSS = """
.kgp-glow {
    outline: 3px solid #47d7ff !important;
    box-shadow: 0 0 18px 6px rgba(71, 215, 255, 0.85) !important;
    transition: box-shadow 0.15s ease-in-out;
    z-index: 9999;
}
"""


class GameBrowser:
    """Kapselt Playwright: Start, Spielseite laden, Evaluate, Stop."""

    def __init__(self, headless: bool, window_size: tuple[int, int],
                 chromium_path: str | None = None) -> None:
        self.headless = headless
        self.window_size = window_size
        self.chromium_path = chromium_path
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self.page: Page | None = None

    async def start(self, game_url: str) -> None:
        self._pw = await async_playwright().start()
        w, h = self.window_size
        args = [f"--window-size={w},{h}"]
        launch_kwargs: dict = {"headless": self.headless, "args": args}
        if self.chromium_path:
            launch_kwargs["executable_path"] = self.chromium_path
        self._browser = await self._pw.chromium.launch(**launch_kwargs)
        context = await self._browser.new_context(viewport={"width": w, "height": h})
        self.page = await context.new_page()
        await self.page.goto(game_url, wait_until="domcontentloaded", timeout=60_000)
        await self._wait_for_game()
        await self.page.add_style_tag(content=GLOW_CSS)

    async def _wait_for_game(self, timeout_s: float = 60.0) -> None:
        """Wartet, bis window.game vollständig initialisiert ist."""
        assert self.page is not None
        deadline = asyncio.get_event_loop().time() + timeout_s
        while True:
            ready = await self.page.evaluate(
                "() => !!(window.game && window.game.bld && window.game.calendar"
                " && window.game.resPool && window.game.village)"
            )
            if ready:
                return
            if asyncio.get_event_loop().time() > deadline:
                raise TimeoutError("Kittens Game wurde nicht initialisiert (window.game fehlt)")
            await asyncio.sleep(0.5)

    async def evaluate(self, js: str, arg: Any = None) -> Any:
        assert self.page is not None, "Browser nicht gestartet"
        if arg is None:
            return await self.page.evaluate(js)
        return await self.page.evaluate(js, arg)

    async def export_save(self) -> str | None:
        """Liefert den LZString-Save-Export des Spiels (für Backups)."""
        try:
            return await self.evaluate(
                "() => { game.save(); return localStorage['com.nuclearunicorn.kittengame.savedata'] || null; }"
            )
        except Exception:
            return None

    async def stop(self) -> None:
        try:
            if self._browser is not None:
                await self._browser.close()
        finally:
            self._browser = None
            self.page = None
            if self._pw is not None:
                await self._pw.stop()
                self._pw = None
