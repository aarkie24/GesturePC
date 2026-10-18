"""Unit tests for static template matcher and margin ratio test."""

import numpy as np
import pytest

from domain.enums import Hand, RejectReason
from gestures.feature_extractor import extract_static_features
from gestures.static_matcher import StaticMatcher, StaticTemplate
from tests.fixtures.generate import generate_pose_landmarks


def test_known_match():
    """Matching exact pose against template yields accepted candidate."""
    feat_palm = extract_static_features(generate_pose_landmarks("open_palm", noise_sigma=0.0))
    feat_fist = extract_static_features(generate_pose_landmarks("fist", noise_sigma=0.0))

    tmpl_palm = StaticTemplate(1, "Palm", Hand.RIGHT, (feat_palm,), base_threshold=0.15)
    tmpl_fist = StaticTemplate(2, "Fist", Hand.RIGHT, (feat_fist,), base_threshold=0.15)

    res = StaticMatcher.match(
        live_features=feat_palm,
        selected_hand=Hand.RIGHT,
        templates=[tmpl_palm, tmpl_fist],
    )

    assert res.accepted is True
    assert res.best_gesture_id == 1
    assert res.best_distance == 0.0
    assert res.second_gesture_id == 2
    assert res.second_distance > 0.3
    assert res.reject_reason is None


def test_above_threshold_rejection():
    """Live pose distance exceeding threshold rejects with ABOVE_THRESHOLD."""
    feat_palm = extract_static_features(generate_pose_landmarks("open_palm", noise_sigma=0.0))
    feat_fist = extract_static_features(generate_pose_landmarks("fist", noise_sigma=0.0))

    # Template only knows Fist
    tmpl_fist = StaticTemplate(2, "Fist", Hand.RIGHT, (feat_fist,), base_threshold=0.10)

    # Live hand is Open Palm
    res = StaticMatcher.match(
        live_features=feat_palm,
        selected_hand=Hand.RIGHT,
        templates=[tmpl_fist],
    )

    assert res.accepted is False
    assert res.reject_reason == RejectReason.ABOVE_THRESHOLD
    assert res.best_distance > 0.10


def test_margin_ratio_rejection():
    """When d_best / d_second > margin_ratio (0.80), candidate is rejected as AMBIGUOUS_MARGIN."""
    feat = extract_static_features(generate_pose_landmarks("open_palm", noise_sigma=0.0))

    # Two nearly identical templates
    tmpl1 = StaticTemplate(1, "Pose1", Hand.RIGHT, (feat,), base_threshold=0.20)
    # Slightly perturbed sample
    feat_close = feat + 0.02
    tmpl2 = StaticTemplate(2, "Pose2", Hand.RIGHT, (feat_close,), base_threshold=0.20)

    # Live feature halfway between them
    feat_live = feat + 0.01
    res = StaticMatcher.match(
        live_features=feat_live,
        selected_hand=Hand.RIGHT,
        templates=[tmpl1, tmpl2],
        margin_ratio_limit=0.80,
    )

    # Both distances will be ~0.01, ratio close to 1.0 > 0.80
    assert res.accepted is False
    assert res.reject_reason == RejectReason.AMBIGUOUS_MARGIN


def test_hand_laterality_filtering():
    """Template for LEFT hand is ignored when RIGHT hand is observed."""
    feat_palm = extract_static_features(generate_pose_landmarks("open_palm", noise_sigma=0.0))
    tmpl_left = StaticTemplate(1, "Left Palm", Hand.LEFT, (feat_palm,), base_threshold=0.20)

    res = StaticMatcher.match(
        live_features=feat_palm,
        selected_hand=Hand.RIGHT,
        templates=[tmpl_left],
    )
    assert res.accepted is False
    assert res.reject_reason == RejectReason.ABOVE_THRESHOLD
