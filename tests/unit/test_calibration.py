"""Unit tests for threshold calibration and gesture collision detection."""

import numpy as np
import pytest

from gestures.calibration import (
    calculate_static_base_threshold,
    check_static_collisions,
)
from gestures.feature_extractor import extract_static_features
from tests.fixtures.generate import generate_pose_landmarks


def test_base_threshold_calculation():
    """Base threshold is clamp(1.5 * p95(r), 0.06, 0.30)."""
    # Create 5 identical samples -> r_i = 0 -> clamped to 0.06
    wf = generate_pose_landmarks("open_palm", noise_sigma=0.0)
    feat = extract_static_features(wf)
    samples_identical = [feat for _ in range(5)]

    thresh = calculate_static_base_threshold(samples_identical)
    assert thresh == 0.06

    # Create samples with controlled variation
    samples_noisy = [
        extract_static_features(generate_pose_landmarks("open_palm", noise_sigma=0.01, seed=i))
        for i in range(10)
    ]
    thresh_noisy = calculate_static_base_threshold(samples_noisy)
    assert 0.06 <= thresh_noisy <= 0.30


def test_collision_detection_identical_poses():
    """Checking identical poses must report collision."""
    wf1 = generate_pose_landmarks("fist", noise_sigma=0.0)
    feat1 = extract_static_features(wf1)

    wf2 = generate_pose_landmarks("fist", noise_sigma=0.002)
    feat2 = extract_static_features(wf2)

    existing = [("Existing Fist", [feat1], 0.12)]
    collisions = check_static_collisions(
        new_sample_features=[feat2],
        new_threshold=0.12,
        existing_gestures=existing,
    )
    assert len(collisions) == 1
    assert collisions[0][0] == "Existing Fist"
    assert collisions[0][1] < 0.12


def test_collision_detection_distinct_poses():
    """Distinct poses (e.g. Open Palm vs Fist) must not report collision."""
    palm_feat = extract_static_features(generate_pose_landmarks("open_palm", noise_sigma=0.0))
    fist_feat = extract_static_features(generate_pose_landmarks("fist", noise_sigma=0.0))

    existing = [("Open Palm", [palm_feat], 0.12)]
    collisions = check_static_collisions(
        new_sample_features=[fist_feat],
        new_threshold=0.12,
        existing_gestures=existing,
    )
    assert len(collisions) == 0
