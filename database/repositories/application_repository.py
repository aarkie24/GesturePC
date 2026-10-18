"""SQLite repository for approved application executables."""

from __future__ import annotations

import datetime
import sqlite3
from typing import List, Optional

from domain.models import ApprovedApplication


class ApplicationRepository:
    """Manages the whitelist of approved desktop application executables."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, display_name: str, exe_path: str) -> ApprovedApplication:
        """Adds a new approved executable to the database."""
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT INTO approved_applications (display_name, exe_path, created_at)
            VALUES (?, ?, ?);
            """,
            (display_name.strip(), exe_path.strip(), now_utc),
        )
        app_id = cursor.lastrowid
        cursor.close()
        if app_id is None:
            raise RuntimeError("Failed to obtain lastrowid for approved application")

        return ApprovedApplication(
            id=app_id,
            display_name=display_name.strip(),
            exe_path=exe_path.strip(),
            created_at=now_utc,
        )

    def delete(self, app_id: int) -> bool:
        """Removes an approved executable by ID."""
        cursor = self._conn.cursor()
        cursor.execute("DELETE FROM approved_applications WHERE id = ?;", (app_id,))
        deleted = cursor.rowcount > 0
        cursor.close()
        return deleted

    def get_by_id(self, app_id: int) -> Optional[ApprovedApplication]:
        """Retrieves an application record by ID."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT id, display_name, exe_path, created_at FROM approved_applications WHERE id = ?;",
            (app_id,),
        )
        row = cursor.fetchone()
        cursor.close()
        if not row:
            return None
        return ApprovedApplication(
            id=row["id"],
            display_name=row["display_name"],
            exe_path=row["exe_path"],
            created_at=row["created_at"],
        )

    def get_by_name(self, display_name: str) -> Optional[ApprovedApplication]:
        """Retrieves an application record by display name (NOCASE)."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT id, display_name, exe_path, created_at FROM approved_applications WHERE display_name = ?;",
            (display_name.strip(),),
        )
        row = cursor.fetchone()
        cursor.close()
        if not row:
            return None
        return ApprovedApplication(
            id=row["id"],
            display_name=row["display_name"],
            exe_path=row["exe_path"],
            created_at=row["created_at"],
        )

    def list_all(self) -> List[ApprovedApplication]:
        """Lists all approved applications ordered alphabetically."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT id, display_name, exe_path, created_at FROM approved_applications ORDER BY display_name ASC;"
        )
        rows = cursor.fetchall()
        cursor.close()
        return [
            ApprovedApplication(
                id=r["id"],
                display_name=r["display_name"],
                exe_path=r["exe_path"],
                created_at=r["created_at"],
            )
            for r in rows
        ]
