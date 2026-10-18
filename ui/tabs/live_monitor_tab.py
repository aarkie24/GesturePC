"""Live Monitor Tab: Real-time camera feed, skeleton overlay, and runtime mode controls."""

from __future__ import annotations

from typing import Callable, Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from domain.enums import RuntimeMode
from ui.components.camera_view import CameraView
from ui.components.status_badge import StatusBadge


class LiveMonitorTab(QWidget):
    """Primary dashboard tab for camera monitoring and operational mode controls."""

    def __init__(
        self,
        on_start_test: Callable[[], None],
        on_start_live: Callable[[], None],
        on_emergency_stop: Callable[[], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._on_start_test = on_start_test
        self._on_start_live = on_start_live
        self._on_emergency_stop = on_emergency_stop

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)

        # Left Column: Camera View
        left_box = QWidget(self)
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.camera_view = CameraView(left_box)
        left_layout.addWidget(self.camera_view, stretch=1)

        main_layout.addWidget(left_box, stretch=3)

        # Right Column: Controls & Diagnostics
        right_box = QWidget(self)
        right_layout = QVBoxLayout(right_box)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(16)

        # 1. Mode Status Group
        mode_group = QGroupBox("Runtime Status", right_box)
        mode_layout = QVBoxLayout(mode_group)
        self.status_badge = StatusBadge(mode_group)
        mode_layout.addWidget(self.status_badge)

        self.hotkey_hint = QLabel("Emergency Stop Hotkey: Ctrl+Alt+Shift+X", mode_group)
        self.hotkey_hint.setStyleSheet("color: #888888; font-size: 11px;")
        mode_layout.addWidget(self.hotkey_hint)
        right_layout.addWidget(mode_group)

        # 2. Controls Group
        ctrl_group = QGroupBox("Mode Controls", right_box)
        ctrl_layout = QVBoxLayout(ctrl_group)
        ctrl_layout.setSpacing(10)

        self.btn_test = QPushButton("Start Test Mode (Safe)", ctrl_group)
        self.btn_test.setStyleSheet(
            "background-color: #0d47a1; color: #ffffff; font-weight: bold; "
            "padding: 10px; border-radius: 6px; font-size: 13px;"
        )
        self.btn_test.clicked.connect(self._on_start_test)
        ctrl_layout.addWidget(self.btn_test)

        self.btn_live = QPushButton("Start Live Automation", ctrl_group)
        self.btn_live.setStyleSheet(
            "background-color: #1b5e20; color: #ffffff; font-weight: bold; "
            "padding: 10px; border-radius: 6px; font-size: 13px;"
        )
        self.btn_live.clicked.connect(self._on_start_live)
        ctrl_layout.addWidget(self.btn_live)

        self.btn_stop = QPushButton("EMERGENCY STOP", ctrl_group)
        self.btn_stop.setStyleSheet(
            "background-color: #b71c1c; color: #ffffff; font-weight: bold; "
            "padding: 10px; border-radius: 6px; font-size: 13px;"
        )
        self.btn_stop.clicked.connect(self._on_emergency_stop)
        ctrl_layout.addWidget(self.btn_stop)

        right_layout.addWidget(ctrl_group)

        # 3. Live Diagnostics
        diag_group = QGroupBox("Pipeline Diagnostics", right_box)
        diag_layout = QGridLayout(diag_group)

        diag_layout.addWidget(QLabel("Camera FPS:"), 0, 0)
        self.lbl_fps = QLabel("0.0", diag_group)
        self.lbl_fps.setStyleSheet("font-weight: bold;")
        diag_layout.addWidget(self.lbl_fps, 0, 1)

        diag_layout.addWidget(QLabel("Hand Tracking:"), 1, 0)
        self.lbl_tracking = QLabel("Idle", diag_group)
        self.lbl_tracking.setStyleSheet("font-weight: bold;")
        diag_layout.addWidget(self.lbl_tracking, 1, 1)

        diag_layout.addWidget(QLabel("Active Candidate:"), 2, 0)
        self.lbl_candidate = QLabel("None", diag_group)
        self.lbl_candidate.setStyleSheet("font-weight: bold;")
        diag_layout.addWidget(self.lbl_candidate, 2, 1)

        right_layout.addWidget(diag_group)
        right_layout.addStretch()

        main_layout.addWidget(right_box, stretch=1)

    def set_mode(self, mode: RuntimeMode) -> None:
        """Updates button enabled states and mode badge according to state machine."""
        self.status_badge.set_mode(mode)
        if mode == RuntimeMode.STOPPED:
            self.btn_test.setEnabled(True)
            self.btn_live.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.lbl_tracking.setText("Camera Off")
            self.camera_view.clear()
        elif mode == RuntimeMode.TEST:
            self.btn_test.setEnabled(False)
            self.btn_live.setEnabled(True)
            self.btn_stop.setEnabled(True)
            self.btn_stop.setText("Stop Test Mode")
        elif mode == RuntimeMode.LIVE:
            self.btn_test.setEnabled(False)
            self.btn_live.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.btn_stop.setText("EMERGENCY STOP")
        elif mode == RuntimeMode.RECORDING:
            self.btn_test.setEnabled(False)
            self.btn_live.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.btn_stop.setText("Cancel Recording")
