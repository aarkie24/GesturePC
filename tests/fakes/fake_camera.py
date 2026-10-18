"""Fake CameraBackend for deterministic tests without physical hardware."""

from __future__ import annotations

import time
from typing import Optional, Tuple
import numpy as np


class FakeCameraBackend:
    """Simulates camera device delivering synthetic frames."""

    def __init__(self, frame_size: Tuple[int, int] = (640, 480)) -> None:
        self.frame_size = frame_size
        self._is_opened = False
        self._frame_count = 0

    def open(
        self,
        index: int = 0,
        backend_name: str = "DSHOW",
        width: int = 640,
        height: int = 480,
        fps: int = 30,
    ) -> bool:
        self._is_opened = True
        self.frame_size = (width, height)
        return True

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray], int]:
        if not self._is_opened:
            return False, None, time.monotonic_ns()

        self._frame_count += 1
        w, h = self.frame_size
        frame = np.full((h, w, 3), fill_value=(self._frame_count % 255), dtype=np.uint8)
        return True, frame, time.monotonic_ns()

    def is_opened(self) -> bool:
        return self._is_opened

    def release(self) -> None:
        self._is_opened = False
