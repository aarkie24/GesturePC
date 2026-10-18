"""Gesture Studio Tab: Record, review, calibrate, and manage static and dynamic gestures."""

from __future__ import annotations

import logging
from typing import Callable, List, Optional, Tuple
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from camera.frame_types import FramePacket
from domain.enums import GestureType, Hand, RuntimeMode, TrackingStatus
from domain.models import Gesture, GestureSample, RecordingResult, TrackingResult
from gestures.recorder import (
    DynamicGestureRecorder,
    DynamicRecorderProgress,
    RecorderProgress,
    RecorderState,
    StaticGestureRecorder,
)
from services.gesture_service import GestureService
from services.runtime_controller import RuntimeController
from ui.components.camera_view import CameraView
from ui.components.status_badge import StatusBadge
from ui.qt_bridge import QtBridge

logger = logging.getLogger(__name__)


class GestureStudioTab(QWidget):
    """Gesture Studio Tab providing gesture registration, sample capture, and management."""

    def __init__(
        self,
        gesture_service: GestureService,
        runtime_controller: RuntimeController,
        qt_bridge: Optional[QtBridge] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._gesture_service = gesture_service
        self._controller = runtime_controller
        self._qt_bridge = qt_bridge

        self._recorder: Optional[StaticGestureRecorder] = None
        self._dynamic_recorder: Optional[DynamicGestureRecorder] = None
        self._current_recording_result: Optional[RecordingResult] = None
        self._pending_collisions: List[Tuple[str, float]] = []
        self._editing_gesture_id: Optional[int] = None

        self._init_ui()
        self._connect_signals()
        self.refresh_gestures_list()

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # -------------------------------------------------------------
        # LEFT PANEL: Registered Gestures List & Selected Details
        # -------------------------------------------------------------
        left_widget = QWidget(splitter)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        list_group = QGroupBox("Registered Gestures", left_widget)
        list_layout = QVBoxLayout(list_group)

        self.table_gestures = QTableWidget(list_group)
        self.table_gestures.setColumnCount(4)
        self.table_gestures.setHorizontalHeaderLabels(["Name", "Type", "Hand", "Status"])
        self.table_gestures.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_gestures.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_gestures.itemSelectionChanged.connect(self._on_gesture_selected)
        list_layout.addWidget(self.table_gestures)

        # Details and Actions for Selected Gesture
        details_box = QGroupBox("Gesture Details & Tuning", left_widget)
        details_layout = QGridLayout(details_box)

        details_layout.addWidget(QLabel("Name:"), 0, 0)
        self.txt_selected_name = QLineEdit(details_box)
        details_layout.addWidget(self.txt_selected_name, 0, 1)

        details_layout.addWidget(QLabel("Sensitivity Scale:"), 1, 0)
        self.slider_sensitivity = QSlider(Qt.Orientation.Horizontal, details_box)
        self.slider_sensitivity.setRange(50, 150)
        self.slider_sensitivity.setValue(100)
        self.slider_sensitivity.valueChanged.connect(self._on_sensitivity_slider_changed)
        details_layout.addWidget(self.slider_sensitivity, 1, 1)

        self.lbl_sensitivity_val = QLabel("1.00x (Normal)", details_box)
        details_layout.addWidget(self.lbl_sensitivity_val, 1, 2)

        btn_bar = QHBoxLayout()
        self.btn_update = QPushButton("Update Gesture", details_box)
        self.btn_update.clicked.connect(self._on_update_gesture_clicked)
        btn_bar.addWidget(self.btn_update)

        self.btn_delete = QPushButton("Delete", details_box)
        self.btn_delete.setStyleSheet("background-color: #7f1d1d; color: white;")
        self.btn_delete.clicked.connect(self._on_delete_gesture_clicked)
        btn_bar.addWidget(self.btn_delete)
        details_layout.addLayout(btn_bar, 2, 0, 1, 3)

        list_layout.addWidget(details_box)
        left_layout.addWidget(list_group)
        splitter.addWidget(left_widget)

        # -------------------------------------------------------------
        # RIGHT PANEL: Recording & Calibration View
        # -------------------------------------------------------------
        right_widget = QWidget(splitter)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self.rec_group = QGroupBox("Record New Static Pose", right_widget)
        rec_group = self.rec_group
        rec_layout = QVBoxLayout(self.rec_group)

        # Config Row
        cfg_row = QHBoxLayout()
        cfg_row.addWidget(QLabel("Type:"))
        self.combo_type = QComboBox(self.rec_group)
        self.combo_type.addItems(["Static Pose", "Dynamic Movement"])
        self.combo_type.currentIndexChanged.connect(self._on_type_changed)
        cfg_row.addWidget(self.combo_type)

        cfg_row.addWidget(QLabel("Tracked Hand:"))
        self.combo_hand = QComboBox(self.rec_group)
        self.combo_hand.addItems(["Right Hand", "Left Hand", "Either Hand"])
        cfg_row.addWidget(self.combo_hand)

        self.btn_start_record = QPushButton("Start Recording", rec_group)
        self.btn_start_record.setStyleSheet(
            "background-color: #1e40af; color: white; font-weight: bold; padding: 6px 14px;"
        )
        self.btn_start_record.clicked.connect(self._on_start_recording_clicked)
        cfg_row.addWidget(self.btn_start_record)

        self.btn_cancel_record = QPushButton("Cancel", rec_group)
        self.btn_cancel_record.setEnabled(False)
        self.btn_cancel_record.clicked.connect(self._on_cancel_recording_clicked)
        cfg_row.addWidget(self.btn_cancel_record)

        rec_layout.addLayout(cfg_row)

        # Live Camera View for Recording
        self.camera_view = CameraView(rec_group)
        rec_layout.addWidget(self.camera_view, stretch=1)

        # Countdown & Progress Overlay
        prog_box = QFrame(rec_group)
        prog_layout = QVBoxLayout(prog_box)

        self.lbl_status = QLabel("Ready. Position hand and click 'Start Recording'.", prog_box)
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setStyleSheet("font-size: 14px; font-weight: bold; color: #60a5fa;")
        prog_layout.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar(prog_box)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        prog_layout.addWidget(self.progress_bar)

        rec_layout.addWidget(prog_box)

        # Save and Collision Confirmation Box
        self.save_box = QGroupBox("Save Recorded Gesture", rec_group)
        save_layout = QGridLayout(self.save_box)

        save_layout.addWidget(QLabel("Gesture Name:"), 0, 0)
        self.txt_gesture_name = QLineEdit(self.save_box)
        self.txt_gesture_name.setPlaceholderText("e.g. Open Palm, Thumbs Up, Fist...")
        save_layout.addWidget(self.txt_gesture_name, 0, 1)

        self.lbl_collision_warning = QLabel("", self.save_box)
        self.lbl_collision_warning.setStyleSheet("color: #ef4444; font-weight: bold;")
        self.lbl_collision_warning.setWordWrap(True)
        save_layout.addWidget(self.lbl_collision_warning, 1, 0, 1, 2)

        save_btn_layout = QHBoxLayout()
        self.btn_save_gesture = QPushButton("Save Gesture", self.save_box)
        self.btn_save_gesture.setStyleSheet(
            "background-color: #166534; color: white; font-weight: bold; padding: 6px 14px;"
        )
        self.btn_save_gesture.clicked.connect(lambda: self._on_save_gesture_clicked(allow_collision=False))
        save_btn_layout.addWidget(self.btn_save_gesture)

        self.btn_save_anyway = QPushButton("Save Anyway (Override Collision)", self.save_box)
        self.btn_save_anyway.setStyleSheet(
            "background-color: #9a3412; color: white; font-weight: bold; padding: 6px 14px;"
        )
        self.btn_save_anyway.setVisible(False)
        self.btn_save_anyway.clicked.connect(lambda: self._on_save_gesture_clicked(allow_collision=True))
        save_btn_layout.addWidget(self.btn_save_anyway)

        save_layout.addLayout(save_btn_layout, 2, 0, 1, 2)
        self.save_box.setEnabled(False)
        rec_layout.addWidget(self.save_box)

        right_layout.addWidget(rec_group)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        layout.addWidget(splitter)

    def _connect_signals(self) -> None:
        if self._qt_bridge is not None:
            self._qt_bridge.frame_ready.connect(self._on_frame_ready)
            self._qt_bridge.mode_changed.connect(self._on_mode_changed)

    def refresh_gestures_list(self) -> None:
        """Reloads registered gestures from GestureService into table."""
        gestures = self._gesture_service.list_gestures()
        self.table_gestures.setRowCount(len(gestures))

        for row, g in enumerate(gestures):
            item_name = QTableWidgetItem(g.name)
            item_name.setData(Qt.ItemDataRole.UserRole, g.id)
            self.table_gestures.setItem(row, 0, item_name)
            self.table_gestures.setItem(row, 1, QTableWidgetItem(g.gesture_type.value))
            self.table_gestures.setItem(row, 2, QTableWidgetItem(g.hand.value))
            status_text = "Enabled" if g.enabled else "Disabled"
            self.table_gestures.setItem(row, 3, QTableWidgetItem(status_text))

    def _on_gesture_selected(self) -> None:
        selected_rows = self.table_gestures.selectedItems()
        if not selected_rows:
            self._editing_gesture_id = None
            return

        row = selected_rows[0].row()
        item = self.table_gestures.item(row, 0)
        if item is None:
            return

        gesture_id = item.data(Qt.ItemDataRole.UserRole)
        self._editing_gesture_id = gesture_id
        g = self._gesture_service.get_gesture(gesture_id)
        if g is not None:
            self.txt_selected_name.setText(g.name)
            slider_val = int(g.threshold_scale * 100)
            self.slider_sensitivity.setValue(slider_val)
            self.lbl_sensitivity_val.setText(f"{g.threshold_scale:.2f}x")

    def _on_sensitivity_slider_changed(self, value: int) -> None:
        scale = value / 100.0
        self.lbl_sensitivity_val.setText(f"{scale:.2f}x")

    def _on_update_gesture_clicked(self) -> None:
        if self._editing_gesture_id is None:
            return
        new_name = self.txt_selected_name.text().strip()
        new_scale = self.slider_sensitivity.value() / 100.0

        try:
            self._gesture_service.update_gesture(
                gesture_id=self._editing_gesture_id,
                name=new_name,
                threshold_scale=new_scale,
            )
            self.refresh_gestures_list()
            QMessageBox.information(self, "Updated", f"Gesture '{new_name}' updated successfully.")
        except Exception as exc:
            QMessageBox.warning(self, "Update Error", str(exc))

    def _on_delete_gesture_clicked(self) -> None:
        if self._editing_gesture_id is None:
            return
        g = self._gesture_service.get_gesture(self._editing_gesture_id)
        if g is None:
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete gesture '{g.name}'?\nThis will also delete associated workflows.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self._gesture_service.delete_gesture(self._editing_gesture_id)
            self.refresh_gestures_list()
            self.txt_selected_name.clear()
            self._editing_gesture_id = None

    def _on_start_recording_clicked(self) -> None:
        hand_choice = self.combo_hand.currentText()
        if "Right" in hand_choice:
            target_hand = Hand.RIGHT
        elif "Left" in hand_choice:
            target_hand = Hand.LEFT
    def _on_type_changed(self) -> None:
        if self.combo_type.currentText() == "Dynamic Movement":
            self.rec_group.setTitle("Record Dynamic Movement (3 Repetitions)")
            self.txt_gesture_name.setPlaceholderText("e.g. Swipe Right, Wave, Circle...")
            self.lbl_status.setText("Ready. Click 'Start Recording' and perform 3 repetitions.")
        else:
            self.rec_group.setTitle("Record Static Pose")
            self.txt_gesture_name.setPlaceholderText("e.g. Open Palm, Thumbs Up, Fist...")
            self.lbl_status.setText("Ready. Position hand and click 'Start Recording'.")

    def _on_start_recording_clicked(self) -> None:
        hand_choice = self.combo_hand.currentText()
        if "Right" in hand_choice:
            target_hand = Hand.RIGHT
        elif "Left" in hand_choice:
            target_hand = Hand.LEFT
        else:
            target_hand = Hand.EITHER

        # Transition controller to RECORDING
        try:
            self._controller.transition_to(RuntimeMode.RECORDING, "User started gesture recording")
        except Exception as exc:
            QMessageBox.warning(self, "Cannot Record", f"Could not enter recording mode:\n{exc}")
            return

        import time

        class SystemClock:
            def time(self) -> float:
                return time.time()
            def monotonic(self) -> float:
                return time.monotonic()
            def monotonic_ns(self) -> int:
                return time.monotonic_ns()
            def sleep(self, seconds: float) -> None:
                time.sleep(seconds)

        is_dynamic = self.combo_type.currentText() == "Dynamic Movement"
        if is_dynamic:
            self._recorder = None
            self._dynamic_recorder = DynamicGestureRecorder(
                clock=SystemClock(),
                target_hand=target_hand,
            )
            self._dynamic_recorder.start(target_hand)
        else:
            self._dynamic_recorder = None
            self._recorder = StaticGestureRecorder(
                clock=SystemClock(),
                target_hand=target_hand,
            )
            self._recorder.start(target_hand)

        self.btn_start_record.setEnabled(False)
        self.btn_cancel_record.setEnabled(True)
        self.save_box.setEnabled(False)
        self.lbl_collision_warning.setText("")
        self.btn_save_anyway.setVisible(False)

    def _on_cancel_recording_clicked(self) -> None:
        if self._recorder is not None:
            self._recorder.cancel()
        if self._dynamic_recorder is not None:
            self._dynamic_recorder.cancel()
        try:
            self._controller.transition_to(RuntimeMode.STOPPED, "User cancelled recording")
        except Exception:
            pass

        self.btn_start_record.setEnabled(True)
        self.btn_cancel_record.setEnabled(False)
        self.lbl_status.setText("Recording cancelled.")
        self.progress_bar.setValue(0)
        self.camera_view.clear()

    @Slot(object, object)
    def _on_frame_ready(self, packet: FramePacket, tracking: Optional[TrackingResult]) -> None:
        # Update camera preview
        self.camera_view.update_frame(packet, tracking)

        # Feed recorder if active
        if self._recorder is not None and tracking is not None:
            progress = self._recorder.feed_frame(tracking)
            self._update_recorder_ui(progress)
        elif self._dynamic_recorder is not None and tracking is not None:
            dyn_progress = self._dynamic_recorder.feed_frame(tracking)
            self._update_dynamic_recorder_ui(dyn_progress)

    def _update_recorder_ui(self, progress: RecorderProgress) -> None:
        if progress.state == RecorderState.COUNTDOWN:
            secs = progress.countdown_remaining_ms / 1000.0
            self.lbl_status.setText(f"Get Ready... Starting in {secs:.1f}s\n{progress.feedback_message}")
            self.progress_bar.setValue(int((1.0 - progress.countdown_remaining_ms / 3000.0) * 50))
        elif progress.state == RecorderState.CAPTURING:
            percent = int(50 + progress.capture_progress_ratio * 50)
            self.progress_bar.setValue(percent)
            self.lbl_status.setText(f"HOLD STEADY! Capturing samples ({percent}%)...")
        elif progress.state == RecorderState.COMPLETED:
            self.progress_bar.setValue(100)
            self.lbl_status.setText(progress.feedback_message)
            self._current_recording_result = self._recorder.get_result()
            self._on_recording_completed()
        elif progress.state == RecorderState.FAILED:
            self.lbl_status.setText(f"Capture Failed: {progress.feedback_message}")
            try:
                self._controller.transition_to(RuntimeMode.STOPPED, "Recording failed")
            except Exception:
                pass
            self.btn_start_record.setEnabled(True)
            self.btn_cancel_record.setEnabled(False)

    def _update_dynamic_recorder_ui(self, progress: DynamicRecorderProgress) -> None:
        if progress.state == RecorderState.COUNTDOWN:
            secs = progress.countdown_remaining_ms / 1000.0
            self.lbl_status.setText(
                f"Repetition {progress.repetition_index + 1} of {progress.repetitions_target}\n"
                f"Starting in {secs:.1f}s — {progress.feedback_message}"
            )
            pct = int((progress.repetitions_completed / float(progress.repetitions_target)) * 100)
            self.progress_bar.setValue(pct)
        elif progress.state == RecorderState.CAPTURING:
            pct = int(
                ((progress.repetitions_completed + progress.capture_progress_ratio)
                 / float(progress.repetitions_target))
                * 100
            )
            self.progress_bar.setValue(pct)
            self.lbl_status.setText(
                f"Repetition {progress.repetition_index + 1}/{progress.repetitions_target}: "
                f"[{progress.segmenter_state}] {progress.feedback_message}"
            )
        elif progress.state == RecorderState.COMPLETED:
            self.progress_bar.setValue(100)
            self.lbl_status.setText(progress.feedback_message)
            self._current_recording_result = self._dynamic_recorder.get_result()
            self._on_recording_completed()
        elif progress.state == RecorderState.FAILED:
            self.lbl_status.setText(f"Recording Failed: {progress.feedback_message}")
            try:
                self._controller.transition_to(RuntimeMode.STOPPED, "Recording failed")
            except Exception:
                pass
            self.btn_start_record.setEnabled(True)
            self.btn_cancel_record.setEnabled(False)

    def _on_recording_completed(self) -> None:
        self.btn_start_record.setEnabled(True)
        self.btn_cancel_record.setEnabled(False)
        self.save_box.setEnabled(True)

        # Switch camera mode back to STOPPED
        try:
            self._controller.transition_to(RuntimeMode.STOPPED, "Recording completed successfully")
        except Exception:
            pass

        # Check collisions immediately for visual feedback
        if self._current_recording_result and self._current_recording_result.samples:
            if self._current_recording_result.gesture_type == GestureType.DYNAMIC:
                collisions = self._gesture_service.check_dynamic_collisions(
                    samples=self._current_recording_result.samples,
                    hand=self._current_recording_result.hand,
                )
            else:
                collisions = self._gesture_service.check_static_collisions(
                    samples=self._current_recording_result.samples,
                    hand=self._current_recording_result.hand,
                )

            self._pending_collisions = collisions
            if collisions:
                coll_str = ", ".join(f"'{name}' (dist={dist:.3f})" for name, dist in collisions)
                self.lbl_collision_warning.setText(
                    f"Warning: Gesture is very close to existing gesture(s): {coll_str}.\n"
                    "Consider re-recording or use 'Save Anyway'."
                )
                self.btn_save_anyway.setVisible(True)
            else:
                self.lbl_collision_warning.setText("Gesture is unique. Ready to save!")
                self.btn_save_anyway.setVisible(False)

    def _on_save_gesture_clicked(self, allow_collision: bool) -> None:
        name = self.txt_gesture_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation Error", "Please enter a name for the gesture.")
            return

        if not self._current_recording_result or not self._current_recording_result.samples:
            QMessageBox.warning(self, "No Samples", "No valid samples available to save.")
            return

        gesture, collisions = self._gesture_service.create_gesture(
            name=name,
            gesture_type=self._current_recording_result.gesture_type,
            hand=self._current_recording_result.hand,
            samples=self._current_recording_result.samples,
            threshold_scale=1.0,
            allow_collision=allow_collision,
        )

        if gesture is None and collisions:
            coll_str = ", ".join(f"'{n}' (dist={d:.3f})" for n, d in collisions)
            QMessageBox.warning(
                self,
                "Collision Conflict",
                f"Cannot save gesture because it conflicts with: {coll_str}.\n"
                "Please re-record or choose 'Save Anyway'.",
            )
            self.btn_save_anyway.setVisible(True)
            return

        QMessageBox.information(self, "Saved", f"Gesture '{name}' saved successfully!")
        self.txt_gesture_name.clear()
        self.lbl_collision_warning.setText("")
        self.btn_save_anyway.setVisible(False)
        self.save_box.setEnabled(False)
        self.refresh_gestures_list()

    @Slot(str, str)
    def _on_mode_changed(self, mode_str: str, reason: str) -> None:
        if mode_str != RuntimeMode.RECORDING.value:
            if self._recorder is not None and self._recorder.state in (
                RecorderState.COUNTDOWN,
                RecorderState.CAPTURING,
            ):
                self._recorder.cancel()
                self.btn_start_record.setEnabled(True)
                self.btn_cancel_record.setEnabled(False)
            if self._dynamic_recorder is not None and self._dynamic_recorder.state in (
                RecorderState.COUNTDOWN,
                RecorderState.CAPTURING,
            ):
                self._dynamic_recorder.cancel()
                self.btn_start_record.setEnabled(True)
                self.btn_cancel_record.setEnabled(False)

