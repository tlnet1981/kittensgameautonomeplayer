"""Zentrale Konfiguration des Kittens-Game-Players.

Alle Werte lassen sich per Umgebungsvariable oder CLI-Flag (siehe run.py)
überschreiben. Defaults sind auf den Normalbetrieb beim Nutzer ausgelegt:
Cockpit auf localhost:8000, Spiel online auf kittensgame.com, sichtbares
(headed) Chromium-Fenster.

Für Entwicklung/Tests ohne Internetzugang kann das Spiel aus einem lokalen
Clone serviert werden (LOCAL_GAME=1, Clone liegt unter ./gamefiles).
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


class Config:
    """Laufzeitkonfiguration (einfaches Attribut-Objekt, kein Framework)."""

    def __init__(self) -> None:
        # --- Cockpit-Server ---
        self.host: str = os.environ.get("KGP_HOST", "127.0.0.1")
        self.port: int = int(os.environ.get("KGP_PORT", "8000"))

        # --- Spielquelle ---
        # Default: offizielles Online-Spiel. Für Entwicklung/Tests:
        # LOCAL_GAME=1 -> das unter ./gamefiles geklonte Spiel wird vom
        # Cockpit-Server unter /game/ mitserviert und Playwright lädt es
        # von dort (identische window.game-API).
        self.local_game: bool = _env_bool("KGP_LOCAL_GAME", False)
        self.game_url: str = os.environ.get("KGP_GAME_URL", "https://kittensgame.com/web/")
        self.gamefiles_dir: Path = PROJECT_ROOT / "gamefiles"

        # --- Browser (Spielfenster) ---
        self.headless: bool = _env_bool("KGP_HEADLESS", False)
        self.game_window_size: tuple[int, int] = (1280, 900)
        # Optionaler Pfad zu einer Chromium-Binary; leer = Playwright-Default.
        # Nützlich, wenn Playwright-Version und installierte Browser abweichen.
        self.chromium_path: str | None = os.environ.get("KGP_CHROMIUM_PATH") or None
        # Persistentes Browser-Profil: hier lebt der SPIELSTAND (localStorage).
        # Ordner löschen = komplett neu anfangen.
        self.profile_dir: Path = Path(os.environ.get("KGP_PROFILE_DIR")
                                      or str(PROJECT_ROOT / "data" / "browser-profile"))

        # --- Agent-Timing ---
        # Telemetrie-Intervall: wie oft der komplette Spielzustand gelesen
        # und ans Cockpit gepusht wird (Sekunden).
        self.snapshot_interval: float = float(os.environ.get("KGP_SNAPSHOT_INTERVAL", "1.0"))
        # Entscheidungs-Intervall: Mindestabstand zwischen zwei Aktionen,
        # damit man als Zuschauer folgen kann (Sekunden).
        self.decision_interval: float = float(os.environ.get("KGP_DECISION_INTERVAL", "1.5"))
        # Dauer des Klick-Highlights im Spielfenster (Millisekunden).
        self.click_glow_ms: int = int(os.environ.get("KGP_CLICK_GLOW_MS", "450"))

        # --- Persistenz ---
        self.data_dir: Path = Path(os.environ.get("KGP_DATA_DIR", str(PROJECT_ROOT / "data")))
        # Save-Export-Intervall (Sekunden); 0 = deaktiviert.
        self.save_export_interval: float = float(os.environ.get("KGP_SAVE_EXPORT_INTERVAL", "300"))

        # --- Referenzversion (Spec: Version Guard, weich) ---
        self.reference_version: str = "1.5.0.2"
        self.reference_build_revision: int = 3

    @property
    def effective_game_url(self) -> str:
        """URL, die das Playwright-Spielfenster tatsächlich lädt."""
        if self.local_game:
            return f"http://{self.host}:{self.port}/game/index.html"
        return self.game_url


CONFIG = Config()
