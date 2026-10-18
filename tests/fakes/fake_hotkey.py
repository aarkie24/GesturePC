"""Fake GlobalHotkeyService for testing emergency stop triggers."""

from __future__ import annotations

from typing import Callable, Optional


class FakeHotkeyService:
    """Simulates system-wide hotkey registration and user press events."""

    def __init__(self, callback: Optional[Callable[[], None]] = None) -> None:
        self.callback = callback
        self._registered = False
        self._chord: Optional[str] = None

    def register(self, chord: str = "Ctrl+Alt+Shift+X") -> bool:
        self._registered = True
        self._chord = chord
        return True

    def unregister(self) -> None:
        self._registered = False
        self._chord = None

    def is_registered(self) -> bool:
        return self._registered

    def simulate_press(self) -> None:
        """Simulates user pressing the global emergency stop chord."""
        if self._registered and self.callback:
            self.callback()
