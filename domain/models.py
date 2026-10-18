"""Domain models for Gesture PC. All domain models are immutable frozen dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple
import numpy as np

from domain.enums import (
    ActionErrorCode,
    ExecutionStatus,
    GestureType,
    Hand,
    RejectReason,
    SnapshotExclusionReason,
    TrackingStatus,
    TriggerState,
)


@dataclass(frozen=True)
class HandObservation:
    """Landmark observation for a single hand in a camera frame."""
    label: str  # "Left" or "Right" as reported by tracker
    label_score: float
    presence_score: float
    landmarks_image: np.ndarray  # float32 shape (21, 3) normalized x, y, depth
    landmarks_world: np.ndarray  # float32 shape (21, 3) metric space

    def __post_init__(self) -> None:
        if self.landmarks_image.flags.writeable:
            self.landmarks_image.setflags(write=False)
        if self.landmarks_world.flags.writeable:
            self.landmarks_world.setflags(write=False)


@dataclass(frozen=True)
class TrackingResult:
    """Tracker output for a single frame."""
    frame_id: int
    capture_ts_ns: int
    frame_size: Tuple[int, int]  # (width, height)
    status: TrackingStatus
    hands: Tuple[HandObservation, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Gesture:
    """User-registered gesture entity."""
    id: Optional[int]
    name: str
    gesture_type: GestureType
    hand: Hand
    enabled: bool = True
    threshold_scale: float = 1.0
    template_revision: int = 1
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class GestureSample:
    """One recording observation of a gesture."""
    id: Optional[int]
    gesture_id: int
    sample_index: int
    frame_count: int
    duration_ms: int
    landmarks_image: np.ndarray  # float32 shape (frame_count, 21, 3)
    landmarks_world: np.ndarray  # float32 shape (frame_count, 21, 3)
    timestamps_ms: Optional[np.ndarray]  # int32 shape (frame_count,) or None if static
    frame_aspect_ratio: float
    tracker_model_id: str
    preprocess_json: str
    created_at: str = ""

    def __post_init__(self) -> None:
        if self.landmarks_image.flags.writeable:
            self.landmarks_image.setflags(write=False)
        if self.landmarks_world.flags.writeable:
            self.landmarks_world.setflags(write=False)
        if self.timestamps_ms is not None and self.timestamps_ms.flags.writeable:
            self.timestamps_ms.setflags(write=False)


@dataclass(frozen=True)
class RecordingResult:
    """Outcome of a gesture recording session."""
    gesture_type: GestureType
    hand: Hand
    samples: Tuple[GestureSample, ...]
    duration_ms: int
    effective_fps: float
    valid: bool
    reject_reason: Optional[RejectReason] = None
    feedback_key: str = ""
    collisions: Tuple[Tuple[str, float], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class FrameAnalysis:
    """Per-frame diagnostic record produced by recognition engine (UI-only)."""
    frame_id: int
    capture_ts_ns: int
    hand_status: TrackingStatus
    motion_state: str  # "STATIONARY", "MOVING", "NO_HAND"
    hand_speed: float  # palm units / sec
    best_gesture_id: Optional[int]
    best_distance: float
    second_gesture_id: Optional[int]
    second_distance: float
    threshold: float
    margin_ratio: float
    outcome: str
    reject_reason: Optional[RejectReason]
    trigger_state: TriggerState
    accumulated_ms: int


@dataclass(frozen=True)
class RecognitionEvent:
    """Accepted trigger event from recognition engine after stability and cooldown checks."""
    event_id: str  # UUID4
    gesture_id: int
    gesture_name: str
    gesture_type: GestureType
    hand: Hand
    capture_ts_ns: int
    timestamp_utc: str
    distance: float
    threshold: float
    margin_ratio: float


@dataclass(frozen=True)
class Admission:
    """Gate admission ticket issued by ExecutionGate to LiveSink."""
    epoch: int
    token: str


@dataclass(frozen=True)
class AppContext:
    """Active desktop foreground context at trigger time."""
    app_id: str  # lower-case normalized executable name or identifier
    display_name: str
    exe_path: str
    window_title: str
    is_elevated: bool
    is_self: bool


@dataclass(frozen=True)
class ApprovedApplication:
    """Application executable allowed to be launched by application actions."""
    id: Optional[int]
    display_name: str
    exe_path: str
    created_at: str = ""


@dataclass(frozen=True)
class WorkflowAction:
    """Configured step within a workflow."""
    id: Optional[int]
    workflow_id: Optional[int]
    position: int
    action_type: str
    parameters_json: str


@dataclass(frozen=True)
class Workflow:
    """Workflow entity bound to a gesture and optionally to a foreground app."""
    id: Optional[int]
    gesture_id: int
    name: str
    context_app_id: Optional[str]  # None for default workflow
    enabled: bool = True
    risk_acknowledged_at: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    actions: Tuple[WorkflowAction, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class WorkflowDefinition:
    """Immutable, validated executable representation of a workflow."""
    workflow_id: int
    workflow_name: str
    gesture_id: int
    context_app_id: Optional[str]
    actions: Tuple[WorkflowAction, ...]
    has_elevated_actions: bool


@dataclass(frozen=True)
class ExecutionRequest:
    """Request handed to ExecutionDispatcher in LIVE mode."""
    correlation_id: str
    gesture_id: int
    workflow: WorkflowDefinition
    context: AppContext
    admission: Admission
    created_ns: int


@dataclass(frozen=True)
class ActionResult:
    """Execution result for an individual workflow action."""
    position: int
    action_type: str
    status: ExecutionStatus
    error_code: Optional[ActionErrorCode] = None
    duration_ms: int = 0


@dataclass(frozen=True)
class ExecutionResult:
    """Complete summary of a workflow execution run."""
    correlation_id: str
    workflow_id: int
    workflow_name: str
    status: ExecutionStatus
    started_utc: str
    ended_utc: str
    actions: Tuple[ActionResult, ...] = field(default_factory=tuple)
    failed_position: Optional[int] = None
    error_code: Optional[ActionErrorCode] = None
    safe_summary: str = ""


@dataclass(frozen=True)
class SnapshotReport:
    """Diagnostic report generated during snapshot compilation."""
    excluded_gestures: Tuple[Tuple[int, str, SnapshotExclusionReason], ...] = field(default_factory=tuple)
    excluded_workflows: Tuple[Tuple[int, str, SnapshotExclusionReason], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TemplateSnapshot:
    """Immutable cache of validated gesture templates for the recognition engine."""
    revision: int
    templates: Tuple[Any, ...]  # StaticTemplate / DynamicTemplate items
    revision_map: Dict[int, int]  # gesture_id -> template_revision
    timestamp_utc: str
    report: SnapshotReport = field(default_factory=SnapshotReport)


@dataclass(frozen=True)
class WorkflowSnapshot:
    """Immutable cache of validated workflow definitions for the resolver."""
    revision: int
    default_workflows: Dict[int, WorkflowDefinition]  # gesture_id -> default workflow
    app_workflows: Dict[Tuple[int, str], WorkflowDefinition]  # (gesture_id, app_id) -> workflow
    timestamp_utc: str
    report: SnapshotReport = field(default_factory=SnapshotReport)
