"""Unit tests for MotionSegmenter state machine (Section 7.5)."""

import numpy as np
import pytest

from gestures.segmenter import MotionSegmenter, SegmenterState


def make_landmarks(wrist_x: float, wrist_y: float, palm_len: float = 0.2):
    """Creates synthetic image and world landmarks with middle MCP at (wrist_x, wrist_y - palm_len)."""
    image_lm = np.zeros((21, 3), dtype=np.float32)
    image_lm[0, :2] = [wrist_x, wrist_y]
    image_lm[9, :2] = [wrist_x, wrist_y - palm_len]

    world_lm = np.zeros((21, 3), dtype=np.float32)
    world_lm[0, :] = [0.0, 0.0, 0.0]
    world_lm[9, :] = [0.0, 0.08, 0.0]  # ~8cm palm
    return world_lm, image_lm


def test_segmenter_stationary_remains_idle():
    segmenter = MotionSegmenter()
    w, h = 640, 480
    ts_ns = 0

    # Feed stationary hand at 30 FPS for 1 second
    for _ in range(30):
        ts_ns += 33_333_333
        world_lm, img_lm = make_landmarks(0.5, 0.5)
        state = segmenter.update(world_lm, img_lm, w, h, ts_ns)
        assert state == SegmenterState.IDLE

    assert segmenter.smoothed_speed < 0.1


def test_segmenter_motion_onset_and_completion():
    segmenter = MotionSegmenter(
        motion_start_speed=0.8,
        motion_start_ms=100,
        motion_end_speed=0.3,
        end_idle_ms=250,
        segment_lookback_ms=300,
    )
    w, h = 640, 480
    ts_ns = 0
    palm_len = 0.2  # 0.2 image units (aspect corrected)

    # 1. Stationary for 400 ms (fills lookback buffer)
    for _ in range(12):
        ts_ns += 33_333_333
        world, img = make_landmarks(0.3, 0.5, palm_len=palm_len)
        state = segmenter.update(world, img, w, h, ts_ns)
        assert state == SegmenterState.IDLE

    # 2. Fast movement (speed ~ 2.0 palm/s for 200 ms > 100 ms start_ms)
    # At 30 FPS, dt = 1/30 s. delta_palm = 2.0 * dt = 0.0667 palm units.
    # In pixels / aspect image coords: delta_pos = 0.0667 * palm_len = 0.0133.
    curr_x = 0.3
    active_observed = False
    for _ in range(10):
        ts_ns += 33_333_333
        curr_x += 0.02
        world, img = make_landmarks(curr_x, 0.5, palm_len=palm_len)
        state = segmenter.update(world, img, w, h, ts_ns)
        if state == SegmenterState.ACTIVE:
            active_observed = True

    assert active_observed, "Segmenter should transition to ACTIVE on high speed"

    # 3. Come to rest (stationary for 600 ms > 173 ms EMA decay + 250 ms end_idle_ms)
    ended_observed = False
    for _ in range(20):
        ts_ns += 33_333_333
        world, img = make_landmarks(curr_x, 0.5, palm_len=palm_len)
        state = segmenter.update(world, img, w, h, ts_ns)
        if state == SegmenterState.ENDED:
            ended_observed = True
            break

    assert ended_observed, "Segmenter should transition to ENDED after resting"

    # 4. Pop completed segment
    seg = segmenter.pop_segment()
    assert seg is not None
    assert len(seg.frames) > 5
    assert seg.duration_ms > 200
    assert segmenter.state == SegmenterState.IDLE


def test_segmenter_aborts_on_excessive_gap():
    segmenter = MotionSegmenter(max_interp_gap_ms=150)
    w, h = 640, 480
    ts_ns = 0
    palm_len = 0.2

    # Transition to ACTIVE
    for _ in range(10):
        ts_ns += 33_333_333
        world, img = make_landmarks(0.3, 0.5, palm_len=palm_len)
        segmenter.update(world, img, w, h, ts_ns)

    curr_x = 0.3
    for _ in range(10):
        ts_ns += 33_333_333
        curr_x += 0.025
        world, img = make_landmarks(curr_x, 0.5, palm_len=palm_len)
        segmenter.update(world, img, w, h, ts_ns)

    assert segmenter.state == SegmenterState.ACTIVE

    # Now introduce gap of 200 ms (> 150 ms)
    ts_ns += 200_000_000
    world, img = make_landmarks(curr_x + 0.01, 0.5, palm_len=palm_len)
    state = segmenter.update(world, img, w, h, ts_ns)

    assert state == SegmenterState.ABORTED
    assert segmenter.pop_segment() is None
