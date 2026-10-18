"""RuntimeController managing operational modes, transitions, and the safety boundary."""

from __future__ import annotations

import logging
import threading
from typing import Callable, Dict, Optional, Tuple

from app.config import SettingsSchema
from camera.camera_manager import CameraManager
from domain.enums import RuntimeMode
from domain.events import RuntimeStatusChanged
from domain.exceptions import InvalidModeTransition
from domain.ports import EventSink, GlobalHotkeyService
from services.diagnostic_sink import DiagnosticSink
from services.event_bus import EventBus
from services.execution_gate import ExecutionGate

logger = logging.getLogger(__name__)

# Valid state machine transitions from §4.2
VALID_TRANSITIONS: Dict[Tuple[RuntimeMode, RuntimeMode], bool] = {
    (RuntimeMode.STOPPED, RuntimeMode.TEST): True,
    (RuntimeMode.STOPPED, RuntimeMode.LIVE): True,
    (RuntimeMode.STOPPED, RuntimeMode.RECORDING): True,
    (RuntimeMode.TEST, RuntimeMode.STOPPED): True,
    (RuntimeMode.TEST, RuntimeMode.LIVE): True,
    (RuntimeMode.TEST, RuntimeMode.RECORDING): True,
    (RuntimeMode.LIVE, RuntimeMode.STOPPED): True,
    (RuntimeMode.LIVE, RuntimeMode.TEST): True,
    (RuntimeMode.LIVE, RuntimeMode.RECORDING): True,  # Triggers LIVE -> STOPPED -> RECORDING
    (RuntimeMode.RECORDING, RuntimeMode.STOPPED): True,
}


class RuntimeController:
    """Controls runtime modes (STOPPED, RECORDING, TEST, LIVE) and enforces safety preconditions."""

    def __init__(
        self,
        gate: ExecutionGate,
        camera_manager: CameraManager,
        settings: SettingsSchema,
        diagnostic_sink: DiagnosticSink,
        live_sink: Optional[EventSink] = None,
        hotkey_service: Optional[GlobalHotkeyService] = None,
        event_bus: Optional[EventBus] = None,
        has_executable_workflows_check: Optional[Callable[[], bool]] = None,
        is_session_unlocked_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._gate = gate
        self._camera_manager = camera_manager
        self._settings = settings
        self._diagnostic_sink = diagnostic_sink
        self._live_sink = live_sink
        self._hotkey_service = hotkey_service
        self._event_bus = event_bus

        self._has_executable_workflows = has_executable_workflows_check or (lambda: True)
        self._is_session_unlocked = is_session_unlocked_check or (lambda: True)

        self._lock = threading.Lock()
        self._mode: RuntimeMode = RuntimeMode.STOPPED
        self._active_sink: EventSink = diagnostic_sink
        self._consecutive_failures = 0
        self._executions_this_minute = 0
        self._minute_window_start_ns = 0

    @property
    def mode(self) -> RuntimeMode:
        with self._lock:
            return self._mode

    @property
    def current_mode(self) -> RuntimeMode:
        """Alias for mode property."""
        with self._lock:
            return self._mode

    @property
    def active_sink(self) -> EventSink:
        with self._lock:
            return self._active_sink

    def transition_to(self, target_mode: RuntimeMode, reason: str = "") -> None:
        """Transitions application state to target_mode following transition table rules."""
        with self._lock:
            current = self._mode
            if current == target_mode:
                return

            # Check transition legality
            if (current, target_mode) not in VALID_TRANSITIONS:
                raise InvalidModeTransition(f"Illegal mode transition from {current.value} to {target_mode.value}.")

            # Transition handlers
            if target_mode == RuntimeMode.STOPPED:
                self._enter_stopped(reason)
            elif target_mode == RuntimeMode.TEST:
                self._enter_test(reason)
            elif target_mode == RuntimeMode.LIVE:
                self._enter_live(reason)
            elif target_mode == RuntimeMode.RECORDING:
                if current == RuntimeMode.LIVE:
                    # Intermediate forced return to STOPPED first
                    self._enter_stopped("Transitioning from LIVE to RECORDING")
                self._enter_recording(reason)

            prev_mode = current
            self._mode = target_mode
            logger.info("Runtime mode changed: %s -> %s (reason: %s)", prev_mode.value, target_mode.value, reason)

        # Publish outside lock
        if self._event_bus:
            self._event_bus.publish(
                RuntimeStatusChanged(
                    mode=target_mode,
                    previous_mode=prev_mode,
                    reason=reason,
                )
            )

    def emergency_stop(self, reason: str = "EMERGENCY_STOP") -> None:
        """Immediate stop mechanism called by hotkey, overlay, tray, or error detectors."""
        # 1. Instantly close gate (O(1), cancels all admissions)
        self._gate.close(reason)

        with self._lock:
            prev_mode = self._mode
            if prev_mode == RuntimeMode.STOPPED:
                return

            self._enter_stopped(reason)
            self._mode = RuntimeMode.STOPPED
            logger.warning("EMERGENCY STOP executed: %s -> STOPPED (%s)", prev_mode.value, reason)

        if self._event_bus:
            self._event_bus.publish(
                RuntimeStatusChanged(
                    mode=RuntimeMode.STOPPED,
                    previous_mode=prev_mode,
                    reason=reason,
                )
            )

    def _enter_stopped(self, reason: str) -> None:
        """Internal logic for entering STOPPED mode."""
        self._gate.close(reason)
        self._camera_manager.stop_pipeline()
        self._active_sink = self._diagnostic_sink

    def _enter_test(self, reason: str) -> None:
        """Internal logic for entering TEST mode."""
        self._gate.close("ENTERING_TEST")
        self._active_sink = self._diagnostic_sink
        self._camera_manager.set_recording_mode(False)
        self._camera_manager.start_pipeline()

    def _enter_recording(self, reason: str) -> None:
        """Internal logic for entering RECORDING mode."""
        self._gate.close("ENTERING_RECORDING")
        self._active_sink = self._diagnostic_sink
        self._camera_manager.start_pipeline()
        self._camera_manager.set_recording_mode(True)

    def _enter_live(self, reason: str) -> None:
        """Internal logic for entering LIVE mode with strict precondition verification."""
        # Verify §4.3 Preconditions:
        # 1. Hotkey must be registered
        if self._hotkey_service and not self._hotkey_service.is_registered():
            raise InvalidModeTransition("Cannot enter LIVE mode: Global stop hotkey is not registered.")

        # 2. Session unlocked
        if not self._is_session_unlocked():
            raise InvalidModeTransition("Cannot enter LIVE mode: Windows session is locked.")

        # 3. Has enabled workflows
        if not self._has_executable_workflows():
            raise InvalidModeTransition("Cannot enter LIVE mode: No enabled gestures with valid workflows exist.")

        # 4. Camera running
        self._camera_manager.set_recording_mode(False)
        self._camera_manager.start_pipeline()

        # 5. Open ExecutionGate
        self._gate.open_for_live()

        # 6. Set LiveSink
        if self._live_sink is not None:
            self._active_sink = self._live_sink
        else:
            self._active_sink = self._diagnostic_sink

        self._consecutive_failures = 0
