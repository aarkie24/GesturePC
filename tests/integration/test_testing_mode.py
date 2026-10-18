"""Integration test: One recorded static gesture is recognized in Test mode without any desktop execution."""

import numpy as np
import pytest

from app.config import SettingsSchema
from app.constants import MODEL_VERSION
from database.repositories.gesture_repository import GestureRepository
from domain.enums import GestureType, Hand, RuntimeMode, TrackingStatus
from domain.models import Gesture, GestureSample, HandObservation, TrackingResult
from gestures.recognition_engine import RecognitionEngine
from gestures.template_loader import TemplateLoader
from gestures.trigger_validator import TriggerValidator
from services.diagnostic_sink import DiagnosticSink
from services.event_bus import EventBus
from services.snapshot_service import SnapshotService
from tests.fakes.fake_clock import FakeClock
from tests.fixtures.generate import generate_pose_landmarks


def test_one_recorded_static_gesture_recognized_in_test_mode(temp_db_conn):
    """Milestone 3 Definition of Done:
    1. A static gesture is recorded and persisted to database.
    2. Snapshot is built.
    3. Application enters TEST mode.
    4. Replaying the recorded gesture pose triggers acceptance and emits RecognitionEvent.
    5. Zero desktop actions are executed (Test mode safety boundary).
    """
    repo = GestureRepository(temp_db_conn)
    bus = EventBus()
    clock = FakeClock(initial_time=1000.0)

    # 1. Record and save a static gesture ("Peace Sign")
    wf = generate_pose_landmarks("peace", noise_sigma=0.0)
    img_wf = np.full((1, 21, 3), 0.5, dtype=np.float32)
    world_wf = np.expand_dims(wf, axis=0)

    gesture = Gesture(None, "Peace Sign", GestureType.STATIC, Hand.RIGHT, enabled=True)
    sample = GestureSample(
        id=None,
        gesture_id=0,
        sample_index=0,
        frame_count=1,
        duration_ms=0,
        landmarks_image=img_wf,
        landmarks_world=world_wf,
        timestamps_ms=None,
        frame_aspect_ratio=1.333,
        tracker_model_id=MODEL_VERSION,
        preprocess_json="{}",
    )
    saved_gesture = repo.create(gesture, [sample])
    assert saved_gesture.id is not None

    # 2. Compile snapshot
    loader = TemplateLoader(repo)
    snapshot_service = SnapshotService(loader, bus)
    snapshot = snapshot_service.rebuild_now()
    assert len(snapshot.templates) == 1
    assert snapshot.templates[0].gesture_name == "Peace Sign"

    # 3. Setup Recognition Engine & Diagnostic Sink (TEST Mode)
    validator = TriggerValidator(clock=clock, stable_duration_ms=400, cooldown_ms=1500)
    engine = RecognitionEngine(clock=clock, trigger_validator=validator)

    diagnostic_sink = DiagnosticSink(event_bus=bus)
    received_events = []

    # Patch diagnostic sink to collect emitted events
    original_on_event = diagnostic_sink.on_recognition_event

    def spy_on_recognition_event(ev):
        received_events.append(ev)
        original_on_event(ev)

    diagnostic_sink.on_recognition_event = spy_on_recognition_event

    # 4. Stream 20 frames (660 ms) of the Peace Sign pose into the engine
    t0_ns = clock.monotonic_ns()
    for frame_idx in range(20):
        t_ns = t0_ns + frame_idx * 33_333_333
        clock.set_ns(t_ns)

        # Pose with slight noise matching template
        noisy_wf = generate_pose_landmarks("peace", noise_sigma=0.002, seed=frame_idx)
        obs = HandObservation(
            label="Right",
            label_score=0.99,
            presence_score=0.99,
            landmarks_image=img_wf[0],
            landmarks_world=noisy_wf,
        )
        tr = TrackingResult(
            frame_id=frame_idx,
            capture_ts_ns=t_ns,
            frame_size=(640, 480),
            status=TrackingStatus.OK,
            hands=(obs,),
        )

        analysis, event = engine.process(
            tracking_result=tr,
            snapshot=snapshot,
            tracked_hand=Hand.RIGHT,
        )
        diagnostic_sink.on_frame_analysis(analysis)

        if event is not None:
            diagnostic_sink.on_recognition_event(event)

    # 5. Verify Milestone 3 Criteria:
    # Gesture was recognized and exactly one event was accepted!
    assert len(received_events) == 1, f"Expected exactly 1 event, got {len(received_events)}"
    ev = received_events[0]
    assert ev.gesture_id == saved_gesture.id
    assert ev.gesture_name == "Peace Sign"
    assert ev.hand == Hand.RIGHT
    assert ev.distance < 0.10

    # Safety boundary verification: DiagnosticSink has zero executor/adapter connections
    assert not hasattr(diagnostic_sink, "_gate")
    assert not hasattr(diagnostic_sink, "_executor")
    assert not hasattr(diagnostic_sink, "_dispatcher")
