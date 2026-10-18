"""Testing Studio Tab: Safely verify recognition with real-time frame diagnostics and event history."""

from __future__ import annotations

import logging
from typing import Callable, Optional
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from camera.frame_types import FramePacket
from domain.enums import RuntimeMode, TrackingStatus, TriggerState
from domain.models import FrameAnalysis, RecognitionEvent, TrackingResult
from services.runtime_controller import RuntimeController
from ui.components.camera_view import CameraView
from ui.components.status_badge import StatusBadge
from ui.qt_bridge import QtBridge

logger = logging.getLogger(__name__)


class TestingTab(QWidget):
    """Testing Studio Tab providing execution-free recognition evaluation and telemetry."""

    def __init__(
        self,
        runtime_controller: RuntimeController,
        qt_bridge: Optional[QtBridge] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._controller = runtime_controller
        self._qt_bridge = qt_bridge

        self._init_ui()
        self._connect_signals()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 1. Safety Banner
        banner = QFrame(self)
        banner.setStyleSheet(
            "background-color: #1e3a8a; border: 1px solid #3b82f6; border-radius: 6px; padding: 6px;"
        )
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(10, 4, 10, 4)

        lbl_shield = QLabel("🛡️ TEST MODE (SAFE): Recognition active — zero actions executed", banner)
        lbl_shield.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 13px;")
        banner_layout.addWidget(lbl_shield)

        self.btn_toggle_test = QPushButton("Start Test", banner)
        self.btn_toggle_test.setStyleSheet(
            "background-color: #2563eb; color: #ffffff; font-weight: bold; padding: 6px 16px; border-radius: 4px;"
        )
        self.btn_toggle_test.clicked.connect(self._on_toggle_test_clicked)
        banner_layout.addWidget(self.btn_toggle_test)

        layout.addWidget(banner)

        # 2. Main Content Splitter (Left: Camera + Overlay, Right: Diagnostics & Events)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Left Column: Camera View
        left_box = QWidget(splitter)
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.camera_view = CameraView(left_box)
        left_layout.addWidget(self.camera_view)
        splitter.addWidget(left_box)

        # Right Column: Diagnostics & Event History
        right_box = QWidget(splitter)
        right_layout = QVBoxLayout(right_box)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        # Telemetry Group
        telemetry_group = QGroupBox("Per-Frame Recognition Diagnostics", right_box)
        telemetry_layout = QGridLayout(telemetry_group)
        telemetry_layout.setSpacing(8)

        telemetry_layout.addWidget(QLabel("Hand Status:"), 0, 0)
        self.lbl_hand_status = QLabel("Standby", telemetry_group)
        self.lbl_hand_status.setStyleSheet("font-weight: bold;")
        telemetry_layout.addWidget(self.lbl_hand_status, 0, 1)

        telemetry_layout.addWidget(QLabel("Motion State:"), 0, 2)
        self.lbl_motion_state = QLabel("STATIONARY", telemetry_group)
        self.lbl_motion_state.setStyleSheet("font-weight: bold;")
        telemetry_layout.addWidget(self.lbl_motion_state, 0, 3)

        telemetry_layout.addWidget(QLabel("Hand Speed:"), 1, 0)
        self.lbl_hand_speed = QLabel("0.00 palm/s", telemetry_group)
        telemetry_layout.addWidget(self.lbl_hand_speed, 1, 1)

        telemetry_layout.addWidget(QLabel("Frame Outcome:"), 1, 2)
        self.lbl_outcome = QLabel("NO_HAND", telemetry_group)
        self.lbl_outcome.setStyleSheet("font-weight: bold; color: #f59e0b;")
        telemetry_layout.addWidget(self.lbl_outcome, 1, 3)

        telemetry_layout.addWidget(QLabel("Best Match:"), 2, 0)
        self.lbl_best_match = QLabel("None", telemetry_group)
        self.lbl_best_match.setStyleSheet("font-weight: bold; color: #10b981;")
        telemetry_layout.addWidget(self.lbl_best_match, 2, 1)

        telemetry_layout.addWidget(QLabel("Distance (MLD):"), 2, 2)
        self.lbl_best_dist = QLabel("N/A", telemetry_group)
        telemetry_layout.addWidget(self.lbl_best_dist, 2, 3)

        telemetry_layout.addWidget(QLabel("Second Match:"), 3, 0)
        self.lbl_second_match = QLabel("None", telemetry_group)
        telemetry_layout.addWidget(self.lbl_second_match, 3, 1)

        telemetry_layout.addWidget(QLabel("Margin Ratio:"), 3, 2)
        self.lbl_margin_ratio = QLabel("N/A", telemetry_group)
        telemetry_layout.addWidget(self.lbl_margin_ratio, 3, 3)

        # Trigger Validation Progress
        telemetry_layout.addWidget(QLabel("Trigger State:"), 4, 0)
        self.lbl_trigger_state = QLabel("IDLE", telemetry_group)
        self.lbl_trigger_state.setStyleSheet("font-weight: bold; color: #60a5fa;")
        telemetry_layout.addWidget(self.lbl_trigger_state, 4, 1)

        telemetry_layout.addWidget(QLabel("Stability Hold:"), 4, 2)
        self.stability_bar = QProgressBar(telemetry_group)
        self.stability_bar.setRange(0, 400)  # default stable_duration_ms
        self.stability_bar.setValue(0)
        self.stability_bar.setTextVisible(True)
        self.stability_bar.setFormat("%v / 400 ms")
        telemetry_layout.addWidget(self.stability_bar, 4, 3)

        right_layout.addWidget(telemetry_group)

        # Accepted Trigger Events Table
        events_group = QGroupBox("Accepted Trigger Events (Test History)", right_box)
        events_layout = QVBoxLayout(events_group)

        self.table_events = QTableWidget(events_group)
        self.table_events.setColumnCount(4)
        self.table_events.setHorizontalHeaderLabels(["Time (UTC)", "Gesture", "Distance", "Margin"])
        self.table_events.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        events_layout.addWidget(self.table_events)

        btn_clear = QPushButton("Clear History", events_group)
        btn_clear.clicked.connect(self.table_events.setRowCount)
        events_layout.addWidget(btn_clear, alignment=Qt.AlignmentFlag.AlignRight)

        right_layout.addWidget(events_group)
        splitter.addWidget(right_box)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter)

    def _connect_signals(self) -> None:
        if self._qt_bridge is not None:
            self._qt_bridge.frame_ready.connect(self._on_frame_ready)
            self._qt_bridge.frame_analysis_ready.connect(self._on_frame_analysis)
            self._qt_bridge.trigger_recognized.connect(self._on_trigger_recognized)
            self._qt_bridge.mode_changed.connect(self._on_mode_changed)

    def _on_toggle_test_clicked(self) -> None:
        mode = self._controller.current_mode
        if mode == RuntimeMode.TEST:
            self._controller.transition_to(RuntimeMode.STOPPED, "User stopped test mode")
        else:
            try:
                self._controller.transition_to(RuntimeMode.TEST, "User started test mode")
            except Exception as exc:
                logger.error("Could not start test mode: %s", exc)

    @Slot(object, object)
    def _on_frame_ready(self, packet: FramePacket, tracking: Optional[TrackingResult]) -> None:
        self.camera_view.update_frame(packet, tracking)

    @Slot(object)
    def _on_frame_analysis(self, analysis: FrameAnalysis) -> None:
        """Updates real-time telemetry diagnostics in UI."""
        self.lbl_hand_status.setText(analysis.hand_status.value)
        self.lbl_motion_state.setText(analysis.motion_state)
        self.lbl_hand_speed.setText(f"{analysis.hand_speed:.2f} palm/s")
        self.lbl_outcome.setText(analysis.outcome)

        if analysis.best_gesture_id is not None:
            self.lbl_best_match.setText(f"ID #{analysis.best_gesture_id}")
            self.lbl_best_dist.setText(f"{analysis.best_distance:.3f} (thresh={analysis.threshold:.3f})")
        else:
            self.lbl_best_match.setText("None")
            self.lbl_best_dist.setText("N/A")

        if analysis.second_gesture_id is not None:
            self.lbl_second_match.setText(f"ID #{analysis.second_gesture_id}")
            self.lbl_margin_ratio.setText(f"{analysis.margin_ratio:.2f}")
        else:
            self.lbl_second_match.setText("None")
            self.lbl_margin_ratio.setText("N/A")

        self.lbl_trigger_state.setText(analysis.trigger_state.value)
        self.stability_bar.setValue(min(400, analysis.accumulated_ms))

    @Slot(object)
    def _on_trigger_recognized(self, event: RecognitionEvent) -> None:
        """Adds accepted trigger event to history table."""
        row = self.table_events.rowCount()
        self.table_events.insertRow(row)

        time_str = event.timestamp_utc.split("T")[-1][:8] if "T" in event.timestamp_utc else event.timestamp_utc
        self.table_events.setItem(row, 0, QTableWidgetItem(time_str))
        self.table_events.setItem(row, 1, QTableWidgetItem(f"{event.gesture_name} ({event.hand.value})"))
        self.table_events.setItem(row, 2, QTableWidgetItem(f"{event.distance:.3f}"))
        self.table_events.setItem(row, 3, QTableWidgetItem(f"{event.margin_ratio:.2f}"))
        self.table_events.scrollToBottom()

    @Slot(str, str)
    def _on_mode_changed(self, mode_str: str, reason: str) -> None:
        if mode_str == RuntimeMode.TEST.value:
            self.btn_toggle_test.setText("Stop Test Mode")
            self.btn_toggle_test.setStyleSheet("background-color: #dc2626; color: white; font-weight: bold; padding: 6px 16px;")
        else:
            self.btn_toggle_test.setText("Start Test")
            self.btn_toggle_test.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold; padding: 6px 16px;")
            self.camera_view.clear()
            self.stability_bar.setValue(0)
