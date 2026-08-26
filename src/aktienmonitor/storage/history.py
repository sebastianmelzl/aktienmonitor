"""Verlauf der Scores.

Die Uebersicht zeigt einen Zustand. Interessant ist aber die Veraenderung: ein
Titel, dessen Score seit dem letzten Lauf um zehn Punkte gestiegen ist, verdient
einen Blick - auch wenn er in der Rangliste nicht ganz oben steht. Dafuer wird
bei jedem Aktualisieren ein Stand je Titel weggeschrieben.

Bewusst nur wenige Kennzahlen je Eintrag: Scores, Abdeckung, Kurs und die zwei
Groessen, deren Vorzeichenwechsel als Ereignis zaehlt. Die vollstaendigen
Kennzahlen liegen im Cache und muessen nicht doppelt gefuehrt werden.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .db import Database


@dataclass(frozen=True)
class HistoryEntry:
    """Ein Stand eines Titels zu einem Zeitpunkt."""

    ticker: str
    recorded_at: datetime
    total: float | None = None
    fundamental: float | None = None
    technical: float | None = None
    analyst: float | None = None
    sentiment: float | None = None
    coverage_fundamental: float | None = None
    price: float | None = None
    ma_cross: str | None = None
    revision_balance: float | None = None

    @property
    def age_days(self) -> float:
        return max(0.0, (datetime.now(UTC) - self.recorded_at).total_seconds() / 86_400.0)


def _as_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


class ScoreHistory:
    """Liest und schreibt die Verlaufstabelle."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def record(self, entry: HistoryEntry) -> None:
        """Schreibt einen Stand fort."""
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO score_history
                    (ticker, recorded_at, total, fundamental, technical, analyst,
                     sentiment, coverage_fundamental, price, ma_cross, revision_balance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.ticker.upper(),
                    entry.recorded_at.astimezone(UTC).isoformat(),
                    entry.total,
                    entry.fundamental,
                    entry.technical,
                    entry.analyst,
                    entry.sentiment,
                    entry.coverage_fundamental,
                    entry.price,
                    entry.ma_cross,
                    entry.revision_balance,
                ),
            )

    def record_many(self, entries: list[HistoryEntry]) -> int:
        for entry in entries:
            self.record(entry)
        return len(entries)

    def latest(self, ticker: str, *, before: datetime | None = None) -> HistoryEntry | None:
        """Juengster Eintrag eines Titels, optional vor einem Zeitpunkt."""
        query = (
            "SELECT * FROM score_history WHERE ticker = ?"
            + (" AND recorded_at < ?" if before is not None else "")
            + " ORDER BY recorded_at DESC LIMIT 1"
        )
        params: tuple = (ticker.upper(),)
        if before is not None:
            params = (ticker.upper(), before.astimezone(UTC).isoformat())
        with self.db.connect() as conn:
            row = conn.execute(query, params).fetchone()
        return _to_entry(row) if row is not None else None

    def previous(self, ticker: str, *, min_gap_hours: float = 6.0) -> HistoryEntry | None:
        """Der letzte Eintrag, der deutlich vor dem juengsten liegt.

        Ohne den Mindestabstand waere der "Vorstand" oft nur Minuten alt - etwa
        wenn zweimal hintereinander aktualisiert wurde. Dann gaebe es nie eine
        Veraenderung zu sehen.
        """
        juengster = self.latest(ticker)
        if juengster is None:
            return None
        grenze = juengster.recorded_at - timedelta(hours=min_gap_hours)
        return self.latest(ticker, before=grenze)

    def series(self, ticker: str, *, limit: int = 200) -> list[HistoryEntry]:
        """Verlauf eines Titels, aufsteigend nach Zeit."""
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM score_history WHERE ticker = ?"
                " ORDER BY recorded_at DESC LIMIT ?",
                (ticker.upper(), limit),
            ).fetchall()
        return [_to_entry(row) for row in reversed(rows)]

    def tickers(self) -> list[str]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT ticker FROM score_history ORDER BY ticker"
            ).fetchall()
        return [row["ticker"] for row in rows]

    def count(self) -> int:
        with self.db.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS n FROM score_history").fetchone()["n"])

    def purge_older_than(self, days: int) -> int:
        """Alte Eintraege entfernen. Der Verlauf soll nicht unbegrenzt wachsen."""
        grenze = (datetime.now(UTC) - timedelta(days=max(0, days))).isoformat()
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM score_history WHERE recorded_at < ?", (grenze,))
            return cursor.rowcount


def _to_entry(row) -> HistoryEntry:
    return HistoryEntry(
        ticker=row["ticker"],
        recorded_at=datetime.fromisoformat(row["recorded_at"]),
        total=_as_float(row["total"]),
        fundamental=_as_float(row["fundamental"]),
        technical=_as_float(row["technical"]),
        analyst=_as_float(row["analyst"]),
        sentiment=_as_float(row["sentiment"]),
        coverage_fundamental=_as_float(row["coverage_fundamental"]),
        price=_as_float(row["price"]),
        ma_cross=row["ma_cross"],
        revision_balance=_as_float(row["revision_balance"]),
    )


def entry_from(snapshot, scored, *, recorded_at: datetime | None = None) -> HistoryEntry:
    """Baut einen Verlaufseintrag aus Snapshot und Bewertung."""
    categories = scored.categories
    ma_cross = snapshot.technical.get("ma_cross")
    return HistoryEntry(
        ticker=snapshot.ticker,
        recorded_at=recorded_at or datetime.now(UTC),
        total=scored.total,
        fundamental=categories["fundamental"].score,
        technical=categories["technical"].score,
        analyst=categories["analyst"].score,
        sentiment=categories["sentiment"].score,
        coverage_fundamental=categories["fundamental"].weight_coverage * 100.0,
        price=snapshot.price,
        ma_cross=ma_cross.text if ma_cross is not None and ma_cross.is_available else None,
        revision_balance=snapshot.analyst.value_of("revision_balance"),
    )
