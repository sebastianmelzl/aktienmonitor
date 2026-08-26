"""Lokaler Cache in SQLite mit datentyp-abhaengiger Lebensdauer (TTL).

Der Cache ist die wichtigste Verteidigung gegen die Rate-Limits der Anbieter.
Jeder Eintrag traegt seinen Abrufzeitpunkt, damit die Oberflaeche jederzeit
anzeigen kann, wie alt eine Zahl ist und woher sie stammt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..storage.db import Database

_ISO = "%Y-%m-%dT%H:%M:%S.%f%z"


def _now() -> datetime:
    return datetime.now(UTC)


def _to_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(_ISO)


def _from_iso(raw: str) -> datetime:
    return datetime.strptime(raw, _ISO)


def build_key(source: str, endpoint: str, ticker: str | None, *parts: str) -> str:
    """Baut einen stabilen Cache-Schluessel."""
    segments = [source, endpoint, (ticker or "-").upper(), *[str(p) for p in parts]]
    return "|".join(segments)


@dataclass(frozen=True)
class CacheEntry:
    """Ein Treffer im Cache samt Altersangabe."""

    payload: object
    source: str
    fetched_at: datetime
    expires_at: datetime

    @property
    def age_seconds(self) -> float:
        return max(0.0, (_now() - self.fetched_at).total_seconds())

    @property
    def is_expired(self) -> bool:
        return _now() >= self.expires_at


class Cache:
    """TTL-Cache auf Basis der ``cache_entry``-Tabelle."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, cache_key: str, *, allow_stale: bool = False) -> CacheEntry | None:
        """Liefert einen Eintrag oder None.

        ``allow_stale=True`` gibt auch abgelaufene Eintraege zurueck - gedacht als
        Rueckfallebene, wenn ein Live-Abruf scheitert. Der Aufrufer erkennt den
        Zustand an ``is_expired`` und muss ihn in der Oberflaeche kenntlich machen.
        """
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT payload, source, fetched_at, expires_at FROM cache_entry WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        entry = CacheEntry(
            payload=json.loads(row["payload"]),
            source=row["source"],
            fetched_at=_from_iso(row["fetched_at"]),
            expires_at=_from_iso(row["expires_at"]),
        )
        if entry.is_expired and not allow_stale:
            return None
        return entry

    def set(
        self,
        cache_key: str,
        payload: object,
        *,
        source: str,
        data_kind: str,
        ttl_seconds: int,
        ticker: str | None = None,
    ) -> CacheEntry:
        """Legt einen Eintrag ab und gibt ihn zurueck."""
        fetched_at = _now()
        expires_at = fetched_at + timedelta(seconds=max(0, ttl_seconds))
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO cache_entry
                    (cache_key, ticker, data_kind, source, payload, fetched_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    payload = excluded.payload,
                    source = excluded.source,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at
                """,
                (
                    cache_key,
                    (ticker or None) and ticker.upper(),
                    data_kind,
                    source,
                    json.dumps(payload, default=str),
                    _to_iso(fetched_at),
                    _to_iso(expires_at),
                ),
            )
        return CacheEntry(
            payload=payload, source=source, fetched_at=fetched_at, expires_at=expires_at
        )

    def invalidate_ticker(self, ticker: str) -> int:
        """Verwirft alle Eintraege eines Titels (fuer "Jetzt aktualisieren")."""
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM cache_entry WHERE ticker = ?", (ticker.upper(),))
            return cursor.rowcount

    def purge_expired(self) -> int:
        with self.db.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM cache_entry WHERE expires_at < ?", (_to_iso(_now()),)
            )
            return cursor.rowcount

    def clear(self) -> int:
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM cache_entry")
            return cursor.rowcount

    def stats(self) -> list[dict[str, object]]:
        """Anzahl Eintraege und aeltester Abruf je Datenart - fuer die Einstellungen."""
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT data_kind, source, COUNT(*) AS n, MIN(fetched_at) AS oldest
                FROM cache_entry GROUP BY data_kind, source ORDER BY data_kind, source
                """
            ).fetchall()
        return [dict(row) for row in rows]
