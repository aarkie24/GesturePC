"""Execution safety gate enforcing epoch-based admissions and O(1) instantaneous cancellation."""

from __future__ import annotations

import logging
import threading
from typing import Optional
import uuid

from domain.models import Admission

logger = logging.getLogger(__name__)


class CancellationToken:
    """Thread-safe cooperative cancellation token checked before every action."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout_sec: float) -> bool:
        """Waits for cancellation or timeout. Returns True if cancelled, False if timed out."""
        return self._event.wait(timeout=timeout_sec)


class ExecutionGate:
    """Safety boundary controlling workflow admission and instantaneous shutdown."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._is_open = False
        self._epoch = 0
        self._token = CancellationToken()
        self._close_reason: Optional[str] = "INITIAL"

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._is_open

    @property
    def epoch(self) -> int:
        with self._lock:
            return self._epoch

    @property
    def close_reason(self) -> Optional[str]:
        with self._lock:
            return self._close_reason

    def open_for_live(self) -> int:
        """Opens the gate for Live automation, invalidating any previous admissions."""
        with self._lock:
            self._epoch += 1
            self._token = CancellationToken()
            self._is_open = True
            self._close_reason = None
            logger.info("ExecutionGate OPENED for LIVE mode (epoch=%d)", self._epoch)
            return self._epoch

    def close(self, reason: str = "STOPPED") -> int:
        """Immediately closes gate, increments epoch, and signals cancellation (O(1))."""
        with self._lock:
            self._is_open = False
            self._epoch += 1
            self._token.cancel()
            self._close_reason = reason
            logger.info("ExecutionGate CLOSED (epoch=%d, reason=%s)", self._epoch, reason)
            return self._epoch

    def admit(self) -> Optional[Admission]:
        """Issues an admission ticket if gate is currently open."""
        with self._lock:
            if not self._is_open:
                return None
            return Admission(epoch=self._epoch, token=str(uuid.uuid4()))

    def is_current(self, admission: Optional[Admission]) -> bool:
        """Verifies that an admission ticket is still valid and uncancelled."""
        if admission is None:
            return False
        with self._lock:
            if not self._is_open:
                return False
            if admission.epoch != self._epoch:
                return False
            if self._token.is_cancelled:
                return False
            return True

    def get_cancellation_token(self) -> CancellationToken:
        """Returns the active cancellation token."""
        with self._lock:
            return self._token
