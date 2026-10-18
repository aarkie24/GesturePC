"""Application composition root and lifecycle coordinator."""

from __future__ import annotations

import logging
from pathlib import Path
import sqlite3
import sys
from typing import Optional

from adapters.windows.global_hotkey import Win32GlobalHotkey
from adapters.windows.session_events import Win32SessionEventSource
from app.config import SettingsSchema
from app.paths import get_database_path
from camera.camera_manager import CameraManager
from camera.hand_tracker import HandTracker
from camera.mediapipe_backend import MediaPipeTrackerBackend
from camera.opencv_backend import OpenCVCameraBackend
from database.connection import create_connection
from database.migrator import DatabaseMigrator
from database.repositories.application_repository import ApplicationRepository
from database.repositories.gesture_repository import GestureRepository
from database.repositories.log_repository import LogRepository
from database.repositories.settings_repository import SettingsRepository
from database.repositories.workflow_repository import WorkflowRepository
from domain.enums import RuntimeMode
from domain.ports import Clock
from gestures.recognition_engine import RecognitionEngine
from gestures.template_loader import TemplateLoader
from gestures.trigger_validator import TriggerValidator
from services.diagnostic_sink import DiagnosticSink
from services.event_bus import EventBus
from services.execution_gate import ExecutionGate
from services.gesture_service import GestureService
from services.recognition_pipeline import RecognitionPipeline
from services.runtime_controller import RuntimeController
from services.snapshot_service import SnapshotService
from ui.main_window import MainWindow
from ui.qt_bridge import QtBridge

logger = logging.getLogger(__name__)


