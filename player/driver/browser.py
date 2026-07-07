"""Playwright-Lifecycle: startet das sichtbare Chromium-Spielfenster.

Das Spielfenster ist bewusst ein eigener, sichtbarer Browser — der Zuschauer
soll dem Agenten beim Klicken zusehen können (headed). Für Tests läuft
dasselbe headless.

Zwei wichtige Eigenschaften:
- **Persistentes Profil:** Kittens Game speichert den Spielstand in
  localStorage. Deshalb läuft der Browser mit `launch_persistent_context`
  auf einem festen Profilordner (config.profile_dir) — der Spielstand
  überlebt Neustarts von run.py. Profilordner löschen = neu anfangen.
- **Englische Spielsprache erzwungen:** Der Actor matcht englische
  Button-Titel. Auf nicht-englischen Systemen würde das Spiel sonst der
  Browser-Sprache folgen (i18n.js: localStorage-Schlüssel, sonst
  navigator.language). Doppelt abgesichert: locale="en-US" am Kontext und
  ein Init-Skript, das den localStorage-Schlüssel vor jedem Seitenstart
  auf "en" setzt (wirkt auch nach Reset-Reloads und übersteuert eine
  früher gespeicherte andere Sprache).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

# Import weich: Unit-Tests importieren den Brain-Loop (→ Actor → Browser)
# auch ohne installiertes Playwright; gestartet wird der Browser dort nie.
# Die Typnamen sind dank `from __future__ import annotations` nur Strings.
try:
    from playwright.async_api import BrowserContext, Page, Playwright, async_playwright
except ImportError:                     # pragma: no cover - Testumgebung
    async_playwright = None

# CSS für das Klick-Highlight (Glow), wird einmalig ins Spiel injiziert.
GLOW_CSS = """
.kgp-glow {
    outline: 3px solid #47d7ff !important;
    box-shadow: 0 0 18px 6px rgba(71, 215, 255, 0.85) !important;
    transition: box-shadow 0.15s ease-in-out;
    z-index: 9999;
}
"""


# Erzwingt Englisch, bevor irgendein Spiel-Skript läuft (i18n.js liest
# diesen Schlüssel zuerst; Fallback wäre navigator.language):
FORCE_ENGLISH_JS = """
try { localStorage["com.nuclearunicorn.kittengame.language"] = "en"; } catch (e) {}
"""


class GameBrowser:
    """Kapselt Playwright: Start, Spielseite laden, Evaluate, Stop."""

    def __init__(self, headless: bool, window_size: tuple[int, int],
                 chromium_path: str | None = None,
                 profile_dir: Path | None = None) -> None:
        self.headless = headless
        self.window_size = window_size
        self.chromium_path = chromium_path
        self.profile_dir = profile_dir
        self._pw: Playwright | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None

    async def start(self, game_url: str) -> None:
        if async_playwright is None:
            raise RuntimeError("Playwright ist nicht installiert (pip install playwright)")
        self._pw = await async_playwright().start()
        w, h = self.window_size
        args = [f"--window-size={w},{h}"]
        launch_kwargs: dict = {
            "headless": self.headless,
            "args": args,
            "viewport": {"width": w, "height": h},
            "locale": "en-US",   # navigator.language / Accept-Language
        }
        if self.chromium_path:
            launch_kwargs["executable_path"] = self.chromium_path
        if self.profile_dir is not None:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._context = await self._pw.chromium.launch_persistent_context(
            str(self.profile_dir) if self.profile_dir else "", **launch_kwargs)
        await self._context.add_init_script(FORCE_ENGLISH_JS)
        self.page = self._context.pages[0] if self._context.pages \
            else await self._context.new_page()
        await self.page.goto(game_url, wait_until="domcontentloaded", timeout=60_000)
        await self._wait_for_game()
        await self.page.add_style_tag(content=GLOW_CSS)
        await self._apply_game_options()

    async def _apply_game_options(self) -> None:
        """Spieloptionen für den autonomen Betrieb setzen.

        noConfirm: Kauf-Bestätigungsdialoge aus — der Agent ist der Spieler,
        seine Safety-Engine übernimmt den Schutz (sonst werden z. B.
        Housing-Käufe still mit 'player-denied' verweigert)."""
        assert self.page is not None
        await self.page.evaluate("() => { game.opts.noConfirm = true; }")

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

    async def reinitialize(self, timeout_s: float = 90.0) -> None:
        """Nach einem Seiten-Reload (Reset!) Spielzustand + Injections erneuern."""
        await self._wait_for_game(timeout_s=timeout_s)
        await self.page.add_style_tag(content=GLOW_CSS)
        await self._apply_game_options()

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
        # Letzten Spielstand sichern (best effort), dann Kontext schließen —
        # das persistiert localStorage (inkl. Save) im Profilordner.
        try:
            if self.page is not None:
                try:
                    await self.page.evaluate("() => game.save()")
                except Exception:
                    pass
            if self._context is not None:
                await self._context.close()
        finally:
            self._context = None
            self.page = None
            if self._pw is not None:
                await self._pw.stop()
                self._pw = None
