"""Main application entry point for Gesture PC."""

from __future__ import annotations

import logging
import msvcrt
import os
from pathlib import Path
import sys
from typing import Optional

from PySide6.QtWidgets import QApplication, QMessageBox

from app.application import Application
from app.constants import APP_DISPLAY_NAME
from app.logging_config import configure_logging
from app.paths import get_lock_file_path

logger = logging.getLogger("main")


class SingleInstanceLock:
    """Acquires a non-blocking Win32 file lock to enforce a single running application instance."""

    def __init__(self, lock_file_path: Path) -> None:
        self.lock_file_path = lock_file_path
        self._file_handle: Optional[int] = None

    def acquire(self) -> bool:
        try:
            self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_handle = os.open(str(self.lock_file_path), os.O_RDWR | os.O_CREAT, 0o666)
            msvcrt.locking(self._file_handle, msvcrt.LK_NBLCK, 1)
            return True
        except (OSError, IOError):
            return False

    def release(self) -> None:
        if self._file_handle is not None:
            try:
                msvcrt.locking(self._file_handle, msvcrt.LK_UNLCK, 1)
                os.close(self._file_handle)
            except (OSError, IOError):
                pass
            self._file_handle = None


def main() -> int:
    # 1. Logging configuration
    configure_logging(verbose=False)
    logger.info("Starting %s...", APP_DISPLAY_NAME)

    # 2. Acquire single instance lock
    lock = SingleInstanceLock(get_lock_file_path())
    if not lock.acquire():
        logger.warning("Another instance of %s is already running. Exiting.", APP_DISPLAY_NAME)
        # Construct minimal Qt app to show message box if interactive
        qt_app = QApplication(sys.argv)
        QMessageBox.warning(
            None,
            APP_DISPLAY_NAME,
            f"Another instance of {APP_DISPLAY_NAME} is already running.\nOnly one instance may run at a time.",
        )
        return 1

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName(APP_DISPLAY_NAME)

    try:
        # 3. Composition root build
        app_instance = Application.build()
        app_instance.main_window.show()
        logger.info("%s initialized and running in mode STOPPED.", APP_DISPLAY_NAME)

        # 4. Qt event loop
        exit_code = qt_app.exec()
        app_instance.shutdown()
        return exit_code
    except Exception as exc:
        logger.critical("Fatal exception during application startup: %s", exc, exc_info=True)
        return 2
    finally:
        lock.release()
        logger.info("%s process exited cleanly.", APP_DISPLAY_NAME)


if __name__ == "__main__":
    sys.exit(main())
