"""Unit tests for dynamic threshold calibration, consistency, and collision checking."""

import numpy as np
import pytest

from gestures.calibration import (
    calculate_dynamic_base_threshold,
    check_dynamic_collisions,
    check_dynamic_sample_consistency,
)
from tests.unit.test_dynamic_matcher import create_synthetic_step_sequence


def test_dynamic_threshold_derivation():
    # 3 samples with pairwise distance ~ 0.10
    s1 = create_synthetic_step_sequence(25, dx=1.0)
    s2 = create_synthetic_step_sequence(25, dx=1.05)
    s3 = create_synthetic_step_sequence(25, dx=0.95)

    base = calculate_dynamic_base_threshold([s1, s2, s3], threshold_slack=1.3)

    # Base threshold should be 1.3 * max_pairwise clamped to [0.08, 0.50]
    assert 0.08 <= base <= 0.50


def test_dynamic_consistency_check_passes():
    s1 = create_synthetic_step_sequence(25, dx=1.0)
    s2 = create_synthetic_step_sequence(25, dx=1.05)
    s3 = create_synthetic_step_sequence(25, dx=0.98)

    is_consistent, max_dtw = check_dynamic_sample_consistency([s1, s2, s3], max_allowed_dtw=0.50)
    assert is_consistent is True
    assert max_dtw < 0.20


def test_dynamic_consistency_check_fails_on_divergent_samples():
    # s1 is horizontal swipe, s2 is vertical swipe (very different, DTW > 0.5)
    s1 = create_synthetic_step_sequence(25, dx=1.0, dy=0.0)
    s2 = create_synthetic_step_sequence(25, dx=0.0, dy=1.0)

    is_consistent, max_dtw = check_dynamic_sample_consistency([s1, s2], max_allowed_dtw=0.50)
    assert is_consistent is False
    assert max_dtw > 0.50


def test_dynamic_collision_check():
    existing_samples = [create_synthetic_step_sequence(25, dx=1.0)]
    existing_gestures = [("Swipe Right", existing_samples, 0.30)]

    # 1. Colliding new samples (nearly identical to Swipe Right)
    new_colliding = [create_synthetic_step_sequence(25, dx=1.02)]
    collisions = check_dynamic_collisions(new_colliding, 0.30, existing_gestures)
    assert len(collisions) == 1
    assert collisions[0][0] == "Swipe Right"

    # 2. Distinct new samples (Swipe Down)
    new_distinct = [create_synthetic_step_sequence(25, dx=0.0, dy=-1.0)]
    collisions_none = check_dynamic_collisions(new_distinct, 0.30, existing_gestures)
    assert len(collisions_none) == 0
