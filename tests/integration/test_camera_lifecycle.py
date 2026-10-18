"""Integration tests for camera pipeline start, frame delivery, and bounded shutdown."""

import time
from app.config import SettingsSchema
from camera.camera_manager import CameraManager
from tests.fakes.fake_camera import FakeCameraBackend


def test_camera_pipeline_lifecycle_and_shutdown_speed():
    settings = SettingsSchema()
    backend = FakeCameraBackend()
    camera_mgr = CameraManager(backend, settings)

    assert not camera_mgr.is_running

    # Start pipeline
    camera_mgr.start_pipeline()
    assert camera_mgr.is_running

    # Verify frame delivery to mailbox
    packet = camera_mgr.live_mailbox.get(timeout_sec=0.5)
    assert packet is not None
    assert packet.frame_bgr.shape == (480, 640, 3)
    assert not packet.frame_bgr.flags.writeable

    # Verify bounded clean shutdown <= 2.0 seconds
    t0 = time.perf_counter()
    camera_mgr.stop_pipeline(timeout_sec=2.0)
    elapsed = time.perf_counter() - t0

    assert not camera_mgr.is_running
    assert elapsed <= 2.0


def test_camera_recording_queue_toggle():
    settings = SettingsSchema()
    backend = FakeCameraBackend()
    camera_mgr = CameraManager(backend, settings)

    camera_mgr.start_pipeline()
    camera_mgr.set_recording_mode(True)

    # Frame should arrive in recording queue
    packet = camera_mgr.recording_queue.get(timeout_sec=0.5)
    assert packet is not None

    camera_mgr.set_recording_mode(False)
    assert camera_mgr.recording_queue.qsize == 0

    camera_mgr.stop_pipeline(timeout_sec=2.0)
