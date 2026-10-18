"""SQLite repository for key-value configuration settings."""

from __future__ import annotations

import datetime
import json
import sqlite3
from typing import Any, Dict, Optional


class SettingsRepository:
    """Provides key-value persistence for configuration settings."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_all(self) -> Dict[str, Any]:
        """Loads all stored settings into a dictionary."""
        cursor = self._conn.cursor()
        cursor.execute("SELECT key, value_json FROM settings;")
        rows = cursor.fetchall()
        cursor.close()

        result: Dict[str, Any] = {}
        for r in rows:
            try:
                result[r["key"]] = json.loads(r["value_json"])
            except json.JSONDecodeError:
                continue
        return result

    def get(self, key: str) -> Optional[Any]:
        """Retrieves a single setting value by key, or None if absent."""
        cursor = self._conn.cursor()
        cursor.execute("SELECT value_json FROM settings WHERE key = ?;", (key,))
        row = cursor.fetchone()
        cursor.close()
        if not row:
            return None
        try:
            return json.loads(row["value_json"])
        except json.JSONDecodeError:
            return None

    def set(self, key: str, value: Any) -> None:
        """Saves or updates a setting key-value pair."""
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        val_json = json.dumps(value)
        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT INTO settings (key, value_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at = excluded.updated_at;
            """,
            (key, val_json, now_utc),
        )
        cursor.close()

    def set_many(self, settings_dict: Dict[str, Any]) -> None:
        """Saves multiple settings atomically."""
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cursor = self._conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE;")
            for k, v in settings_dict.items():
                cursor.execute(
                    """
                    INSERT INTO settings (key, value_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value_json = excluded.value_json,
                        updated_at = excluded.updated_at;
                    """,
                    (k, json.dumps(v), now_utc),
                )
            cursor.execute("COMMIT;")
        except Exception:
            cursor.execute("ROLLBACK;")
            cursor.close()
            raise
        cursor.close()
