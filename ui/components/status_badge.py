"""Vibrant status badge component indicating current runtime mode."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from domain.enums import RuntimeMode


class StatusBadge(QLabel):
    """Visual indicator showing the active operational mode."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_mode(RuntimeMode.STOPPED)

    def set_mode(self, mode: RuntimeMode) -> None:
        if mode == RuntimeMode.STOPPED:
            style = (
                "background-color: #2b2b2b; color: #aaaaaa; font-weight: bold; "
                "font-size: 11px; padding: 4px 10px; border-radius: 4px; border: 1px solid #444444;"
            )
        elif mode == RuntimeMode.TEST:
            style = (
                "background-color: #0d47a1; color: #ffffff; font-weight: bold; "
                "font-size: 11px; padding: 4px 10px; border-radius: 4px; border: 1px solid #1976d2;"
            )
        elif mode == RuntimeMode.LIVE:
            style = (
                "background-color: #1b5e20; color: #ffffff; font-weight: bold; "
                "font-size: 11px; padding: 4px 10px; border-radius: 4px; border: 1px solid #388e3c;"
            )
        elif mode == RuntimeMode.RECORDING:
            style = (
                "background-color: #b71c1c; color: #ffffff; font-weight: bold; "
                "font-size: 11px; padding: 4px 10px; border-radius: 4px; border: 1px solid #d32f2f;"
            )
        else:
            style = "background-color: #333333; color: #ffffff; padding: 4px 10px; border-radius: 4px;"

        self.setText(f"● {mode.value}")
        self.setStyleSheet(style)
