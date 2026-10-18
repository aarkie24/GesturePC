"""Application constants and immutable configuration boundaries."""

APP_NAME = "GesturePC"
APP_DISPLAY_NAME = "Gesture PC"

# Algorithm & Representation Versions
NORMALIZER_VERSION = 1
FEATURE_VERSION = 1

# Bundled Tracker Model
TRACKER_MODEL_FILENAME = "hand_landmarker.task"
TRACKER_MODEL_SHA256 = "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1"
TRACKER_MODEL_ID = f"{TRACKER_MODEL_FILENAME}@{TRACKER_MODEL_SHA256[:12]}"
COMPATIBLE_TRACKER_MODELS = (TRACKER_MODEL_ID,)

# Safety & Chord Constraints
DEFAULT_STOP_HOTKEY = "Ctrl+Alt+Shift+X"
SENSITIVE_CHORDS = frozenset([
    "Ctrl+Alt+Del",
    "Alt+F4",
    "Win+L",
    "Ctrl+Shift+Esc",
])

# Limits
MAX_ACTIONS_PER_WORKFLOW = 20
MAX_TOTAL_DELAY_MS = 30000
WORKFLOW_WATCHDOG_MS = 60000
ACTION_TIMEOUT_MS = 5000
DIAGNOSTICS_RING_BUFFER_SIZE = 500
