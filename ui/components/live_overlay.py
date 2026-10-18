"""Always-on-top floating Stop overlay shown during LIVE automation."""

from __future__ import annotations

from typing import Callable, Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)


class LiveOverlay(QWidget):
    """Small always-on-top floating toolbar displayed exclusively during LIVE mode."""

    def __init__(
        self,
        on_stop_clicked: Callable[[], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool,
        )
        self._on_stop_clicked = on_stop_clicked
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        container = QWidget(self)
        container.setStyleSheet(
            "background-color: rgba(20, 20, 20, 0.90); "
            "border: 2px solid #d32f2f; "
            "border-radius: 8px;"
        )
        c_layout = QHBoxLayout(container)
        c_layout.setContentsMargins(10, 6, 10, 6)
        c_layout.setSpacing(12)

        dot_label = QLabel("● LIVE", container)
        dot_label.setStyleSheet("color: #4caf50; font-weight: bold; font-size: 12px;")
        c_layout.addWidget(dot_label)

        stop_btn = QPushButton("STOP (Ctrl+Alt+Shift+X)", container)
        stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        stop_btn.setStyleSheet(
            "background-color: #d32f2f; color: #ffffff; font-weight: bold; "
            "font-size: 11px; padding: 6px 14px; border-radius: 4px; border: none;"
        )
        stop_btn.clicked.connect(self._on_stop_clicked)
        c_layout.addWidget(stop_btn)

        layout.addWidget(container)
        self.adjustSize()

    def show_in_corner(self) -> None:
        """Positions the overlay in the top-right corner of the primary screen and displays it."""
        screen = QApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            x = geom.right() - self.width() - 24
            y = geom.top() + 24
            self.move(x, y)
        self.show()
