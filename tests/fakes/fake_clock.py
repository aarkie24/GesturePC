"""Fake clock for deterministic time manipulation in tests."""

from __future__ import annotations


class FakeClock:
    """Deterministic, manually advanceable clock conforming to Clock protocol."""

    def __init__(self, initial_time: float = 1000.0) -> None:
        self._current_time = initial_time

    def time(self) -> float:
        return self._current_time

    def monotonic(self) -> float:
        return self._current_time

    def monotonic_ns(self) -> int:
        return int(self._current_time * 1_000_000_000)

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        """Advances clock by specified seconds."""
        if seconds < 0:
            raise ValueError("Time cannot move backward")
        self._current_time += seconds
