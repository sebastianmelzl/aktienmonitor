"""Verwaltung des beobachteten Universums (Titel und Listen)."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from ..storage.db import Database

# Ticker koennen Punkte (SAP.DE), Bindestriche (BRK-B) und Ziffern (7203.T) enthalten.
TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._\-]{0,19}$")


def normalise_ticker(raw: str) -> str | None:
    """Vereinheitlicht eine Ticker-Eingabe; None, wenn sie unbrauchbar ist."""
    candidate = (raw or "").strip().upper().replace(" ", "")
    if not candidate or not TICKER_PATTERN.match(candidate):
        return None
    return candidate


@dataclass(frozen=True)
class WatchlistEntry:
    ticker: str
    display_name: str | None
    added_at: datetime
    note: str | None
    groups: tuple[str, ...] = ()


class Watchlist:
    def __init__(self, db: Database) -> None:
        self.db = db

    # --- Titel ---------------------------------------------------------------

    def add(self, ticker: str, *, display_name: str | None = None, note: str | None = None) -> str:
        """Nimmt einen Titel auf. Gibt den normalisierten Ticker zurueck."""
        normalised = normalise_ticker(ticker)
        if normalised is None:
            raise ValueError(f"Ungueltiger Ticker: {ticker!r}")
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO watchlist_item (ticker, display_name, added_at, note)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    display_name = COALESCE(excluded.display_name, watchlist_item.display_name),
                    note = COALESCE(excluded.note, watchlist_item.note)
                """,
                (normalised, display_name, datetime.now(UTC).isoformat(), note),
            )
        return normalised

    def remove(self, ticker: str) -> bool:
        normalised = normalise_ticker(ticker)
        if normalised is None:
            return False
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM watchlist_item WHERE ticker = ?", (normalised,))
            return cursor.rowcount > 0

    def all(self) -> list[WatchlistEntry]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT ticker, display_name, added_at, note FROM watchlist_item ORDER BY ticker"
            ).fetchall()
            memberships = conn.execute(
                """
                SELECT m.ticker, g.name FROM watchlist_membership m
                JOIN watchlist_group g ON g.id = m.group_id
                ORDER BY g.name
                """
            ).fetchall()
        by_ticker: dict[str, list[str]] = {}
        for row in memberships:
            by_ticker.setdefault(row["ticker"], []).append(row["name"])
        return [
            WatchlistEntry(
                ticker=row["ticker"],
                display_name=row["display_name"],
                added_at=datetime.fromisoformat(row["added_at"]),
                note=row["note"],
                groups=tuple(by_ticker.get(row["ticker"], ())),
            )
            for row in rows
        ]

    def tickers(self, group: str | None = None) -> list[str]:
        if group is None:
            return [entry.ticker for entry in self.all()]
        return [entry.ticker for entry in self.all() if group in entry.groups]

    # --- Listen / Gruppen ----------------------------------------------------

    def create_group(self, name: str) -> int:
        clean = (name or "").strip()
        if not clean:
            raise ValueError("Listenname darf nicht leer sein")
        with self.db.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO watchlist_group (name, created_at) VALUES (?, ?)",
                (clean, datetime.now(UTC).isoformat()),
            )
            row = conn.execute("SELECT id FROM watchlist_group WHERE name = ?", (clean,)).fetchone()
        return int(row["id"])

    def delete_group(self, name: str) -> bool:
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM watchlist_group WHERE name = ?", ((name or "").strip(),))
            return cursor.rowcount > 0

    def groups(self) -> list[str]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT name FROM watchlist_group ORDER BY name").fetchall()
        return [row["name"] for row in rows]

    def assign(self, ticker: str, group: str) -> None:
        normalised = normalise_ticker(ticker)
        if normalised is None:
            raise ValueError(f"Ungueltiger Ticker: {ticker!r}")
        group_id = self.create_group(group)
        with self.db.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO watchlist_membership (ticker, group_id) VALUES (?, ?)",
                (normalised, group_id),
            )

    def unassign(self, ticker: str, group: str) -> None:
        normalised = normalise_ticker(ticker)
        if normalised is None:
            return
        with self.db.connect() as conn:
            conn.execute(
                """
                DELETE FROM watchlist_membership
                WHERE ticker = ? AND group_id = (SELECT id FROM watchlist_group WHERE name = ?)
                """,
                (normalised, (group or "").strip()),
            )

    def set_groups(self, ticker: str, groups: list[str]) -> None:
        """Setzt die Listenzugehoerigkeit eines Titels auf genau ``groups``."""
        normalised = normalise_ticker(ticker)
        if normalised is None:
            raise ValueError(f"Ungueltiger Ticker: {ticker!r}")
        current = set(next((e.groups for e in self.all() if e.ticker == normalised), ()))
        wanted = {g.strip() for g in groups if g and g.strip()}
        for group in wanted - current:
            self.assign(normalised, group)
        for group in current - wanted:
            self.unassign(normalised, group)

    # --- CSV-Import ----------------------------------------------------------

    def import_csv(self, content: str) -> tuple[list[str], list[str]]:
        """Importiert Ticker aus CSV-Text.

        Erkannt werden die Spalten ``ticker`` (Pflicht), ``name`` und ``gruppe``/
        ``group``. Fehlt eine Kopfzeile, wird die erste Spalte als Ticker gelesen.
        Rueckgabe: (uebernommene Ticker, abgelehnte Eingaben).
        """
        accepted: list[str] = []
        rejected: list[str] = []
        text = content.lstrip("﻿")
        if not text.strip():
            return accepted, rejected

        sample = text[:2048]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
            dialect.delimiter = ";" if sample.count(";") > sample.count(",") else ","

        rows = list(csv.reader(io.StringIO(text), dialect))
        if not rows:
            return accepted, rejected

        header = [cell.strip().lower() for cell in rows[0]]
        has_header = "ticker" in header or "symbol" in header
        if has_header:
            idx_ticker = header.index("ticker") if "ticker" in header else header.index("symbol")
            idx_name = header.index("name") if "name" in header else None
            idx_group = next(
                (header.index(c) for c in ("gruppe", "group", "liste", "list") if c in header), None
            )
            data_rows = rows[1:]
        else:
            idx_ticker, idx_name, idx_group = 0, None, None
            data_rows = rows

        for row in data_rows:
            if not row or not any(cell.strip() for cell in row):
                continue
            raw = row[idx_ticker] if idx_ticker < len(row) else ""
            normalised = normalise_ticker(raw)
            if normalised is None:
                rejected.append(raw.strip() or "(leer)")
                continue
            name = row[idx_name].strip() if idx_name is not None and idx_name < len(row) else None
            self.add(normalised, display_name=name or None)
            if idx_group is not None and idx_group < len(row) and row[idx_group].strip():
                self.assign(normalised, row[idx_group].strip())
            accepted.append(normalised)
        return accepted, rejected
