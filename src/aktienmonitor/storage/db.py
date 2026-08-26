"""SQLite-Anbindung mit nummerierten Migrationsschritten.

Bewusst ohne ORM: das Schema besteht aus wenigen Tabellen mit klarem Zuschnitt,
ein ORM waere hier zusaetzliche Abhaengigkeit ohne Gewinn.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Jede Migration ist ein Tupel (Version, SQL). Neue Schritte werden nur
# angehaengt, bestehende niemals veraendert.
MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS watchlist_item (
            ticker      TEXT PRIMARY KEY,
            display_name TEXT,
            added_at    TEXT NOT NULL,
            note        TEXT
        );

        CREATE TABLE IF NOT EXISTS watchlist_group (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS watchlist_membership (
            ticker      TEXT NOT NULL,
            group_id    INTEGER NOT NULL,
            PRIMARY KEY (ticker, group_id),
            FOREIGN KEY (ticker) REFERENCES watchlist_item(ticker) ON DELETE CASCADE,
            FOREIGN KEY (group_id) REFERENCES watchlist_group(id) ON DELETE CASCADE
        );

        -- Zwischenspeicher fuer Rohantworten der Datenquellen.
        CREATE TABLE IF NOT EXISTS cache_entry (
            cache_key   TEXT PRIMARY KEY,
            ticker      TEXT,
            data_kind   TEXT NOT NULL,
            source      TEXT NOT NULL,
            payload     TEXT NOT NULL,
            fetched_at  TEXT NOT NULL,
            expires_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cache_ticker_kind
            ON cache_entry (ticker, data_kind);
        CREATE INDEX IF NOT EXISTS idx_cache_expires
            ON cache_entry (expires_at);

        -- Protokoll aller API-Zugriffe: Quelle, Endpunkt, Cache-Treffer.
        CREATE TABLE IF NOT EXISTS api_call_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            source      TEXT NOT NULL,
            endpoint    TEXT NOT NULL,
            ticker      TEXT,
            cache_hit   INTEGER NOT NULL,
            status      TEXT NOT NULL,
            duration_ms INTEGER,
            error       TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_api_log_ts ON api_call_log (ts DESC);

        -- Ergebnis des Datenquellen-Checks: was kann der Key des Nutzers wirklich?
        CREATE TABLE IF NOT EXISTS source_capability (
            source      TEXT NOT NULL,
            endpoint    TEXT NOT NULL,
            status      TEXT NOT NULL,
            detail      TEXT,
            checked_at  TEXT NOT NULL,
            PRIMARY KEY (source, endpoint)
        );

        CREATE TABLE IF NOT EXISTS app_setting (
            key         TEXT PRIMARY KEY,
            value       TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
        """,
    ),
    (
        2,
        """
        -- Verlauf der Scores. Traegt bei jedem Aktualisieren einen Stand je
        -- Titel ein; daraus entsteht die Veraenderungserkennung.
        CREATE TABLE IF NOT EXISTS score_history (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker                TEXT NOT NULL,
            recorded_at           TEXT NOT NULL,
            total                 REAL,
            fundamental           REAL,
            technical             REAL,
            analyst               REAL,
            sentiment             REAL,
            coverage_fundamental  REAL,
            price                 REAL,
            ma_cross              TEXT,
            revision_balance      REAL
        );
        CREATE INDEX IF NOT EXISTS idx_history_ticker_time
            ON score_history (ticker, recorded_at DESC);
        """,
    ),
]

_init_lock = threading.Lock()
_initialised: set[str] = set()


class Database:
    """Duenne Huelle um sqlite3 mit automatischer Schema-Migration."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Oeffnet eine Verbindung; committet am Ende bzw. rollt bei Fehlern zurueck."""
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        key = str(self.path.resolve())
        with _init_lock:
            if key in _initialised:
                return
            with self.connect() as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS schema_version ("
                    " version INTEGER PRIMARY KEY,"
                    " applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
                )
                row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_version").fetchone()
                current = int(row["v"])
                for version, script in MIGRATIONS:
                    if version > current:
                        conn.executescript(script)
                        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
            _initialised.add(key)


def reset_schema_cache() -> None:
    """Nur fuer Tests: erzwingt erneute Migrationspruefung."""
    with _init_lock:
        _initialised.clear()
