"""Domain bus events."""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
from typing import Any, Dict, Optional
import uuid

from domain.enums import ExecutionStatus, PipelineErrorCode, RuntimeMode
from domain.models import ExecutionResult, SnapshotReport


@dataclass(frozen=True)
class DomainEvent:
    """Base class for all system bus events."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp_utc: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )


@dataclass(frozen=True)
class RuntimeStatusChanged(DomainEvent):
    """Fired when application operational mode changes."""
    mode: RuntimeMode = RuntimeMode.STOPPED
    previous_mode: RuntimeMode = RuntimeMode.STOPPED
    reason: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineErrorOccurred(DomainEvent):
    """Fired when camera or tracker experiences hardware or pipeline faults."""
    code: PipelineErrorCode = PipelineErrorCode.CAMERA_LOST
    message: str = ""


@dataclass(frozen=True)
class GestureRegistered(DomainEvent):
    """Fired when a new gesture is persisted."""
    gesture_id: int = 0
    name: str = ""


@dataclass(frozen=True)
class GestureUpdated(DomainEvent):
    """Fired when an existing gesture is modified or re-recorded."""
    gesture_id: int = 0
    name: str = ""


@dataclass(frozen=True)
class GestureDeleted(DomainEvent):
    """Fired when a gesture is deleted."""
    gesture_id: int = 0
    name: str = ""


@dataclass(frozen=True)
class WorkflowUpdated(DomainEvent):
    """Fired when a workflow is saved or updated."""
    workflow_id: int = 0
    gesture_id: int = 0


@dataclass(frozen=True)
class WorkflowDeleted(DomainEvent):
    """Fired when a workflow is removed."""
    workflow_id: int = 0
    gesture_id: int = 0


@dataclass(frozen=True)
class SnapshotRebuilt(DomainEvent):
    """Fired when template or workflow snapshots are atomically compiled."""
    template_revision: int = 0
    workflow_revision: int = 0
    report: Optional[SnapshotReport] = None


@dataclass(frozen=True)
class WorkflowExecutionStarted(DomainEvent):
    """Fired when an admitted execution request begins running."""
    correlation_id: str = ""
    workflow_id: int = 0
    workflow_name: str = ""
    app_id: str = ""


@dataclass(frozen=True)
class WorkflowExecutionFinished(DomainEvent):
    """Fired when a workflow completes execution."""
    result: Optional[ExecutionResult] = None


@dataclass(frozen=True)
class ExecutionDropped(DomainEvent):
    """Fired when a trigger is dropped due to busy worker, non-live mode, or suppression."""
    reason: ExecutionStatus = ExecutionStatus.DROPPED_BUSY
    gesture_id: int = 0
    details: str = ""
