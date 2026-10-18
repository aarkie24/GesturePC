"""OpenCV implementation of CameraBackend port."""

from __future__ import annotations

import logging
import time
from typing import Optional, Tuple
import cv2
import numpy as np

logger = logging.getLogger(__name__)


class OpenCVCameraBackend:
    """CameraBackend implementation using cv2.VideoCapture."""

    def __init__(self) -> None:
        self._cap: Optional[cv2.VideoCapture] = None

    def open(
        self,
        index: int = 0,
        backend_name: str = "DSHOW",
        width: int = 640,
        height: int = 480,
        fps: int = 30,
    ) -> bool:
        """Opens camera at index using specified backend."""
        self.release()

        api = cv2.CAP_DSHOW if backend_name.upper() == "DSHOW" else cv2.CAP_MSMF
        logger.info("Opening camera index %d using backend %s (%dx%d @ %d fps)...", index, backend_name, width, height, fps)

        cap = cv2.VideoCapture(index, api)
        if not cap.isOpened() and backend_name.upper() == "DSHOW":
            # Automatic fallback to MSMF
            logger.warning("Failed to open camera with DSHOW; attempting fallback to MSMF...")
            cap = cv2.VideoCapture(index, cv2.CAP_MSMF)

        if not cap.isOpened():
            logger.error("Failed to open camera index %d with backends DSHOW and MSMF", index)
            return False

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)

        self._cap = cap
        return True

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray], int]:
        """Reads frame from camera. Returns (success, frame_bgr, timestamp_ns)."""
        if self._cap is None or not self._cap.isOpened():
            return False, None, time.monotonic_ns()

        t_ns = time.monotonic_ns()
        ret, frame = self._cap.read()
        return bool(ret), frame if ret else None, t_ns

    def is_opened(self) -> bool:
        """Returns True if the camera handle is active."""
        return self._cap is not None and self._cap.isOpened()

    def release(self) -> None:
        """Releases the camera device."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception as exc:
                logger.warning("Error releasing camera: %s", exc)
            finally:
                self._cap = None
