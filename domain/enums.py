"""Enumerations used throughout the Gesture PC domain."""

from enum import Enum, unique


@unique
class RuntimeMode(str, Enum):
    """Runtime operational modes of the application."""
    STOPPED = "STOPPED"
    RECORDING = "RECORDING"
    TEST = "TEST"
    LIVE = "LIVE"


@unique
class GestureType(str, Enum):
    """Classification of gesture dynamics."""
    STATIC = "STATIC"
    DYNAMIC = "DYNAMIC"


@unique
class Hand(str, Enum):
    """Hand laterality."""
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    EITHER = "EITHER"


@unique
class RiskTier(str, Enum):
    """Workflow action risk classification."""
    SAFE = "SAFE"
    ELEVATED = "ELEVATED"


@unique
class TriggerState(str, Enum):
    """Internal state machine of the trigger validator."""
    IDLE = "IDLE"
    ACCUMULATING = "ACCUMULATING"
    FIRED = "FIRED"
    COOLDOWN = "COOLDOWN"
    REARMING = "REARMING"


@unique
class TrackingStatus(str, Enum):
    """Hand tracker extraction status."""
    OK = "OK"
    NO_HAND = "NO_HAND"
    TRACKER_ERROR = "TRACKER_ERROR"


@unique
class RejectReason(str, Enum):
    """Reasons why a recording, frame, or candidate match was rejected."""
    NO_HAND = "NO_HAND"
    WRONG_HAND = "WRONG_HAND"
    AMBIGUOUS_HANDS = "AMBIGUOUS_HANDS"
    DEGENERATE_HAND = "DEGENERATE_HAND"
    TOO_FEW_VALID_FRAMES = "TOO_FEW_VALID_FRAMES"
    HAND_MOVING = "HAND_MOVING"
    LOW_FPS = "LOW_FPS"
    TOO_SHORT = "TOO_SHORT"
    INSUFFICIENT_MOTION = "INSUFFICIENT_MOTION"
    TOO_MANY_GAPS = "TOO_MANY_GAPS"
    INCONSISTENT_SAMPLES = "INCONSISTENT_SAMPLES"
    TRACKING_LOST = "TRACKING_LOST"
    ABOVE_THRESHOLD = "ABOVE_THRESHOLD"
    AMBIGUOUS_MARGIN = "AMBIGUOUS_MARGIN"
    MOVING = "MOVING"
    SEGMENT_NO_MATCH = "SEGMENT_NO_MATCH"


@unique
class ExecutionStatus(str, Enum):
    """Outcome status of workflow execution attempts."""
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    DROPPED_NOT_LIVE = "DROPPED_NOT_LIVE"
    DROPPED_BUSY = "DROPPED_BUSY"
    EXPIRED = "EXPIRED"
    SUPPRESSED_SELF_FOREGROUND = "SUPPRESSED_SELF_FOREGROUND"
    NO_WORKFLOW = "NO_WORKFLOW"
    GESTURE_DISABLED = "GESTURE_DISABLED"
    SKIPPED_WORKFLOW_DISABLED = "SKIPPED_WORKFLOW_DISABLED"
    SKIPPED_CONTEXT_CHANGED = "SKIPPED_CONTEXT_CHANGED"
    SKIPPED_ELEVATED_TARGET = "SKIPPED_ELEVATED_TARGET"


@unique
class ActionErrorCode(str, Enum):
    """Specific error codes for workflow action failures."""
    ACTION_REJECTED = "ACTION_REJECTED"
    ADAPTER_ERROR = "ADAPTER_ERROR"
    TIMEOUT = "TIMEOUT"
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    APP_NOT_APPROVED = "APP_NOT_APPROVED"


@unique
class PipelineErrorCode(str, Enum):
    """Camera and tracker hardware/pipeline errors."""
    CAMERA_NOT_FOUND = "CAMERA_NOT_FOUND"
    CAMERA_BUSY = "CAMERA_BUSY"
    CAMERA_NO_FRAMES = "CAMERA_NO_FRAMES"
    CAMERA_LOST = "CAMERA_LOST"
    TRACKER_MODEL_INVALID = "TRACKER_MODEL_INVALID"
    TRACKER_ERROR = "TRACKER_ERROR"


@unique
class SnapshotExclusionReason(str, Enum):
    """Reasons why a gesture or workflow is excluded from an active snapshot."""
    NEEDS_RERECORDING = "NEEDS_RERECORDING"
    INVALID_LANDMARKS = "INVALID_LANDMARKS"
    UNSUPPORTED_TRACKER_MODEL = "UNSUPPORTED_TRACKER_MODEL"
    INVALID_WORKFLOW = "INVALID_WORKFLOW"
    RISK_NOT_ACKNOWLEDGED = "RISK_NOT_ACKNOWLEDGED"
    MISSING_APP_REF = "MISSING_APP_REF"