class Application:
    """Composition root assembling dependencies and managing system lifecycle."""

    def __init__(
        self,
        db_conn: sqlite3.Connection,
        settings: SettingsSchema,
        event_bus: EventBus,
        gesture_repo: GestureRepository,
        workflow_repo: WorkflowRepository,
        app_repo: ApplicationRepository,
        settings_repo: SettingsRepository,
        log_repo: LogRepository,
        camera_manager: CameraManager,
        execution_gate: ExecutionGate,
        runtime_controller: RuntimeController,
        qt_bridge: QtBridge,
        main_window: MainWindow,
        gesture_service: Optional[Any] = None,
        snapshot_service: Optional[Any] = None,
        recognition_pipeline: Optional[Any] = None,
        hand_tracker: Optional[Any] = None,
        hotkey_service: Optional[Win32GlobalHotkey] = None,
        session_watcher: Optional[Win32SessionEventSource] = None,
    ) -> None:
        self.db_conn = db_conn
        self.settings = settings
        self.event_bus = event_bus
        self.gesture_repo = gesture_repo
        self.workflow_repo = workflow_repo
        self.app_repo = app_repo
        self.settings_repo = settings_repo
        self.log_repo = log_repo
        self.camera_manager = camera_manager
        self.execution_gate = execution_gate
        self.runtime_controller = runtime_controller
        self.qt_bridge = qt_bridge
        self.main_window = main_window
        self.gesture_service = gesture_service
        self.snapshot_service = snapshot_service
        self.recognition_pipeline = recognition_pipeline
        self.hand_tracker = hand_tracker
        self.hotkey_service = hotkey_service
        self.session_watcher = session_watcher

    @classmethod
    def build(
        cls,
        db_path: Optional[Path] = None,
        enable_os_adapters: bool = True,
    ) -> Application:
        """Constructs the application object graph."""
        if db_path is None:
            db_path = get_database_path()

        logger.info("Initializing database connection at %s", db_path)
        conn = create_connection(db_path)

        # 1. Run database migrations
        migrator = DatabaseMigrator()
        new_version = migrator.migrate(conn)
        logger.info("Database migration state verified: user_version=%d", new_version)

        # 2. Construct repositories
        gesture_repo = GestureRepository(conn)
        workflow_repo = WorkflowRepository(conn)
        app_repo = ApplicationRepository(conn)
        settings_repo = SettingsRepository(conn)
        log_repo = LogRepository(conn)

        # 3. Load and validate settings
        stored_settings = settings_repo.get_all()
        validated_settings = SettingsSchema.load_validated(stored_settings)
        logger.info("Settings validated successfully. Stop hotkey configured: %s", validated_settings.stop_hotkey)

        # Check backup interval
        migrator.backup_if_stale(conn, new_version, max_age_days=validated_settings.backup_interval_days)

        # Prune old logs at startup
        pruned_count = log_repo.prune(
            max_rows=validated_settings.log_retention_rows,
            max_days=validated_settings.log_retention_days,
        )
        if pruned_count > 0:
            logger.info("Pruned %d stale log records during startup", pruned_count)

        # 4. Event Bus and QtBridge
        event_bus = EventBus()
        qt_bridge = QtBridge(event_bus)

        # 4b. Template Loader, Snapshot Service, and Gesture Service (M3)
        template_loader = TemplateLoader(gesture_repo)
        snapshot_service = SnapshotService(template_loader, event_bus)
        snapshot_service.rebuild_now()
        gesture_service = GestureService(gesture_repo, snapshot_service, event_bus)

        # 5. Camera Subsystem
        camera_backend = OpenCVCameraBackend()
        camera_manager = CameraManager(
            backend=camera_backend,
            settings=validated_settings,
            event_bus=event_bus,
        )

        # 5b. Tracker Backend & Recognition Engine (M3)
        mediapipe_backend = MediaPipeTrackerBackend()
        hand_tracker = HandTracker(mediapipe_backend)

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

        clock = SystemClock()
        trigger_validator = TriggerValidator(
            clock=clock,
            stable_duration_ms=validated_settings.stable_duration_ms,
            cooldown_ms=validated_settings.cooldown_ms,
            rearm_release_ms=validated_settings.rearm_release_ms,
        )
        recognition_engine = RecognitionEngine(clock=clock, trigger_validator=trigger_validator)

        # 6. Safety Boundary: ExecutionGate & Sinks
        execution_gate = ExecutionGate()
        diagnostic_sink = DiagnosticSink(event_bus=event_bus)

        # 7. OS Adapters (Windows)
        hotkey_service: Optional[Win32GlobalHotkey] = None
        session_watcher: Optional[Win32SessionEventSource] = None

        # 8. RuntimeController
        def check_executable_workflows() -> bool:
            gestures = gesture_repo.list_all(enabled_only=True)
            for g in gestures:
                wfs = workflow_repo.get_for_gesture(g.id)
                if any(w.enabled for w in wfs):
                    return True
            return False

        runtime_controller = RuntimeController(
            gate=execution_gate,
            camera_manager=camera_manager,
            settings=validated_settings,
            diagnostic_sink=diagnostic_sink,
            live_sink=None,  # LiveSink will be wired in Milestone 6
            hotkey_service=None,
            event_bus=event_bus,
            has_executable_workflows_check=check_executable_workflows,
            is_session_unlocked_check=lambda: True,
        )

        # 8b. Recognition Pipeline Coordinator
        recognition_pipeline = RecognitionPipeline(
            camera_manager=camera_manager,
            hand_tracker=hand_tracker,
            recognition_engine=recognition_engine,
            snapshot_service=snapshot_service,
            runtime_controller=runtime_controller,
            qt_bridge=qt_bridge,
            settings=validated_settings,
        )
        recognition_pipeline.start()

        # Initialize OS adapters if on Windows and enabled
        if enable_os_adapters and sys.platform == "win32":
            hotkey_service = Win32GlobalHotkey(
                on_hotkey_pressed=lambda: runtime_controller.emergency_stop("HOTKEY_TRIGGERED")
            )
            # Register default or configured hotkey
            hotkey_service.register(validated_settings.stop_hotkey)
            runtime_controller._hotkey_service = hotkey_service

            session_watcher = Win32SessionEventSource(
                on_session_locked=lambda: runtime_controller.emergency_stop("SESSION_LOCKED")
            )
            session_watcher.start()

        # 9. Main Window Shell
        main_window = MainWindow(
            on_start_test=lambda: runtime_controller.transition_to(RuntimeMode.TEST, "User Start Test"),
            on_start_live=lambda: runtime_controller.transition_to(RuntimeMode.LIVE, "User Start Live"),
            on_emergency_stop=lambda: runtime_controller.emergency_stop("User Clicked Stop"),
            qt_bridge=qt_bridge,
            gesture_service=gesture_service,
            runtime_controller=runtime_controller,
        )
        main_window.set_mode(RuntimeMode.STOPPED)

        return cls(
            db_conn=conn,
            settings=validated_settings,
            event_bus=event_bus,
            gesture_repo=gesture_repo,
            workflow_repo=workflow_repo,
            app_repo=app_repo,
            settings_repo=settings_repo,
            log_repo=log_repo,
            camera_manager=camera_manager,
            execution_gate=execution_gate,
            runtime_controller=runtime_controller,
            qt_bridge=qt_bridge,
            main_window=main_window,
            gesture_service=gesture_service,
            snapshot_service=snapshot_service,
            recognition_pipeline=recognition_pipeline,
            hand_tracker=hand_tracker,
            hotkey_service=hotkey_service,
            session_watcher=session_watcher,
        )

    def shutdown(self) -> None:
        """Performs clean shutdown sequence (ordering per §11-H)."""
        logger.info("Initiating application shutdown...")
        try:
            self.runtime_controller.emergency_stop("SHUTDOWN")
        except Exception as exc:
            logger.error("Error during controller stop: %s", exc)

        if self.recognition_pipeline:
            try:
                self.recognition_pipeline.stop(timeout_sec=2.0)
            except Exception as exc:
                logger.error("Error stopping recognition pipeline: %s", exc)

        if self.hand_tracker:
            try:
                self.hand_tracker.close()
            except Exception as exc:
                logger.error("Error closing hand tracker: %s", exc)

        if self.hotkey_service:
            try:
                self.hotkey_service.unregister()
            except Exception as exc:
                logger.error("Error unregistering hotkey: %s", exc)

        if self.session_watcher:
            try:
                self.session_watcher.stop()
            except Exception as exc:
                logger.error("Error stopping session watcher: %s", exc)

        try:
            self.camera_manager.stop_pipeline(timeout_sec=2.0)
        except Exception as exc:
            logger.error("Error stopping camera manager: %s", exc)

        try:
            self.db_conn.close()
            logger.info("Database connection closed cleanly.")
        except Exception as exc:
            logger.error("Error during database shutdown: %s", exc)
