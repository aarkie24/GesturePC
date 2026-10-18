"""Domain exception definitions."""


class GesturePCError(Exception):
    """Base exception for all Gesture PC errors."""


class InvalidRecording(GesturePCError):
    """Raised when a gesture recording fails validation."""


class DuplicateGestureName(GesturePCError):
    """Raised when attempting to create or rename a gesture to an existing name."""


class InvalidWorkflow(GesturePCError):
    """Raised when a workflow configuration is structurally invalid."""


class InvalidModeTransition(GesturePCError):
    """Raised when attempting an unauthorized or invalid state machine transition."""


class CameraUnavailable(GesturePCError):
    """Raised when the camera device cannot be opened, is disconnected, or stalls."""


class SnapshotInvalid(GesturePCError):
    """Raised when building a template or workflow snapshot fails unrecoverably."""


class ActionRejected(GesturePCError):
    """Raised when a workflow action cannot be performed or violates constraints."""


class DatabaseMigrationError(GesturePCError):
    """Raised when a database migration fails or is incompatible."""


class DatabaseCorruptError(GesturePCError):
    """Raised when database integrity check fails."""


class SettingsValidationError(GesturePCError):
    """Raised when a setting value violates its schema constraints."""
