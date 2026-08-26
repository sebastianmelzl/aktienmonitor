"""Persistente Einstellungen (Gewichtungen, TTLs, aktive Quellen)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from ..storage.db import Database


class SettingsStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str, default: object = None) -> object:
        with self.db.connect() as conn:
            row = conn.execute("SELECT value FROM app_setting WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def set(self, key: str, value: object) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO app_setting (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, json.dumps(value), datetime.now(UTC).isoformat()),
            )

    def delete(self, key: str) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM app_setting WHERE key = ?", (key,))

    def all(self) -> dict[str, object]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT key, value FROM app_setting").fetchall()
        result: dict[str, object] = {}
        for row in rows:
            try:
                result[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                continue
        return result
