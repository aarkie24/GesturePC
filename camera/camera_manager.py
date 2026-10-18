"""Camera hardware and capture worker coordinator."""

from __future__ import annotations

import logging
import threading
from typing import Optional

from app.config import SettingsSchema
from camera.capture_worker import CaptureWorker
from camera.frame_types import LatestFrameMailbox, LosslessFrameQueue
from domain.exceptions import CameraUnavailable
from domain.ports import CameraBackend
from services.event_bus import EventBus

logger = logging.getLogger(__name__)


class CameraManager:
    """Manages the single active camera hardware handle and background capture worker."""

    def __init__(
        self,
        backend: CameraBackend,
        settings: SettingsSchema,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self._backend = backend
        self._settings = settings
        self._event_bus = event_bus

        self._lock = threading.Lock()
        self._live_mailbox = LatestFrameMailbox()
        self._recording_queue = LosslessFrameQueue(maxsize=settings.recording_queue_frames)
        self._capture_worker: Optional[CaptureWorker] = None
        self._is_active = False

    @property
    def live_mailbox(self) -> LatestFrameMailbox:
        """Returns the mailbox where latest frames are placed for live matching and UI preview."""
        return self._live_mailbox

    @property
    def recording_queue(self) -> LosslessFrameQueue:
        """Returns the lossless frame queue used during gesture recording."""
        return self._recording_queue

    @property
    def is_running(self) -> bool:
        """Returns True if the camera is actively capturing frames."""
        with self._lock:
            return self._is_active and self._backend.is_opened()

    def start_pipeline(self) -> None:
        """Opens the camera backend and starts the capture worker."""
        with self._lock:
            if self._is_active:
                return

            opened = self._backend.open(
                index=self._settings.camera_index,
                backend_name=self._settings.camera_backend,
                width=self._settings.capture_width,
                height=self._settings.capture_height,
                fps=self._settings.capture_fps,
            )
            if not opened:
                raise CameraUnavailable(
                    f"Could not open camera {self._settings.camera_index} with backend {self._settings.camera_backend}."
                )

            self._live_mailbox.clear()
            self._recording_queue.clear()

            self._capture_worker = CaptureWorker(
                backend=self._backend,
                live_mailbox=self._live_mailbox,
                recording_queue=self._recording_queue,
                event_bus=self._event_bus,
            )
            self._capture_worker.start()
            self._is_active = True
            logger.info("Camera pipeline started successfully.")

    def stop_pipeline(self, timeout_sec: float = 2.0) -> None:
        """Stops the capture worker and releases the camera device within timeout_sec."""
        with self._lock:
            if not self._is_active:
                return

            if self._capture_worker is not None:
                self._capture_worker.stop(timeout_sec=timeout_sec)
                self._capture_worker = None

            self._backend.release()
            self._live_mailbox.clear()
            self._recording_queue.clear()
            self._is_active = False
            logger.info("Camera pipeline stopped cleanly.")

    def set_recording_mode(self, enabled: bool) -> None:
        """Enables or disables lossless frame queuing for gesture recording."""
        with self._lock:
            if self._capture_worker:
                self._capture_worker.set_recording_mode(enabled)
            if not enabled:
                self._recording_queue.clear()
