"""System tray icon with mode display and emergency stop action."""

from __future__ import annotations

from typing import Callable, Optional
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from app.constants import APP_DISPLAY_NAME
from domain.enums import RuntimeMode


def create_tray_pixmap(color_hex: str = "#d32f2f") -> QPixmap:
    """Generates an in-memory high-DPI icon pixmap with a colored badge dot."""
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color_hex))
    painter.setPen(QColor("#ffffff"))
    painter.drawEllipse(4, 4, 24, 24)
    painter.end()
    return pixmap


class SystemTray(QSystemTrayIcon):
    """System tray integration providing instant stop from outside the main window."""

    def __init__(
        self,
        on_show_window: Callable[[], None],
        on_emergency_stop: Callable[[], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._on_show_window = on_show_window
        self._on_emergency_stop = on_emergency_stop

        self.setIcon(QIcon(create_tray_pixmap("#2b2b2b")))
        self.setToolTip(f"{APP_DISPLAY_NAME} — Mode: STOPPED")
        self._init_menu()

    def _init_menu(self) -> None:
        menu = QMenu()

        self._mode_action = QAction("Mode: STOPPED", menu)
        self._mode_action.setEnabled(False)
        menu.addAction(self._mode_action)
        menu.addSeparator()

        show_act = QAction("Open Gesture PC", menu)
        show_act.triggered.connect(self._on_show_window)
        menu.addAction(show_act)

        stop_act = QAction("STOP (Ctrl+Alt+Shift+X)", menu)
        stop_act.triggered.connect(self._on_emergency_stop)
        menu.addAction(stop_act)

        menu.addSeparator()
        quit_act = QAction("Exit", menu)
        quit_act.triggered.connect(lambda: self.parent().close() if self.parent() else None)
        menu.addAction(quit_act)

        self.setContextMenu(menu)

    def set_mode(self, mode: RuntimeMode) -> None:
        """Updates tooltip, icon color, and menu text to match mode."""
        self._mode_action.setText(f"Mode: {mode.value}")
        self.setToolTip(f"{APP_DISPLAY_NAME} — Mode: {mode.value}")

        if mode == RuntimeMode.LIVE:
            self.setIcon(QIcon(create_tray_pixmap("#4caf50")))
        elif mode == RuntimeMode.TEST:
            self.setIcon(QIcon(create_tray_pixmap("#2196f3")))
        elif mode == RuntimeMode.RECORDING:
            self.setIcon(QIcon(create_tray_pixmap("#f44336")))
        else:
            self.setIcon(QIcon(create_tray_pixmap("#757575")))
