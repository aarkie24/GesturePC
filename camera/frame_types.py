"""Frame representations and inter-thread mailboxes for video capture."""

from __future__ import annotations

from dataclasses import dataclass
import queue
import threading
from typing import Optional
import numpy as np


@dataclass(frozen=True)
class FramePacket:
    """Represents a single captured video frame."""
    frame_id: int
    capture_ts_ns: int
    frame_bgr: np.ndarray  # (H, W, 3) uint8 BGR array
    aspect_ratio: float

    def __post_init__(self) -> None:
        if self.frame_bgr.flags.writeable:
            self.frame_bgr.setflags(write=False)


class LatestFrameMailbox:
    """Single-slot thread-safe mailbox where newest frame replaces older unprocessed frame."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._slot: Optional[FramePacket] = None
        self._version: int = 0

    def put(self, packet: FramePacket) -> None:
        """Stores the latest frame, overwriting any previous unconsumed frame."""
        with self._cond:
            self._slot = packet
            self._version += 1
            self._cond.notify_all()

    def get(self, timeout_sec: float = 0.1) -> Optional[FramePacket]:
        """Waits for and retrieves the latest frame. Consuming leaves slot empty until next frame."""
        with self._cond:
            if self._slot is None:
                self._cond.wait(timeout=timeout_sec)
            packet = self._slot
            self._slot = None
            return packet

    def clear(self) -> None:
        """Empties the mailbox."""
        with self._cond:
            self._slot = None


class LosslessFrameQueue:
    """Bounded FIFO queue used exclusively during gesture recording."""

    def __init__(self, maxsize: int = 300) -> None:
        self._queue: queue.Queue[FramePacket] = queue.Queue(maxsize=maxsize)

    def put(self, packet: FramePacket) -> bool:
        """Pushes frame into recording queue. Returns False if full (overflow)."""
        try:
            self._queue.put_nowait(packet)
            return True
        except queue.Full:
            return False

    def get(self, timeout_sec: float = 0.1) -> Optional[FramePacket]:
        """Pulls frame from queue."""
        try:
            return self._queue.get(timeout=timeout_sec)
        except queue.Empty:
            return None

    def clear(self) -> None:
        """Empties the queue."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    @property
    def qsize(self) -> int:
        return self._queue.qsize()
