"""Zentrale Konfiguration.

Alle Werte stammen aus der .env-Datei bzw. aus Umgebungsvariablen. API-Keys
werden ausschliesslich hier eingelesen und niemals geloggt oder persistiert.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _project_root() -> Path:
    """Ermittelt das Projektverzeichnis robust.

    Bei einer Installation aus dem Quellbaum liegt es zwei Ebenen ueber diesem
    Modul. Wird das Paket dagegen nach site-packages installiert (etwa in einem
    Container), zeigt derselbe Pfad ins Python-Verzeichnis - dann ist das
    Arbeitsverzeichnis die richtige Wahl. ``AKTIENMONITOR_ROOT`` sticht beides.
    """
    override = (os.getenv("AKTIENMONITOR_ROOT") or "").strip()
    if override:
        return Path(override)
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "pyproject.toml").exists():
        return candidate
    return Path.cwd()


PROJECT_ROOT = _project_root()

# Datentypen, fuer die getrennte Cache-Lebensdauern gelten.
DATA_KIND_QUOTE = "quote"
DATA_KIND_PRICE_HISTORY = "price_history"
DATA_KIND_FUNDAMENTALS = "fundamentals"
DATA_KIND_PROFILE = "profile"
DATA_KIND_ANALYST = "analyst"
DATA_KIND_NEWS = "news"
DATA_KIND_SENTIMENT = "sentiment"

DATA_KINDS = (
    DATA_KIND_QUOTE,
    DATA_KIND_PRICE_HISTORY,
    DATA_KIND_FUNDAMENTALS,
    DATA_KIND_PROFILE,
    DATA_KIND_ANALYST,
    DATA_KIND_NEWS,
)

DEFAULT_TTL_SECONDS: dict[str, int] = {
    DATA_KIND_QUOTE: 300,
    DATA_KIND_PRICE_HISTORY: 21_600,
    DATA_KIND_FUNDAMENTALS: 604_800,
    DATA_KIND_PROFILE: 2_592_000,
    DATA_KIND_ANALYST: 86_400,
    DATA_KIND_NEWS: 3_600,
}

_TTL_ENV_VARS: dict[str, str] = {
    DATA_KIND_QUOTE: "CACHE_TTL_QUOTE",
    DATA_KIND_PRICE_HISTORY: "CACHE_TTL_PRICE_HISTORY",
    DATA_KIND_FUNDAMENTALS: "CACHE_TTL_FUNDAMENTALS",
    DATA_KIND_PROFILE: "CACHE_TTL_PROFILE",
    DATA_KIND_ANALYST: "CACHE_TTL_ANALYST",
    DATA_KIND_NEWS: "CACHE_TTL_NEWS",
}


def _env_int(name: str, default: int) -> int:
    """Liest eine Ganzzahl aus der Umgebung; faellt bei Unsinn auf den Default zurueck."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    # Inline-Kommentare in der .env abschneiden ("300  # 5 Minuten").
    raw = raw.split("#", 1)[0].strip()
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


@dataclass(frozen=True)
class Config:
    """Laufzeitkonfiguration der Anwendung."""

    finnhub_api_key: str | None
    anthropic_api_key: str | None
    anthropic_model: str
    db_path: Path
    log_level: str
    ttl_seconds: dict[str, int] = field(default_factory=dict)
    rate_limit_per_min: dict[str, int] = field(default_factory=dict)
    retry_max_attempts: int = 4

    @property
    def has_finnhub(self) -> bool:
        return bool(self.finnhub_api_key)

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)


def load_config(env_file: Path | None = None) -> Config:
    """Laedt die Konfiguration aus .env und Umgebungsvariablen."""
    load_dotenv(dotenv_path=env_file or (PROJECT_ROOT / ".env"), override=False)

    db_raw = os.getenv("AKTIENMONITOR_DB_PATH", "data/aktienmonitor.db").strip()
    db_path = Path(db_raw)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path

    def _key(name: str) -> str | None:
        value = (os.getenv(name) or "").strip()
        return value or None

    return Config(
        finnhub_api_key=_key("FINNHUB_API_KEY"),
        anthropic_api_key=_key("ANTHROPIC_API_KEY"),
        anthropic_model=(os.getenv("ANTHROPIC_MODEL") or "claude-opus-5").strip(),
        db_path=db_path,
        log_level=(os.getenv("AKTIENMONITOR_LOG_LEVEL") or "INFO").strip().upper(),
        ttl_seconds={
            kind: _env_int(_TTL_ENV_VARS[kind], DEFAULT_TTL_SECONDS[kind]) for kind in DATA_KINDS
        },
        rate_limit_per_min={
            "finnhub": _env_int("RATE_LIMIT_FINNHUB_PER_MIN", 50),
            "yfinance": _env_int("RATE_LIMIT_YFINANCE_PER_MIN", 60),
        },
        retry_max_attempts=_env_int("RETRY_MAX_ATTEMPTS", 4),
    )
