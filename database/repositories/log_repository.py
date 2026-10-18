"""SQLite repository for audit and execution event logs."""

from __future__ import annotations

import datetime
import json
import sqlite3
from typing import Any, Dict, List, Optional, Sequence


class LogRepository:
    """Provides structured insertion, querying, and retention pruning for event logs."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(
        self,
        event_type: str,
        status: str,
        correlation_id: Optional[str] = None,
        gesture_id: Optional[int] = None,
        gesture_name: Optional[str] = None,
        workflow_id: Optional[int] = None,
        workflow_name: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        timestamp_utc: Optional[str] = None,
    ) -> int:
        """Inserts a single event log record."""
        if timestamp_utc is None:
            timestamp_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()

        details_json = None
        if details is not None:
            details_json = json.dumps(details)
            if len(details_json) > 2048:
                details_json = details_json[:2045] + "..."

        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT INTO event_logs (
                timestamp_utc, event_type, status, correlation_id,
                gesture_id, gesture_name, workflow_id, workflow_name, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                timestamp_utc,
                event_type,
                status,
                correlation_id,
                gesture_id,
                gesture_name,
                workflow_id,
                workflow_name,
                details_json,
            ),
        )
        row_id = cursor.lastrowid or 0
        cursor.close()
        return row_id

    def insert_batch(self, records: Sequence[Dict[str, Any]]) -> None:
        """Inserts a batch of log records inside a single transaction."""
        if not records:
            return

        cursor = self._conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE;")
            for r in records:
                ts = r.get("timestamp_utc") or datetime.datetime.now(datetime.timezone.utc).isoformat()
                det = r.get("details")
                det_json = None
                if det is not None:
                    det_json = json.dumps(det) if isinstance(det, dict) else str(det)
                    if len(det_json) > 2048:
                        det_json = det_json[:2045] + "..."

                cursor.execute(
                    """
                    INSERT INTO event_logs (
                        timestamp_utc, event_type, status, correlation_id,
                        gesture_id, gesture_name, workflow_id, workflow_name, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        ts,
                        r.get("event_type", ""),
                        r.get("status", ""),
                        r.get("correlation_id"),
                        r.get("gesture_id"),
                        r.get("gesture_name"),
                        r.get("workflow_id"),
                        r.get("workflow_name"),
                        det_json,
                    ),
                )
            cursor.execute("COMMIT;")
        except Exception:
            cursor.execute("ROLLBACK;")
            cursor.close()
            raise
        cursor.close()

    def prune(self, max_rows: int = 10000, max_days: int = 30) -> int:
        """Prunes log entries exceeding row retention ceiling or older than max_days."""
        cursor = self._conn.cursor()
        total_deleted = 0

        # 1. Prune by age
        cutoff_date = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=max_days)
        ).isoformat()
        cursor.execute("DELETE FROM event_logs WHERE timestamp_utc < ?;", (cutoff_date,))
        total_deleted += cursor.rowcount

        # 2. Prune by row count limit
        cursor.execute("SELECT COUNT(*) FROM event_logs;")
        count_row = cursor.fetchone()
        current_count = count_row[0] if count_row else 0

        if current_count > max_rows:
            excess = current_count - max_rows
            cursor.execute(
                """
                DELETE FROM event_logs WHERE id IN (
                    SELECT id FROM event_logs ORDER BY timestamp_utc ASC LIMIT ?
                );
                """,
                (excess,),
            )
            total_deleted += cursor.rowcount

        cursor.close()
        return total_deleted

    def query(
        self,
        limit: int = 100,
        offset: int = 0,
        event_type: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Queries log records ordered by timestamp descending."""
        cursor = self._conn.cursor()
        conditions = []
        params: List[Any] = []

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if correlation_id:
            conditions.append("correlation_id = ?")
            params.append(correlation_id)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query_sql = f"""
            SELECT id, timestamp_utc, event_type, status, correlation_id,
                   gesture_id, gesture_name, workflow_id, workflow_name, details_json
            FROM event_logs
            {where_clause}
            ORDER BY timestamp_utc DESC, id DESC
            LIMIT ? OFFSET ?;
        """
        params.extend([limit, offset])

        cursor.execute(query_sql, tuple(params))
        rows = cursor.fetchall()
        cursor.close()

        result: List[Dict[str, Any]] = []
        for r in rows:
            det = None
            if r["details_json"]:
                try:
                    det = json.loads(r["details_json"])
                except json.JSONDecodeError:
                    det = r["details_json"]

            result.append(
                {
                    "id": r["id"],
                    "timestamp_utc": r["timestamp_utc"],
                    "event_type": r["event_type"],
                    "status": r["status"],
                    "correlation_id": r["correlation_id"],
                    "gesture_id": r["gesture_id"],
                    "gesture_name": r["gesture_name"],
                    "workflow_id": r["workflow_id"],
                    "workflow_name": r["workflow_name"],
                    "details": det,
                }
            )

        return result
