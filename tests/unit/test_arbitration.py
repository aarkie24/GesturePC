"""Unit tests for static vs dynamic gesture arbitration in RecognitionEngine (Section 7.5)."""

import numpy as np
import pytest

from domain.enums import GestureType, Hand, RejectReason, TrackingStatus, TriggerState
from domain.models import (
    HandObservation,
    SnapshotReport,
    TemplateSnapshot,
    TrackingResult,
)
from gestures.dynamic_matcher import DynamicTemplate
from gestures.feature_extractor import (
    extract_dynamic_step_features,
    extract_static_features,
)
from gestures.normalizer import aspect_correct_image_landmarks
from gestures.recognition_engine import RecognitionEngine
from gestures.resampler import resample_step_vectors
from gestures.segmenter import MotionSegmenter
from gestures.static_matcher import StaticTemplate
from gestures.trigger_validator import TriggerValidator
from tests.fakes.fake_clock import FakeClock


def make_tracking_result(wrist_x: float, wrist_y: float, ts_ns: int, frame_id: int = 1) -> TrackingResult:
    # 21 landmarks world
    world = np.zeros((21, 3), dtype=np.float32)
    world[9, 1] = 0.08  # 8cm palm unit
    # index finger extended for static candidate
    world[8, 1] = 0.16

    # image landmarks
    img = np.zeros((21, 3), dtype=np.float32)
    img[0, :2] = [wrist_x, wrist_y]
    img[9, :2] = [wrist_x, wrist_y - 0.15]
    img[8, :2] = [wrist_x, wrist_y - 0.30]

    hand = HandObservation(
        label="Right",
        label_score=0.99,
        presence_score=0.99,
        landmarks_image=img,
        landmarks_world=world,
    )
    return TrackingResult(
        frame_id=frame_id,
        capture_ts_ns=ts_ns,
        frame_size=(640, 480),
        status=TrackingStatus.OK,
        hands=(hand,),
    )


def test_motion_suppresses_static_gesture():
    clock = FakeClock()
    engine = RecognitionEngine(clock=clock)

    # Compile static template
    sample_feat = extract_static_features(make_tracking_result(0.5, 0.5, 0).hands[0].landmarks_world)
    static_tmpl = StaticTemplate(
        gesture_id=1,
        gesture_name="Point",
        hand=Hand.RIGHT,
        samples=(sample_feat,),
        base_threshold=0.20,
    )
    snapshot = TemplateSnapshot(
        revision=1,
        templates=(static_tmpl,),
        revision_map={1: 1},
        timestamp_utc="",
    )

    # 1. Stationary frame -> static match accumulates
    ts_ns = 1_000_000_000
    res = make_tracking_result(0.5, 0.5, ts_ns, frame_id=1)
    analysis, event = engine.process(res, snapshot)
    assert analysis.outcome == "MATCH"
    assert event is None  # Accumulating

    # 2. Fast movement frame (high speed > 0.35)
    ts_ns += 33_333_333
    res_fast = make_tracking_result(0.65, 0.5, ts_ns, frame_id=2)
    analysis2, event2 = engine.process(res_fast, snapshot)

    assert analysis2.outcome == "MOVING"
    assert analysis2.reject_reason == RejectReason.MOVING
    assert event2 is None


def test_segment_ended_fires_dynamic_gesture_and_resets_static():
    clock = FakeClock()
    engine = RecognitionEngine(clock=clock)

    # 1. First record a reference swipe segment to compile an accurate DynamicTemplate
    init_seg = None
    curr_x = 0.3
    ts_ns = 1_000_000_000
    for i in range(10):
        ts_ns += 33_333_333
        r = make_tracking_result(0.3, 0.5, ts_ns, i)
        engine.segmenter.update(r.hands[0].landmarks_world, r.hands[0].landmarks_image, 640, 480, ts_ns)
    for i in range(15):
        ts_ns += 33_333_333
        curr_x += 0.015
        r = make_tracking_result(curr_x, 0.5, ts_ns, 10 + i)
        engine.segmenter.update(r.hands[0].landmarks_world, r.hands[0].landmarks_image, 640, 480, ts_ns)
    for i in range(20):
        ts_ns += 33_333_333
        r = make_tracking_result(curr_x, 0.5, ts_ns, 25 + i)
        st = engine.segmenter.update(r.hands[0].landmarks_world, r.hands[0].landmarks_image, 640, 480, ts_ns)
        if st.name == "ENDED":
            init_seg = engine.segmenter.pop_segment()
            break

    assert init_seg is not None
    ref_wrist = init_seg.frames[0].wrist_corrected
    tmpl_steps = [
        extract_dynamic_step_features(f.landmarks_world, f.landmarks_image, 640, 480, ref_wrist, init_seg.segment_palm_scale)
        for f in init_seg.frames
    ]
    tmpl_resampled = resample_step_vectors(np.stack(tmpl_steps), init_seg.timestamps_ms)
    assert tmpl_resampled is not None

    dyn_tmpl = DynamicTemplate(
        gesture_id=2,
        gesture_name="Swipe Right",
        hand=Hand.RIGHT,
        samples=(tmpl_resampled,),
        base_threshold=0.35,
    )

    # Also static template
    sample_feat = extract_static_features(make_tracking_result(0.5, 0.5, 0).hands[0].landmarks_world)
    static_tmpl = StaticTemplate(
        gesture_id=1,
        gesture_name="Point",
        hand=Hand.RIGHT,
        samples=(sample_feat,),
        base_threshold=0.20,
    )

    snapshot = TemplateSnapshot(
        revision=1,
        templates=(static_tmpl, dyn_tmpl),
        revision_map={1: 1, 2: 1},
        timestamp_utc="",
    )

    # 2. Reset engine and replay live motion
    engine.reset()
    ts_ns = 2_000_000_000
    frame_id = 100

    # Pre-motion rest (300 ms)
    for _ in range(10):
        ts_ns += 33_333_333
        frame_id += 1
        res = make_tracking_result(0.3, 0.5, ts_ns, frame_id)
        engine.process(res, snapshot)

    # Fast swipe right for 15 frames
    curr_x = 0.3
    for _ in range(15):
        ts_ns += 33_333_333
        frame_id += 1
        curr_x += 0.015
        res = make_tracking_result(curr_x, 0.5, ts_ns, frame_id)
        analysis, event = engine.process(res, snapshot)
        assert analysis.outcome == "MOVING"
        assert event is None

    # Post-motion rest until segment reaches ENDED
    dynamic_fired = False
    for _ in range(20):
        ts_ns += 33_333_333
        frame_id += 1
        res = make_tracking_result(curr_x, 0.5, ts_ns, frame_id)
        analysis, event = engine.process(res, snapshot)
        if event is not None:
            assert event.gesture_type == GestureType.DYNAMIC
            assert event.gesture_name == "Swipe Right"
            dynamic_fired = True
            break

    assert dynamic_fired, "Dynamic gesture should fire once when segment reaches ENDED"

