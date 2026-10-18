"""Main application window with tab views, persistent status bar, overlay, and tray integration."""

from __future__ import annotations

from typing import Callable, Optional
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.constants import APP_DISPLAY_NAME
from camera.frame_types import FramePacket
from domain.enums import RuntimeMode
from domain.models import TrackingResult
from ui.components.live_overlay import LiveOverlay
from ui.components.status_badge import StatusBadge
from ui.qt_bridge import QtBridge
from ui.tabs.live_monitor_tab import LiveMonitorTab
from ui.tray import SystemTray


class MainWindow(QMainWindow):
    """Main application window coordinating tabs, status bar, overlay, and mode events."""

    def __init__(
        self,
        on_start_test: Callable[[], None],
        on_start_live: Callable[[], None],
        on_emergency_stop: Callable[[], None],
        qt_bridge: Optional[QtBridge] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(APP_DISPLAY_NAME)
        self.resize(1180, 750)
        self.setMinimumSize(850, 600)

        self._on_start_test = on_start_test
        self._on_start_live = on_start_live
        self._on_emergency_stop = on_emergency_stop
        self._qt_bridge = qt_bridge

        self._current_mode: RuntimeMode = RuntimeMode.STOPPED

        # 1. Floating Live Overlay
        self._live_overlay = LiveOverlay(on_stop_clicked=self._on_emergency_stop)

        # 2. System Tray
        self._tray = SystemTray(
            on_show_window=self._show_and_activate,
            on_emergency_stop=self._on_emergency_stop,
            parent=self,
        )
        self._tray.show()

        self._init_ui()
        self._connect_bridge()

    def _init_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)

        # Main Tab Widget
        self.tabs = QTabWidget(central)
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #333333; background: #181818; border-radius: 6px; } "
            "QTabBar::tab { background: #242424; color: #cccccc; padding: 10px 20px; font-weight: bold; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 4px; } "
            "QTabBar::tab:selected { background: #181818; color: #ffffff; border-bottom: 2px solid #2196f3; } "
            "QTabBar::tab:hover { background: #2d2d2d; color: #ffffff; }"
        )

        # Tab 1: Live Monitor
        self.live_monitor_tab = LiveMonitorTab(
            on_start_test=self._on_start_test,
            on_start_live=self._on_start_live,
            on_emergency_stop=self._on_emergency_stop,
            parent=self.tabs,
        )
        self.tabs.addTab(self.live_monitor_tab, "Live Monitor")

        # Tab Placeholders for M3-M7
        self.gesture_studio_tab = QWidget()
        self.workflow_studio_tab = QWidget()
        self.testing_tab = QWidget()
        self.settings_tab = QWidget()

        self.tabs.addTab(self.gesture_studio_tab, "Gesture Studio")
        self.tabs.addTab(self.workflow_studio_tab, "Workflow Studio")
        self.tabs.addTab(self.testing_tab, "Testing Studio")
        self.tabs.addTab(self.settings_tab, "Settings")

        layout.addWidget(self.tabs)

        # Persistent Status Bar
        status_bar = QStatusBar(self)
        status_bar.setStyleSheet("background-color: #1e1e1e; border-top: 1px solid #333333;")
        self.setStatusBar(status_bar)

        self._status_badge = StatusBadge(self)
        self._hotkey_label = QLabel("Emergency Stop: Ctrl+Alt+Shift+X", self)
        self._hotkey_label.setStyleSheet("color: #888888; margin-left: 14px; font-size: 11px;")

        self._camera_status_label = QLabel("Camera: Standby", self)
        self._camera_status_label.setStyleSheet("color: #888888; margin-left: 14px; font-size: 11px;")

        self._btn_bar_stop = QPushButton("STOP", self)
        self._btn_bar_stop.setStyleSheet(
            "background-color: #d32f2f; color: #ffffff; font-weight: bold; "
            "padding: 2px 14px; border-radius: 3px; font-size: 11px;"
        )
        self._btn_bar_stop.clicked.connect(self._on_emergency_stop)
        self._btn_bar_stop.setEnabled(False)

        status_bar.addWidget(self._status_badge)
        status_bar.addWidget(self._hotkey_label)
        status_bar.addWidget(self._camera_status_label)
        status_bar.addPermanentWidget(self._btn_bar_stop)

    def _connect_bridge(self) -> None:
        if self._qt_bridge is not None:
            self._qt_bridge.mode_changed.connect(self._on_mode_changed_signal)
            self._qt_bridge.frame_ready.connect(self._on_frame_ready_signal)
            self._qt_bridge.pipeline_error.connect(self._on_pipeline_error_signal)

    @Slot(str, str)
    def _on_mode_changed_signal(self, mode_str: str, reason: str) -> None:
        try:
            mode = RuntimeMode(mode_str)
            self.set_mode(mode)
        except ValueError:
            pass

    @Slot(object, object)
    def _on_frame_ready_signal(self, packet: FramePacket, tracking: Optional[TrackingResult]) -> None:
        self.live_monitor_tab.camera_view.update_frame(packet, tracking)
        if tracking and tracking.hands:
            self.live_monitor_tab.lbl_tracking.setText(f"{tracking.hands[0].label} hand detected")
        else:
            self.live_monitor_tab.lbl_tracking.setText("Searching for hand...")

    @Slot(str, str)
    def _on_pipeline_error_signal(self, code: str, msg: str) -> None:
        self._camera_status_label.setText(f"Camera Error: {code}")
        QMessageBox.warning(self, "Camera Pipeline Alert", f"Pipeline Error ({code}):\n{msg}")

    def set_mode(self, mode: RuntimeMode) -> None:
        """Updates UI components to match active operational mode."""
        self._current_mode = mode
        self._status_badge.set_mode(mode)
        self._tray.set_mode(mode)
        self.live_monitor_tab.set_mode(mode)

        if mode == RuntimeMode.STOPPED:
            self._btn_bar_stop.setEnabled(False)
            self._camera_status_label.setText("Camera: Off")
            self._live_overlay.hide()
        elif mode == RuntimeMode.TEST:
            self._btn_bar_stop.setEnabled(True)
            self._camera_status_label.setText("Camera: Streaming (Test Mode)")
            self._live_overlay.hide()
        elif mode == RuntimeMode.LIVE:
            self._btn_bar_stop.setEnabled(True)
            self._camera_status_label.setText("Camera: Active (LIVE Automation)")
            self._live_overlay.show_in_corner()
        elif mode == RuntimeMode.RECORDING:
            self._btn_bar_stop.setEnabled(True)
            self._camera_status_label.setText("Camera: Recording Gestures")
            self._live_overlay.hide()

    def _show_and_activate(self) -> None:
        self.showNormal()
        self.activateWindow()

    @property
    def current_mode(self) -> RuntimeMode:
        return self._current_mode

    def closeEvent(self, event) -> None:
        """Cleans up tray and overlay on close."""
        self._live_overlay.hide()
        self._tray.hide()
        super().closeEvent(event)
