"""Protokoll aller Datenquellen-Zugriffe.

Jeder Zugriff wird mit Quelle, Endpunkt, Cache-Treffer und Dauer festgehalten -
sowohl im Python-Logging als auch in der Datenbank, damit die Oberflaeche das
Verhalten gegenueber den Rate-Limits sichtbar machen kann.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ..storage.db import Database

logger = logging.getLogger("aktienmonitor.api")

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_RATE_LIMITED = "rate_limited"
STATUS_FORBIDDEN = "forbidden"
STATUS_NOT_FOUND = "not_found"


class CallLog:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(
        self,
        *,
        source: str,
        endpoint: str,
        ticker: str | None,
        cache_hit: bool,
        status: str,
        duration_ms: int | None = None,
        error: str | None = None,
    ) -> None:
        marker = "CACHE-HIT " if cache_hit else "CACHE-MISS"
        logger.info(
            "%s %-9s %-24s %-10s %s%s",
            marker,
            source,
            endpoint,
            ticker or "-",
            status,
            f" ({duration_ms} ms)" if duration_ms is not None else "",
        )
        if error:
            logger.warning("%s %s %s: %s", source, endpoint, ticker or "-", error)
        try:
            with self.db.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO api_call_log
                        (ts, source, endpoint, ticker, cache_hit, status, duration_ms, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        datetime.now(UTC).isoformat(),
                        source,
                        endpoint,
                        ticker.upper() if ticker else None,
                        1 if cache_hit else 0,
                        status,
                        duration_ms,
                        error,
                    ),
                )
        except Exception:  # noqa: BLE001 - Logging darf den Abruf nie zum Scheitern bringen
            logger.exception("Konnte API-Aufruf nicht protokollieren")

    def recent(self, limit: int = 200) -> list[dict[str, object]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT ts, source, endpoint, ticker, cache_hit, status, duration_ms, error"
                " FROM api_call_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def summary(self) -> dict[str, int]:
        """Cache-Trefferquote und Fehlerzahl der letzten 24 Stunden."""
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COALESCE(SUM(cache_hit), 0) AS hits,
                    COALESCE(SUM(CASE WHEN status <> 'ok' THEN 1 ELSE 0 END), 0) AS errors
                FROM api_call_log
                WHERE ts >= datetime('now', '-1 day')
                """
            ).fetchone()
        return {"total": int(row["total"]), "cache_hits": int(row["hits"]), "errors": int(row["errors"])}
