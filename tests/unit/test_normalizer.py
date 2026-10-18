"""Unit tests for landmarks normalizer and coordinate transformations."""

import numpy as np
import pytest

from domain.enums import RejectReason
from gestures.normalizer import (
    NORMALIZER_VERSION,
    DegenerateHandError,
    aspect_correct_image_landmarks,
    compute_palm_unit_image,
    mean_landmark_deviation,
    normalize_world_landmarks,
)
from tests.fixtures.generate import generate_pose_landmarks


def test_normalizer_version():
    assert NORMALIZER_VERSION == 1


def test_translation_invariance():
    """Translating the wrist to any 3D coordinate must yield identical normalized landmarks."""
    base = generate_pose_landmarks("open_palm", noise_sigma=0.0)
    translated_1 = generate_pose_landmarks("open_palm", noise_sigma=0.0, wrist_translation=(1.5, -2.0, 0.75))
    translated_2 = generate_pose_landmarks("open_palm", noise_sigma=0.0, wrist_translation=(-10.0, 5.0, -3.2))

    norm_base = normalize_world_landmarks(base)
    norm_t1 = normalize_world_landmarks(translated_1)
    norm_t2 = normalize_world_landmarks(translated_2)

    np.testing.assert_allclose(norm_t1, norm_base, atol=1e-5)
    np.testing.assert_allclose(norm_t2, norm_base, atol=1e-5)


def test_uniform_scale_invariance():
    """Uniform scaling by hand distance/size must yield identical normalized landmarks."""
    base = generate_pose_landmarks("open_palm", scale=1.0)
    scaled_small = generate_pose_landmarks("open_palm", scale=0.5)
    scaled_large = generate_pose_landmarks("open_palm", scale=2.5)

    norm_base = normalize_world_landmarks(base)
    norm_small = normalize_world_landmarks(scaled_small)
    norm_large = normalize_world_landmarks(scaled_large)

    np.testing.assert_allclose(norm_small, norm_base, atol=1e-5)
    np.testing.assert_allclose(norm_large, norm_base, atol=1e-5)


def test_determinism():
    """Normalizer is deterministic given identical input."""
    base = generate_pose_landmarks("fist", noise_sigma=0.0)
    norm1 = normalize_world_landmarks(base)
    norm2 = normalize_world_landmarks(base)
    np.testing.assert_array_equal(norm1, norm2)


def test_degenerate_hand():
    """A hand whose palm unit is below 1e-6 must raise DegenerateHandError."""
    degenerate = np.zeros((21, 3), dtype=np.float32)
    with pytest.raises(DegenerateHandError):
        normalize_world_landmarks(degenerate)


def test_rotation_sensitivity():
    """Section 7.3: Orientation is preserved. A 180° rotation must change distance beyond default threshold."""
    base = generate_pose_landmarks("thumbs_up", noise_sigma=0.0)
    
    # Rotate 180 degrees around Z axis (flips thumbs-up to thumbs-down)
    rot_180 = base.copy()
    rot_180[:, 0] = -rot_180[:, 0]
    rot_180[:, 1] = -rot_180[:, 1]

    norm_base = normalize_world_landmarks(base)
    norm_rot = normalize_world_landmarks(rot_180)

    dist = mean_landmark_deviation(norm_base, norm_rot)
    # Threshold for thumbs-up is typically ~0.12 palm units; 180 rotation distance is much larger (> 0.5)
    assert dist > 0.30, f"Distance {dist} should be substantially above default threshold for 180 deg rotation"


def test_mean_landmark_deviation():
    """MLD between identical poses is 0.0."""
    base = generate_pose_landmarks("peace", noise_sigma=0.0)
    norm = normalize_world_landmarks(base)
    assert mean_landmark_deviation(norm, norm) == 0.0


def test_aspect_correction():
    """Aspect correction scales x coordinate by width/height."""
    img_lm = np.full((21, 3), 0.5, dtype=np.float32)
    corrected = aspect_correct_image_landmarks(img_lm, width=640, height=480)
    expected_x = 0.5 * (640 / 480)
    assert pytest.approx(corrected[0, 0]) == expected_x
    assert pytest.approx(corrected[0, 1]) == 0.5
