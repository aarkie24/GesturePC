"""SQLite repository for workflows and ordered workflow actions."""

from __future__ import annotations

import datetime
import sqlite3
from typing import List, Optional, Sequence, Tuple

from domain.exceptions import InvalidWorkflow
from domain.models import Workflow, WorkflowAction


class WorkflowRepository:
    """Provides transactional persistence for workflows and ordered action chains."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, workflow: Workflow, actions: Sequence[WorkflowAction]) -> Workflow:
        """Persists a new workflow with its ordered actions in a single transaction."""
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        ctx_app = workflow.context_app_id.strip().lower() if workflow.context_app_id else None
        cursor = self._conn.cursor()

        try:
            cursor.execute("BEGIN IMMEDIATE;")
            cursor.execute(
                """
                INSERT INTO workflows (
                    gesture_id, name, context_app_id, enabled,
                    risk_acknowledged_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    workflow.gesture_id,
                    workflow.name.strip(),
                    ctx_app,
                    1 if workflow.enabled else 0,
                    workflow.risk_acknowledged_at,
                    now_utc,
                    now_utc,
                ),
            )
            workflow_id = cursor.lastrowid
            if workflow_id is None:
                raise RuntimeError("Failed to obtain lastrowid for new workflow")

            for pos, act in enumerate(actions):
                cursor.execute(
                    """
                    INSERT INTO workflow_actions (
                        workflow_id, position, action_type, parameters_json
                    ) VALUES (?, ?, ?, ?);
                    """,
                    (
                        workflow_id,
                        act.position if act.position >= 0 else pos,
                        act.action_type,
                        act.parameters_json,
                    ),
                )

            cursor.execute("COMMIT;")
        except sqlite3.IntegrityError as exc:
            cursor.execute("ROLLBACK;")
            cursor.close()
            if "ux_workflows_gesture_context" in str(exc) or "UNIQUE" in str(exc):
                raise InvalidWorkflow(
                    f"A workflow for gesture {workflow.gesture_id} with context '{ctx_app or 'default'}' already exists."
                ) from exc
            raise
        except Exception:
            cursor.execute("ROLLBACK;")
            cursor.close()
            raise

        cursor.close()
        saved_actions = tuple(
            WorkflowAction(
                id=None,
                workflow_id=workflow_id,
                position=act.position if act.position >= 0 else pos,
                action_type=act.action_type,
                parameters_json=act.parameters_json,
            )
            for pos, act in enumerate(actions)
        )

        return Workflow(
            id=workflow_id,
            gesture_id=workflow.gesture_id,
            name=workflow.name.strip(),
            context_app_id=ctx_app,
            enabled=workflow.enabled,
            risk_acknowledged_at=workflow.risk_acknowledged_at,
            created_at=now_utc,
            updated_at=now_utc,
            actions=saved_actions,
        )

    def update(self, workflow: Workflow, actions: Optional[Sequence[WorkflowAction]] = None) -> None:
        """Updates workflow details and atomically replaces its action list if provided."""
        if workflow.id is None:
            raise ValueError("Workflow ID must be set for update")

        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        ctx_app = workflow.context_app_id.strip().lower() if workflow.context_app_id else None
        cursor = self._conn.cursor()

        try:
            cursor.execute("BEGIN IMMEDIATE;")
            cursor.execute(
                """
                UPDATE workflows SET
                    name = ?,
                    context_app_id = ?,
                    enabled = ?,
                    risk_acknowledged_at = ?,
                    updated_at = ?
                WHERE id = ?;
                """,
                (
                    workflow.name.strip(),
                    ctx_app,
                    1 if workflow.enabled else 0,
                    workflow.risk_acknowledged_at,
                    now_utc,
                    workflow.id,
                ),
            )

            if actions is not None:
                # Replace action list in the same transaction
                cursor.execute("DELETE FROM workflow_actions WHERE workflow_id = ?;", (workflow.id,))
                for pos, act in enumerate(actions):
                    cursor.execute(
                        """
                        INSERT INTO workflow_actions (
                            workflow_id, position, action_type, parameters_json
                        ) VALUES (?, ?, ?, ?);
                        """,
                        (
                            workflow.id,
                            act.position if act.position >= 0 else pos,
                            act.action_type,
                            act.parameters_json,
                        ),
                    )

            cursor.execute("COMMIT;")
        except sqlite3.IntegrityError as exc:
            cursor.execute("ROLLBACK;")
            cursor.close()
            if "ux_workflows_gesture_context" in str(exc) or "UNIQUE" in str(exc):
                raise InvalidWorkflow(
                    f"A workflow for gesture {workflow.gesture_id} with context '{ctx_app or 'default'}' already exists."
                ) from exc
            raise
        except Exception:
            cursor.execute("ROLLBACK;")
            cursor.close()
            raise

        cursor.close()

    def acknowledge_risk(self, workflow_id: int) -> None:
        """Marks elevated risk as acknowledged by user with UTC timestamp."""
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cursor = self._conn.cursor()
        cursor.execute(
            "UPDATE workflows SET risk_acknowledged_at = ?, updated_at = ? WHERE id = ?;",
            (now_utc, now_utc, workflow_id),
        )
        cursor.close()

    def delete(self, workflow_id: int) -> bool:
        """Deletes a workflow (cascades to actions)."""
        cursor = self._conn.cursor()
        cursor.execute("DELETE FROM workflows WHERE id = ?;", (workflow_id,))
        deleted = cursor.rowcount > 0
        cursor.close()
        return deleted

    def get_by_id(self, workflow_id: int) -> Optional[Workflow]:
        """Retrieves a single workflow with its actions loaded."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT id, gesture_id, name, context_app_id, enabled,
                   risk_acknowledged_at, created_at, updated_at
            FROM workflows WHERE id = ?;
            """,
            (workflow_id,),
        )
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return None

        actions = self._fetch_actions(cursor, workflow_id)
        cursor.close()

        return Workflow(
            id=row["id"],
            gesture_id=row["gesture_id"],
            name=row["name"],
            context_app_id=row["context_app_id"],
            enabled=bool(row["enabled"]),
            risk_acknowledged_at=row["risk_acknowledged_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            actions=actions,
        )

    def get_for_gesture(self, gesture_id: int) -> List[Workflow]:
        """Returns all workflows attached to a specific gesture."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT id, gesture_id, name, context_app_id, enabled,
                   risk_acknowledged_at, created_at, updated_at
            FROM workflows WHERE gesture_id = ?
            ORDER BY context_app_id ASC, id ASC;
            """,
            (gesture_id,),
        )
        rows = cursor.fetchall()
        result: List[Workflow] = []
        for r in rows:
            wf_id = r["id"]
            actions = self._fetch_actions(cursor, wf_id)
            result.append(
                Workflow(
                    id=wf_id,
                    gesture_id=r["gesture_id"],
                    name=r["name"],
                    context_app_id=r["context_app_id"],
                    enabled=bool(r["enabled"]),
                    risk_acknowledged_at=r["risk_acknowledged_at"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    actions=actions,
                )
            )
        cursor.close()
        return result

    def list_all(self, enabled_only: bool = False) -> List[Workflow]:
        """Returns all workflows in the system."""
        cursor = self._conn.cursor()
        sql = """
            SELECT id, gesture_id, name, context_app_id, enabled,
                   risk_acknowledged_at, created_at, updated_at
            FROM workflows
        """
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY gesture_id ASC, id ASC;"

        cursor.execute(sql)
        rows = cursor.fetchall()
        result: List[Workflow] = []
        for r in rows:
            wf_id = r["id"]
            actions = self._fetch_actions(cursor, wf_id)
            result.append(
                Workflow(
                    id=wf_id,
                    gesture_id=r["gesture_id"],
                    name=r["name"],
                    context_app_id=r["context_app_id"],
                    enabled=bool(r["enabled"]),
                    risk_acknowledged_at=r["risk_acknowledged_at"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    actions=actions,
                )
            )
        cursor.close()
        return result

    def _fetch_actions(self, cursor: sqlite3.Cursor, workflow_id: int) -> Tuple[WorkflowAction, ...]:
        """Helper to fetch ordered actions for a workflow."""
        cursor.execute(
            """
            SELECT id, workflow_id, position, action_type, parameters_json
            FROM workflow_actions
            WHERE workflow_id = ?
            ORDER BY position ASC;
            """,
            (workflow_id,),
        )
        rows = cursor.fetchall()
        return tuple(
            WorkflowAction(
                id=r["id"],
                workflow_id=r["workflow_id"],
                position=r["position"],
                action_type=r["action_type"],
                parameters_json=r["parameters_json"],
            )
            for r in rows
        )
