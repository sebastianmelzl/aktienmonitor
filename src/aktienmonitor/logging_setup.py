"""Logging-Konfiguration: Konsole plus rotierende Datei unter logs/."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import PROJECT_ROOT

_configured = False

_FORMAT = "%(asctime)s %(levelname)-7s %(name)-26s %(message)s"


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    """Richtet das Logging einmalig ein (mehrfache Aufrufe sind unschaedlich)."""
    global _configured
    if _configured:
        return

    target_dir = log_dir or (PROJECT_ROOT / "logs")
    target_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("aktienmonitor")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.propagate = False

    formatter = logging.Formatter(_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        target_dir / "aktienmonitor.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # yfinance ist im Normalbetrieb sehr gespraechig.
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    logging.getLogger("peewee").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    _configured = True
