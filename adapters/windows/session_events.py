"""Windows session lock, disconnect, and power sleep notification adapter."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# WTS & Win32 Constants
WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_LOGOFF = 0x6
NOTIFY_FOR_THIS_SESSION = 0

wtsapi32 = ctypes.windll.wtsapi32
user32 = ctypes.windll.user32


class Win32SessionEventSource:
    """Listens for Windows session lock and logoff events on a dedicated message thread."""

    def __init__(self, on_session_locked: Optional[Callable[[], None]] = None) -> None:
        self._callback = on_session_locked
        self._thread: Optional[threading.Thread] = None
        self._hwnd: Optional[int] = None
        self._is_running = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._is_running:
                return
            self._is_running = True
            self._thread = threading.Thread(
                target=self._window_thread,
                name="Win32SessionWatcher",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            if not self._is_running:
                return
            self._is_running = False
            if self._hwnd:
                user32.PostMessageW(self._hwnd, 0x0010, 0, 0)  # WM_CLOSE
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=1.0)
            self._thread = None
            self._hwnd = None

    def _window_thread(self) -> None:
        """Creates a hidden window to receive WM_WTSSESSION_CHANGE."""
        LRESULT = ctypes.c_ssize_t
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = LRESULT
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        def py_wnd_proc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
            if msg == WM_WTSSESSION_CHANGE:
                if wparam in (WTS_SESSION_LOCK, WTS_SESSION_LOGOFF):
                    logger.warning("Windows session locked or logged off (wparam=%d)!", wparam)
                    if self._callback:
                        try:
                            self._callback()
                        except Exception as exc:
                            logger.exception("Error in session lock callback: %s", exc)
                return 0
            elif msg == 0x0010:  # WM_CLOSE
                user32.DestroyWindow(hwnd)
                return 0
            elif msg == 0x0002:  # WM_DESTROY
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        wnd_proc_callback = WNDPROC(py_wnd_proc)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        class_name = f"GesturePC_SessionWatcher_{threading.get_ident()}"
        wc = WNDCLASS()
        wc.lpfnWndProc = wnd_proc_callback
        wc.lpszClassName = class_name
        wc.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)

        reg = user32.RegisterClassW(ctypes.byref(wc))
        if not reg:
            logger.warning("Failed to register window class for session watcher.")
            return

        hwnd = user32.CreateWindowExW(
            0,
            class_name,
            "SessionWatcher",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            wc.hInstance,
            None,
        )
        self._hwnd = hwnd

        # Register session notifications
        try:
            wtsapi32.WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION)
            logger.info("WTSRegisterSessionNotification active on window %d.", hwnd)
        except Exception as exc:
            logger.warning("Could not register session notification: %s", exc)

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        try:
            wtsapi32.WTSUnRegisterSessionNotification(hwnd)
        except Exception:
            pass
