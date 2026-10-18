"""Unit tests for banded DTW dynamic gesture matcher and speed-variation robustness."""

import time
import numpy as np
import pytest

from domain.enums import Hand, RejectReason
from gestures.dynamic_matcher import (
    DynamicMatcher,
    DynamicTemplate,
    banded_dtw_distance,
    compute_step_cost,
)


def create_synthetic_step_sequence(n_steps: int, dx: float = 0.05, dy: float = 0.0) -> np.ndarray:
    """Generates synthetic 17-dimensional step sequence representing a trajectory swipe."""
    seq = np.zeros((n_steps, 17), dtype=np.float32)
    # Shape part (15 dims): constant fingertips
    base_shape = np.array([
        0.02, 0.08, 0.0,
        0.04, 0.12, 0.0,
        0.0, 0.14, 0.0,
        -0.03, 0.12, 0.0,
        -0.05, 0.08, 0.0,
    ], dtype=np.float32)
    seq[:, :15] = base_shape

    # Trajectory part (2 dims): wrist moving from 0 to dx * n_steps
    for i in range(n_steps):
        seq[i, 15] = dx * (i / float(max(1, n_steps - 1)))
        seq[i, 16] = dy * (i / float(max(1, n_steps - 1)))

    return seq


def test_dtw_identical_sequence_zero_distance():
    seq = create_synthetic_step_sequence(25, dx=0.5)
    dist = banded_dtw_distance(seq, seq)
    assert dist == pytest.approx(0.0, abs=1e-5)


def test_dtw_speed_variation_invariance():
    # Base sequence: 25 steps (e.g. 1.0s at 25 Hz)
    base_seq = create_synthetic_step_sequence(25, dx=1.0)

    # Fast version: 20 steps (0.8s)
    fast_seq = create_synthetic_step_sequence(20, dx=1.0)

    # Slow version: 30 steps (1.2s)
    slow_seq = create_synthetic_step_sequence(30, dx=1.0)

    dist_fast = banded_dtw_distance(base_seq, fast_seq)
    dist_slow = banded_dtw_distance(base_seq, slow_seq)

    # DTW should warp time effectively; distance should be very low
    assert dist_fast < 0.10
    assert dist_slow < 0.10


def test_dtw_length_ratio_prefilter():
    short_seq = create_synthetic_step_sequence(10)
    long_seq = create_synthetic_step_sequence(30)  # ratio = 1/3 < 0.5

    dist = banded_dtw_distance(short_seq, long_seq)
    assert np.isinf(dist)


def test_dynamic_matcher_acceptance_and_margin():
    # Template 1: Swipe Right
    t1_samples = (
        create_synthetic_step_sequence(25, dx=1.0, dy=0.0),
        create_synthetic_step_sequence(26, dx=1.05, dy=0.0),
        create_synthetic_step_sequence(24, dx=0.98, dy=0.0),
    )
    t1 = DynamicTemplate(
        gesture_id=1,
        gesture_name="Swipe Right",
        hand=Hand.RIGHT,
        samples=t1_samples,
        base_threshold=0.25,
    )

    # Template 2: Swipe Up
    t2_samples = (
        create_synthetic_step_sequence(25, dx=0.0, dy=1.0),
        create_synthetic_step_sequence(26, dx=0.0, dy=1.05),
    )
    t2 = DynamicTemplate(
        gesture_id=2,
        gesture_name="Swipe Up",
        hand=Hand.RIGHT,
        samples=t2_samples,
        base_threshold=0.25,
    )

    # Test candidate: slight variation of Swipe Right
    live_steps = create_synthetic_step_sequence(25, dx=1.02, dy=0.02)

    result = DynamicMatcher.match(
        live_steps=live_steps,
        selected_hand=Hand.RIGHT,
        templates=[t1, t2],
    )

    assert result.accepted is True
    assert result.best_gesture_id == 1
    assert result.best_gesture_name == "Swipe Right"
    assert result.best_distance < 0.15
    assert result.margin_ratio < 0.85


def test_dynamic_matcher_ambiguous_margin():
    # Two templates very close to each other
    t1 = DynamicTemplate(
        gesture_id=1,
        gesture_name="Swipe A",
        hand=Hand.RIGHT,
        samples=(create_synthetic_step_sequence(25, dx=1.00),),
        base_threshold=0.30,
    )
    t2 = DynamicTemplate(
        gesture_id=2,
        gesture_name="Swipe B",
        hand=Hand.RIGHT,
        samples=(create_synthetic_step_sequence(25, dx=1.03),),
        base_threshold=0.30,
    )

    # live is at dx=1.014, equidistant enough between dx=1.00 and dx=1.03 that d1/d2 > 0.85
    live = create_synthetic_step_sequence(25, dx=1.014)
    result = DynamicMatcher.match(live, Hand.RIGHT, [t1, t2], margin_ratio_limit=0.85)

    assert result.accepted is False
    assert result.reject_reason == RejectReason.AMBIGUOUS_MARGIN


def test_dtw_performance_budget_10_gestures():
    """Definition of Done (Section 12.1 / Milestone 4):
    DTW within <= 20 ms for 10 gestures (each with 3 samples = 30 DTW comparisons).
    """
    templates = []
    for g in range(10):
        samples = tuple(
            create_synthetic_step_sequence(25, dx=0.5 + 0.05 * g, dy=0.1 * s)
            for s in range(3)
        )
        templates.append(
            DynamicTemplate(
                gesture_id=g + 1,
                gesture_name=f"Gesture {g + 1}",
                hand=Hand.RIGHT,
                samples=samples,
                base_threshold=0.25,
            )
        )

    live = create_synthetic_step_sequence(25, dx=0.7, dy=0.1)

    t0 = time.perf_counter()
    result = DynamicMatcher.match(live, Hand.RIGHT, templates)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert elapsed_ms < 20.0, f"DTW matching took {elapsed_ms:.2f} ms (budget <= 20 ms)"
