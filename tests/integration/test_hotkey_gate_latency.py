"""Integration tests measuring emergency stop hotkey-to-gate-closure latency."""

import time
import numpy as np

from app.config import SettingsSchema
from camera.camera_manager import CameraManager
from domain.enums import RuntimeMode
from services.diagnostic_sink import DiagnosticSink
from services.event_bus import EventBus
from services.execution_gate import ExecutionGate
from services.runtime_controller import RuntimeController
from tests.fakes.fake_camera import FakeCameraBackend
from tests.fakes.fake_hotkey import FakeHotkeyService


def test_hotkey_to_gate_closure_latency():
    settings = SettingsSchema()
    event_bus = EventBus()
    camera_mgr = CameraManager(FakeCameraBackend(), settings, event_bus)
    gate = ExecutionGate()
    diagnostic_sink = DiagnosticSink(event_bus)

    latencies_ms = []

    for _ in range(50):
        hotkey = FakeHotkeyService()
        hotkey.register()

        controller = RuntimeController(
            gate=gate,
            camera_manager=camera_mgr,
            settings=settings,
            diagnostic_sink=diagnostic_sink,
            live_sink=None,
            hotkey_service=hotkey,
            event_bus=event_bus,
            has_executable_workflows_check=lambda: True,
            is_session_unlocked_check=lambda: True,
        )

        hotkey.callback = lambda: controller.emergency_stop("HOTKEY")
        controller.transition_to(RuntimeMode.LIVE)
        assert gate.is_open

        # Measure trigger to gate closure
        t0 = time.perf_counter()
        hotkey.simulate_press()
        gate_closed = not gate.is_open
        elapsed_ms = (time.perf_counter() - t0) * 1000

        assert gate_closed
        latencies_ms.append(elapsed_ms)

    p50 = float(np.percentile(latencies_ms, 50))
    p95 = float(np.percentile(latencies_ms, 95))

    # Target from §12.1 is p95 <= 100 ms
    assert p95 <= 100.0, f"Hotkey-to-gate p95 latency {p95:.2f}ms exceeded 100ms ceiling!"
