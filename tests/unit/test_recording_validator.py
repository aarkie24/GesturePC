"""Unit tests for RecordingValidator against Section 7.4 numeric limits."""

import numpy as np
import pytest

from domain.enums import Hand, RejectReason
from domain.models import HandObservation
from gestures.recording_validator import RecordingValidator
from tests.fixtures.generate import generate_pose_landmarks


def _make_hand(pose_name: str, label: str = "Right") -> HandObservation:
    wf = generate_pose_landmarks(pose_name, noise_sigma=0.0)
    return HandObservation(
        label=label,
        label_score=0.99,
        presence_score=0.99,
        landmarks_image=wf,
        landmarks_world=wf,
    )


def test_valid_recording():
    """Sequence with >= 20 stable frames matching target hand passes validation."""
    hands = [_make_hand("open_palm", "Right") for _ in range(25)]
    ts = [int(1e9 + i * 33_333_333) for i in range(25)]

    is_valid, reason, msg, indices = RecordingValidator.validate_static_recording(
        hand_observations=hands,
        timestamps_ns=ts,
        target_hand=Hand.RIGHT,
    )
    assert is_valid is True
    assert reason is None
    assert len(indices) == 25


def test_low_fps_rejection():
    """Effective FPS below 15 FPS rejects as LOW_FPS."""
    hands = [_make_hand("open_palm", "Right") for _ in range(10)]
    # 10 frames over 2 seconds = 5 FPS (< 15 FPS)
    ts = [int(1e9 + i * 200_000_000) for i in range(10)]

    is_valid, reason, msg, indices = RecordingValidator.validate_static_recording(
        hand_observations=hands,
        timestamps_ns=ts,
        target_hand=Hand.RIGHT,
        min_effective_fps=15.0,
    )
    assert is_valid is False
    assert reason == RejectReason.LOW_FPS


def test_wrong_hand_rejection():
    """Target hand is Right but only Left hands observed rejects with WRONG_HAND."""
    hands = [_make_hand("open_palm", "Left") for _ in range(25)]
    ts = [int(1e9 + i * 33_333_333) for i in range(25)]

    is_valid, reason, msg, indices = RecordingValidator.validate_static_recording(
        hand_observations=hands,
        timestamps_ns=ts,
        target_hand=Hand.RIGHT,
    )
    assert is_valid is False
    assert reason == RejectReason.WRONG_HAND


def test_hand_moving_rejection():
    """Frames alternating wildly between distinct poses exceed max deviation -> HAND_MOVING."""
    # Alternates between open palm and fist
    hands = []
    for i in range(30):
        pose = "open_palm" if i % 2 == 0 else "fist"
        hands.append(_make_hand(pose, "Right"))
    ts = [int(1e9 + i * 33_333_333) for i in range(30)]

    is_valid, reason, msg, indices = RecordingValidator.validate_static_recording(
        hand_observations=hands,
        timestamps_ns=ts,
        target_hand=Hand.RIGHT,
        max_deviation=0.10,
    )
    assert is_valid is False
    assert reason in (RejectReason.HAND_MOVING, RejectReason.TOO_FEW_VALID_FRAMES)
