"""Background recognition pipeline processing live camera frames into tracking and recognition."""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from app.config import SettingsSchema
from camera.camera_manager import CameraManager
from camera.hand_tracker import HandTracker
from domain.enums import Hand, RuntimeMode
from domain.models import FrameAnalysis, RecognitionEvent
from gestures.recognition_engine import RecognitionEngine
from services.runtime_controller import RuntimeController
from services.snapshot_service import SnapshotService
from ui.qt_bridge import QtBridge

logger = logging.getLogger(__name__)


class RecognitionPipeline:
    """Manages the background loop extracting landmarks and executing gesture recognition."""

    def __init__(
        self,
        camera_manager: CameraManager,
        hand_tracker: HandTracker,
        recognition_engine: RecognitionEngine,
        snapshot_service: SnapshotService,
        runtime_controller: RuntimeController,
        qt_bridge: Optional[QtBridge] = None,
        settings: Optional[SettingsSchema] = None,
    ) -> None:
        self._camera_manager = camera_manager
        self._hand_tracker = hand_tracker
        self._engine = recognition_engine
        self._snapshot_service = snapshot_service
        self._controller = runtime_controller
        self._qt_bridge = qt_bridge
        self._settings = settings

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Starts the background tracking and recognition thread."""
        with self._lock:
            if self.is_running:
                return

            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="RecognitionPipelineThread",
                daemon=True,
            )
            self._thread.start()
            logger.info("RecognitionPipeline thread started.")

    def stop(self, timeout_sec: float = 2.0) -> None:
        """Signals worker to stop and waits for termination."""
        with self._lock:
            if not self.is_running:
                return

            self._stop_event.set()
            if self._thread is not None:
                self._thread.join(timeout=timeout_sec)
                self._thread = None
            logger.info("RecognitionPipeline thread stopped.")

    def _run_loop(self) -> None:
        """Main processing loop fetching frames from mailbox, running tracker and engine."""
        logger.debug("Entering recognition pipeline processing loop.")

        while not self._stop_event.is_set():
            mode = self._controller.current_mode
            if mode == RuntimeMode.STOPPED:
                # Camera is stopped, wait briefly
                self._stop_event.wait(0.05)
                continue

            # Fetch latest frame from mailbox
            packet = self._camera_manager.live_mailbox.get(timeout_ms=50)
            if packet is None:
                continue

            # Extract hand landmarks via HandTracker
            ts_ms = int(packet.timestamp_ns / 1_000_000)
            try:
                tracking_res = self._hand_tracker.process_frame(
                    frame_bgr=packet.frame_bgr,
                    timestamp_ms=ts_ms,
                    frame_id=packet.frame_id,
                    capture_ts_ns=packet.timestamp_ns,
                )
            except Exception as exc:
                logger.error("Error during hand landmark extraction: %s", exc)
                continue

            # Forward video frame and skeleton landmarks to UI preview
            if self._qt_bridge is not None:
                self._qt_bridge.emit_frame(packet, tracking_res)

            # In TEST or LIVE mode: evaluate recognition engine
            if mode in (RuntimeMode.TEST, RuntimeMode.LIVE):
                snapshot = self._snapshot_service.get_template_snapshot()
                tracked_hand_enum = Hand(self._settings.tracked_hand) if self._settings else Hand.RIGHT
                sensitivity = self._settings.sensitivity if self._settings else 1.0
                margin_limit = self._settings.margin_ratio if self._settings else 0.80

                analysis, event = self._engine.process(
                    tracking_result=tracking_res,
                    snapshot=snapshot,
                    tracked_hand=tracked_hand_enum,
                    global_sensitivity=sensitivity,
                    margin_ratio_limit=margin_limit,
                )

                # Feed active sink
                active_sink = self._controller.active_sink
                if active_sink is not None:
                    try:
                        active_sink.on_frame_analysis(analysis)
                    except Exception as exc:
                        logger.error("Error in active sink on_frame_analysis: %s", exc)

                    if event is not None:
                        try:
                            active_sink.on_recognition_event(event)
                        except Exception as exc:
                            logger.error("Error in active sink on_recognition_event: %s", exc)

                # Send telemetry and events to UI via QtBridge
                if self._qt_bridge is not None:
                    self._qt_bridge.emit_frame_analysis(analysis)
                    if event is not None:
                        self._qt_bridge.emit_trigger_recognized(event)

        logger.debug("Exited recognition pipeline processing loop.")
