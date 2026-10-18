"""High-level hand tracking coordinator."""

from __future__ import annotations

import logging
from typing import Optional
import numpy as np

from domain.models import TrackingResult
from domain.ports import HandTrackerBackend

logger = logging.getLogger(__name__)


class HandTracker:
    """Coordinates hand landmark detection using an injected tracker backend."""

    def __init__(self, backend: HandTrackerBackend) -> None:
        self._backend = backend

    def process_frame(
        self,
        frame_bgr: np.ndarray,
        timestamp_ms: int,
        frame_id: int = 0,
        capture_ts_ns: int = 0,
    ) -> TrackingResult:
        """Processes frame through tracker backend."""
        # Check backend signature
        if hasattr(self._backend, "process_frame"):
            try:
                return self._backend.process_frame(
                    frame_bgr=frame_bgr,
                    timestamp_ms=timestamp_ms,
                    frame_id=frame_id,
                    capture_ts_ns=capture_ts_ns,
                )
            except TypeError:
                return self._backend.process_frame(frame_bgr, timestamp_ms)
        raise RuntimeError("Tracker backend does not implement process_frame")

    def close(self) -> None:
        """Releases tracker backend."""
        self._backend.close()
