"""Entscheidungstagebuch: eigene Kauf-/Verkaufsentscheidungen mit Begruendung.

Anders als der Score-Verlauf (``history.py``) schreibt sich hier nichts
automatisch fort - ein Eintrag entsteht ausschliesslich, wenn der Nutzer
selbst eine Entscheidung eintraegt. Die Begruendung ist die eigene
Einschaetzung zum Zeitpunkt der Entscheidung, nicht rueckblickend erzeugt
und nicht von einem Sprachmodell verfasst - ein Tagebuch, das sich selbst
im Nachhinein rechtfertigt, waere nutzlos.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from .db import Database

ACTION_BUY = "Kauf"
ACTION_SELL = "Verkauf"
ACTIONS = (ACTION_BUY, ACTION_SELL)


@dataclass(frozen=True)
class JournalEntry:
    """Eine eingetragene Entscheidung."""

    ticker: str
    action: str
    decided_at: date
    price: float | None = None
    amount: float | None = None
    shares: float | None = None
    score_at_decision: float | None = None
    rationale: str | None = None
    id: int | None = None
    created_at: datetime | None = None


def _as_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


class DecisionJournal:
    """Liest und schreibt das Entscheidungstagebuch."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, entry: JournalEntry) -> int:
        if entry.action not in ACTIONS:
            raise ValueError(f"Unbekannte Aktion: {entry.action!r} - erwartet {ACTIONS}")
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO decision_journal
                    (ticker, action, decided_at, price, amount, shares,
                     score_at_decision, rationale, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.ticker.upper(),
                    entry.action,
                    entry.decided_at.isoformat(),
                    entry.price,
                    entry.amount,
                    entry.shares,
                    entry.score_at_decision,
                    entry.rationale,
                    datetime.now(UTC).isoformat(),
                ),
            )
            return int(cursor.lastrowid)

    def all(self, *, ticker: str | None = None) -> list[JournalEntry]:
        """Alle Eintraege, juengste zuerst."""
        query = "SELECT * FROM decision_journal"
        params: tuple = ()
        if ticker:
            query += " WHERE ticker = ?"
            params = (ticker.upper(),)
        query += " ORDER BY decided_at DESC, id DESC"
        with self.db.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_to_entry(row) for row in rows]

    def delete(self, entry_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM decision_journal WHERE id = ?", (entry_id,))

    def tickers(self) -> list[str]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT ticker FROM decision_journal ORDER BY ticker"
            ).fetchall()
        return [row["ticker"] for row in rows]

    def count(self) -> int:
        with self.db.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS n FROM decision_journal").fetchone()["n"])


def _to_entry(row) -> JournalEntry:
    return JournalEntry(
        id=row["id"],
        ticker=row["ticker"],
        action=row["action"],
        decided_at=date.fromisoformat(row["decided_at"]),
        price=_as_float(row["price"]),
        amount=_as_float(row["amount"]),
        shares=_as_float(row["shares"]),
        score_at_decision=_as_float(row["score_at_decision"]),
        rationale=row["rationale"],
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
    )


__all__ = ["ACTION_BUY", "ACTION_SELL", "ACTIONS", "DecisionJournal", "JournalEntry"]
