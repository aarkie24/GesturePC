"""Win32 global emergency stop hotkey service using ctypes and RegisterHotKey."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Win32 Constants
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
HOTKEY_ID = 9001

user32 = ctypes.windll.user32


def parse_hotkey_chord(chord: str) -> tuple[int, int]:
    """Parses a string chord like 'Ctrl+Alt+Shift+X' into (fsModifiers, vkCode)."""
    parts = [p.strip().upper() for p in chord.split("+")]
    modifiers = MOD_NOREPEAT
    key_code = 0

    for p in parts:
        if p in ("CTRL", "CONTROL"):
            modifiers |= MOD_CONTROL
        elif p == "ALT":
            modifiers |= MOD_ALT
        elif p == "SHIFT":
            modifiers |= MOD_SHIFT
        elif p in ("WIN", "WINDOWS", "SUPER"):
            modifiers |= MOD_WIN
        elif len(p) == 1 and p.isalnum():
            key_code = ord(p)
        elif p.startswith("F") and p[1:].isdigit():
            f_num = int(p[1:])
            if 1 <= f_num <= 24:
                key_code = 0x70 + (f_num - 1)  # VK_F1 is 0x70
        elif p == "ESC":
            key_code = 0x1B
        elif p == "SPACE":
            key_code = 0x20
        else:
            raise ValueError(f"Unknown hotkey component: {p}")

    if key_code == 0:
        raise ValueError(f"No valid virtual key specified in chord: {chord}")

    return modifiers, key_code


class Win32GlobalHotkey:
    """Listens for an OS-wide emergency stop hotkey on a dedicated Win32 message pump thread."""

    def __init__(self, on_hotkey_pressed: Optional[Callable[[], None]] = None) -> None:
        self._callback = on_hotkey_pressed
        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None
        self._is_registered = False
        self._ready_event = threading.Event()
        self._registered_chord: Optional[str] = None
        self._lock = threading.Lock()

    def is_registered(self) -> bool:
        with self._lock:
            return self._is_registered

    def register(self, chord: str = "Ctrl+Alt+Shift+X") -> bool:
        """Starts background message pump thread and registers the hotkey."""
        with self._lock:
            if self._is_registered:
                self.unregister()

            self._registered_chord = chord
            self._ready_event.clear()
            self._thread = threading.Thread(
                target=self._pump_loop,
                name="Win32HotkeyPump",
                daemon=True,
            )
            self._thread.start()

        # Wait for registration confirmation from thread
        self._ready_event.wait(timeout=2.0)
        with self._lock:
            return self._is_registered

    def unregister(self) -> None:
        """Posts WM_QUIT to message thread and unregisters hotkey."""
        with self._lock:
            if self._thread_id is not None:
                user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            if self._thread is not None and self._thread.is_alive():
                self._thread.join(timeout=1.0)
            self._thread = None
            self._thread_id = None
            self._is_registered = False
            logger.info("Global hotkey unregistered.")

    def _pump_loop(self) -> None:
        """Dedicated message pump thread."""
        current_tid = ctypes.windll.kernel32.GetCurrentThreadId()
        self._thread_id = current_tid

        try:
            modifiers, vk = parse_hotkey_chord(self._registered_chord or "Ctrl+Alt+Shift+X")
        except Exception as exc:
            logger.error("Failed to parse hotkey chord %r: %s", self._registered_chord, exc)
            self._ready_event.set()
            return

        res = user32.RegisterHotKey(None, HOTKEY_ID, modifiers, vk)
        if not res:
            err = ctypes.get_last_error()
            logger.error("RegisterHotKey failed for '%s' (Win32 error: %d)", self._registered_chord, err)
            self._is_registered = False
            self._ready_event.set()
            return

        self._is_registered = True
        logger.info("Global stop hotkey registered successfully: %s", self._registered_chord)
        self._ready_event.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                logger.warning("Global emergency stop hotkey TRIGGERED by user!")
                if self._callback:
                    try:
                        self._callback()
                    except Exception as exc:
                        logger.exception("Error executing hotkey callback: %s", exc)
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        user32.UnregisterHotKey(None, HOTKEY_ID)
        self._is_registered = False
