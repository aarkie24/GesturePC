"""Unit tests covering the complete RuntimeController mode transition table and preconditions."""

import pytest

from app.config import SettingsSchema
from camera.camera_manager import CameraManager
from domain.enums import RuntimeMode
from domain.exceptions import InvalidModeTransition
from services.diagnostic_sink import DiagnosticSink
from services.event_bus import EventBus
from services.execution_gate import ExecutionGate
from services.runtime_controller import RuntimeController
from tests.fakes.fake_camera import FakeCameraBackend
from tests.fakes.fake_hotkey import FakeHotkeyService


@pytest.fixture
def controller_fixtures():
    settings = SettingsSchema()
    event_bus = EventBus()
    camera_backend = FakeCameraBackend()
    camera_manager = CameraManager(camera_backend, settings, event_bus)
    gate = ExecutionGate()
    diagnostic_sink = DiagnosticSink(event_bus)
    hotkey_service = FakeHotkeyService()
    hotkey_service.register()

    controller = RuntimeController(
        gate=gate,
        camera_manager=camera_manager,
        settings=settings,
        diagnostic_sink=diagnostic_sink,
        live_sink=None,
        hotkey_service=hotkey_service,
        event_bus=event_bus,
        has_executable_workflows_check=lambda: True,
        is_session_unlocked_check=lambda: True,
    )
    return controller, gate, hotkey_service, camera_manager


def test_transition_table_allowed_paths(controller_fixtures):
    controller, gate, hotkey, camera_mgr = controller_fixtures

    # Initial state is STOPPED
    assert controller.mode == RuntimeMode.STOPPED
    assert not gate.is_open

    # STOPPED -> TEST
    controller.transition_to(RuntimeMode.TEST)
    assert controller.mode == RuntimeMode.TEST
    assert camera_mgr.is_running
    assert not gate.is_open

    # TEST -> STOPPED
    controller.transition_to(RuntimeMode.STOPPED)
    assert controller.mode == RuntimeMode.STOPPED
    assert not camera_mgr.is_running

    # STOPPED -> LIVE
    controller.transition_to(RuntimeMode.LIVE)
    assert controller.mode == RuntimeMode.LIVE
    assert gate.is_open
    assert camera_mgr.is_running

    # LIVE -> TEST (gate closes first)
    controller.transition_to(RuntimeMode.TEST)
    assert controller.mode == RuntimeMode.TEST
    assert not gate.is_open
    assert camera_mgr.is_running

    # TEST -> LIVE
    controller.transition_to(RuntimeMode.LIVE)
    assert controller.mode == RuntimeMode.LIVE
    assert gate.is_open

    # LIVE -> STOPPED
    controller.transition_to(RuntimeMode.STOPPED)
    assert controller.mode == RuntimeMode.STOPPED
    assert not gate.is_open

    # STOPPED -> RECORDING
    controller.transition_to(RuntimeMode.RECORDING)
    assert controller.mode == RuntimeMode.RECORDING
    assert camera_mgr.is_running
    assert not gate.is_open

    # RECORDING -> STOPPED
    controller.transition_to(RuntimeMode.STOPPED)
    assert controller.mode == RuntimeMode.STOPPED
    assert not camera_mgr.is_running


def test_transition_table_forbidden_paths(controller_fixtures):
    controller, gate, hotkey, camera_mgr = controller_fixtures

    # Enter RECORDING
    controller.transition_to(RuntimeMode.RECORDING)

    # RECORDING -> TEST is forbidden (must pass through STOPPED)
    with pytest.raises(InvalidModeTransition):
        controller.transition_to(RuntimeMode.TEST)

    # RECORDING -> LIVE is forbidden (must pass through STOPPED)
    with pytest.raises(InvalidModeTransition):
        controller.transition_to(RuntimeMode.LIVE)

    # Clean exit back to STOPPED
    controller.transition_to(RuntimeMode.STOPPED)


def test_live_mode_preconditions_enforced(controller_fixtures):
    controller, gate, hotkey, camera_mgr = controller_fixtures

    # 1. Hotkey unregistered blocks LIVE entry
    hotkey.unregister()
    with pytest.raises(InvalidModeTransition, match="hotkey is not registered"):
        controller.transition_to(RuntimeMode.LIVE)
    hotkey.register()

    # 2. Locked session blocks LIVE entry
    controller._is_session_unlocked = lambda: False
    with pytest.raises(InvalidModeTransition, match="session is locked"):
        controller.transition_to(RuntimeMode.LIVE)
    controller._is_session_unlocked = lambda: True

    # 3. No executable workflows blocks LIVE entry
    controller._has_executable_workflows = lambda: False
    with pytest.raises(InvalidModeTransition, match="No enabled gestures"):
        controller.transition_to(RuntimeMode.LIVE)
    controller._has_executable_workflows = lambda: True

    # When all hold, transition succeeds
    controller.transition_to(RuntimeMode.LIVE)
    assert controller.mode == RuntimeMode.LIVE


def test_emergency_stop_always_honored(controller_fixtures):
    controller, gate, hotkey, camera_mgr = controller_fixtures

    controller.transition_to(RuntimeMode.LIVE)
    assert gate.is_open

    # Emergency stop
    controller.emergency_stop("TEST_EMERGENCY")
    assert controller.mode == RuntimeMode.STOPPED
    assert not gate.is_open
    assert gate.close_reason == "TEST_EMERGENCY"
    assert not camera_mgr.is_running
