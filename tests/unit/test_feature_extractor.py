"""Unit tests for feature extractor."""

import numpy as np
import pytest

from gestures.feature_extractor import (
    FEATURE_VERSION,
    extract_dynamic_step_features,
    extract_static_features,
)
from tests.fixtures.generate import generate_pose_landmarks


def test_feature_version():
    assert FEATURE_VERSION == 1


def test_static_feature_vector_layout():
    """Static feature vector must be 1D float32 array of shape (60,)."""
    lm = generate_pose_landmarks("open_palm", noise_sigma=0.0)
    feat = extract_static_features(lm)

    assert isinstance(feat, np.ndarray)
    assert feat.dtype == np.float32
    assert feat.shape == (60,)
    assert not np.any(np.isnan(feat))
    assert not np.any(np.isinf(feat))


def test_dynamic_step_features_layout():
    """Dynamic step features must be 1D float32 array of shape (17,)."""
    lm_world = generate_pose_landmarks("open_palm", noise_sigma=0.0)
    lm_img = np.full((21, 3), 0.5, dtype=np.float32)

    ref_wrist = np.array([0.5, 0.5], dtype=np.float32)
    step_vec = extract_dynamic_step_features(
        landmarks_world=lm_world,
        landmarks_image=lm_img,
        frame_width=640,
        frame_height=480,
        ref_wrist_image=ref_wrist,
        segment_palm_scale=0.2,
    )

    assert isinstance(step_vec, np.ndarray)
    assert step_vec.dtype == np.float32
    assert step_vec.shape == (17,)
