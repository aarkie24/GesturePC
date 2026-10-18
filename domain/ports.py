"""Port definitions (Protocols) defining interfaces for infrastructure and hardware adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol, Tuple, runtime_checkable
import numpy as np

if TYPE_CHECKING:
    from domain.models import (
        AppContext,
        FrameAnalysis,
        RecognitionEvent,
        TrackingResult,
    )


@runtime_checkable
class Clock(Protocol):
    """Port for time measurement and deterministic delays."""

    def time(self) -> float:
        """Returns the current UTC timestamp in seconds."""
        ...

    def monotonic(self) -> float:
        """Returns monotonic time in seconds."""
        ...

    def monotonic_ns(self) -> int:
        """Returns monotonic time in nanoseconds."""
        ...

    def sleep(self, seconds: float) -> None:
        """Suspends execution for the specified duration."""
        ...


@runtime_checkable
class CameraBackend(Protocol):
    """Port for video capture hardware abstraction."""

    def open(self, index: int, backend_name: str, width: int, height: int, fps: int) -> bool:
        """Opens camera device at index with given settings."""
        ...

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray], int]:
        """Reads the latest frame. Returns (success, frame_bgr, timestamp_ns)."""
        ...

    def is_opened(self) -> bool:
        """Returns True if the camera handle is valid and delivering."""
        ...

    def release(self) -> None:
        """Releases the camera device cleanly."""
        ...


@runtime_checkable
class HandTrackerBackend(Protocol):
    """Port for hand landmark extraction backend (e.g. MediaPipe Tasks)."""

    def process_frame(self, frame_bgr: np.ndarray, timestamp_ms: int) -> TrackingResult:
        """Extracts 3D landmarks for the supplied frame."""
        ...

    def close(self) -> None:
        """Releases tracker model resources."""
        ...


@runtime_checkable
class ForegroundWindowProvider(Protocol):
    """Port for inspecting active desktop window and foreground process."""

    def get_foreground_context(self) -> AppContext:
        """Captures the current foreground application identity and window metadata."""
        ...


@runtime_checkable
class DesktopActionAdapter(Protocol):
    """Port for synthesizing user input and managing desktop windows."""

    def send_hotkey(self, keys: Tuple[str, ...]) -> bool:
        """Synthesizes a keyboard shortcut chord."""
        ...

    def send_text(self, text: str) -> bool:
        """Types unicode string into the focused control."""
        ...

    def mouse_click(self, button: str, x: int, y: int, relative: bool = False) -> bool:
        """Sends mouse click at coordinates."""
        ...

    def mouse_scroll(self, clicks: int) -> bool:
        """Synthesizes vertical mouse wheel scroll."""
        ...

    def set_window_state(self, action: str) -> bool:
        """Minimizes, maximizes, restores, or closes the target window."""
        ...

    def launch_app(self, exe_path: str, args: Optional[str] = None) -> bool:
        """Launches an approved application executable."""
        ...


@runtime_checkable
class GlobalHotkeyService(Protocol):
    """Port for system-wide emergency stop hotkey listening."""

    def register(self, chord: str) -> bool:
        """Registers the specified chord globally."""
        ...

    def unregister(self) -> None:
        """Unregisters the hotkey."""
        ...

    def is_registered(self) -> bool:
        """Returns True if hotkey registration is currently active."""
        ...


@runtime_checkable
class SessionEventSource(Protocol):
    """Port for OS session locking, logoff, and display sleep notifications."""

    def start(self) -> None:
        """Begins listening for OS session state changes."""
        ...

    def stop(self) -> None:
        """Stops listening."""
        ...


@runtime_checkable
class EventSink(Protocol):
    """Port for consumers of recognition engine output."""

    def on_frame_analysis(self, analysis: FrameAnalysis) -> None:
        """Receives per-frame diagnostic information."""
        ...

    def on_recognition_event(self, event: RecognitionEvent) -> None:
        """Receives an accepted trigger event after trigger validation."""
        ...
