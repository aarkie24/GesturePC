"""Dedicated thread worker capturing video frames into appropriate mailboxes."""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import numpy as np

from camera.frame_types import FramePacket, LatestFrameMailbox, LosslessFrameQueue
from domain.enums import PipelineErrorCode
from domain.events import PipelineErrorOccurred
from domain.ports import CameraBackend
from services.event_bus import EventBus

logger = logging.getLogger(__name__)


class CaptureWorker:
    """Runs high-rate camera capture loop on a dedicated thread."""

    def __init__(
        self,
        backend: CameraBackend,
        live_mailbox: LatestFrameMailbox,
        recording_queue: Optional[LosslessFrameQueue] = None,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self._backend = backend
        self._live_mailbox = live_mailbox
        self._recording_queue = recording_queue
        self._event_bus = event_bus

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._frame_id = 0
        self._is_recording = False
        self._last_frame_ts_ns: int = 0
        self._consecutive_failures = 0

    def start(self) -> None:
        """Starts the capture loop thread."""
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._frame_id = 0
        self._consecutive_failures = 0
        self._last_frame_ts_ns = time.monotonic_ns()

        self._thread = threading.Thread(
            target=self._capture_loop,
            name="CameraCaptureWorker",
            daemon=True,
        )
        self._thread.start()
        logger.info("Camera capture worker thread started.")

    def stop(self, timeout_sec: float = 2.0) -> None:
        """Signals stop and waits for capture thread to exit (bounded <= 2s)."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout_sec)
            if self._thread.is_alive():
                logger.warning("Camera capture thread did not terminate within %.1f seconds", timeout_sec)
        self._thread = None
        logger.info("Camera capture worker stopped.")

    def set_recording_mode(self, enabled: bool) -> None:
        """Enables or disables pushing frames into the lossless recording queue."""
        self._is_recording = enabled

    @property
    def last_frame_ts_ns(self) -> int:
        return self._last_frame_ts_ns

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _capture_loop(self) -> None:
        """Continuous frame grab loop."""
        while not self._stop_event.is_set():
            ret, frame_bgr, ts_ns = self._backend.read_frame()
            if not ret or frame_bgr is None:
                self._consecutive_failures += 1
                if self._consecutive_failures >= 30:
                    logger.error("Camera read failed consecutively 30 times. Publishing CAMERA_LOST.")
                    if self._event_bus:
                        self._event_bus.publish(
                            PipelineErrorOccurred(
                                code=PipelineErrorCode.CAMERA_LOST,
                                message="Camera read failed consecutively 30 times.",
                            )
                        )
                    break
                time.sleep(0.01)
                continue

            self._consecutive_failures = 0
            self._frame_id += 1
            self._last_frame_ts_ns = ts_ns

            h, w = frame_bgr.shape[:2]
            aspect = float(w) / float(h) if h > 0 else 1.333
            packet = FramePacket(
                frame_id=self._frame_id,
                capture_ts_ns=ts_ns,
                frame_bgr=frame_bgr,
                aspect_ratio=aspect,
            )

            # Always populate live mailbox for preview / matching
            self._live_mailbox.put(packet)

            # In recording mode, also route to lossless queue
            if self._is_recording and self._recording_queue is not None:
                if not self._recording_queue.put(packet):
                    logger.warning("Recording queue overflow; dropped frame %d", self._frame_id)
