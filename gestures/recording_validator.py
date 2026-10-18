"""Validation logic for recorded gesture samples against numerical thresholds."""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple
import numpy as np

from app.constants import (
    MIN_EFFECTIVE_FPS,
    STATIC_CAPTURE_MAX_DEVIATION,
    STATIC_MAX_SPEED,
    STATIC_MIN_VALID_FRAMES,
)
from domain.enums import Hand, RejectReason
from domain.models import HandObservation
from gestures.normalizer import (
    DegenerateHandError,
    mean_landmark_deviation,
    normalize_world_landmarks,
)


class RecordingValidator:
    """Validates recorded static gesture frames according to Section 7.4 numeric rules."""

    @staticmethod
    def validate_static_recording(
        hand_observations: Sequence[Optional[HandObservation]],
        timestamps_ns: Sequence[int],
        target_hand: Hand,
        min_valid_frames: int = STATIC_MIN_VALID_FRAMES,
        max_deviation: float = STATIC_CAPTURE_MAX_DEVIATION,
        max_speed: float = STATIC_MAX_SPEED,
        min_effective_fps: float = MIN_EFFECTIVE_FPS,
    ) -> Tuple[bool, Optional[RejectReason], str, List[int]]:
        """Validates a captured static sequence and returns valid frame indices.
        
        Returns:
            (is_valid, reject_reason, feedback_message, valid_frame_indices)
        """
        total_frames = len(hand_observations)
        if total_frames == 0:
            return False, RejectReason.NO_HAND, "No frames captured during recording session.", []

        # 1. Check frame rate
        duration_s = (timestamps_ns[-1] - timestamps_ns[0]) / 1e9 if total_frames > 1 else 0.0
        effective_fps = total_frames / duration_s if duration_s > 0 else 0.0
        if effective_fps < min_effective_fps and total_frames > 5:
            return (
                False,
                RejectReason.LOW_FPS,
                f"Effective frame rate too low: {effective_fps:.1f} FPS (minimum {min_effective_fps} FPS).",
                [],
            )

        # 2. Check hand detections and target hand consistency
        valid_normalized_landmarks: List[np.ndarray] = []
        valid_indices: List[int] = []
        no_hand_count = 0
        wrong_hand_count = 0

        target_str = target_hand.value.capitalize()

        for idx, hand in enumerate(hand_observations):
            if hand is None:
                no_hand_count += 1
                continue

            if target_hand != Hand.EITHER and hand.label.capitalize() != target_str:
                wrong_hand_count += 1
                continue

            try:
                norm_feat = normalize_world_landmarks(hand.landmarks_world)
                valid_normalized_landmarks.append(norm_feat)
                valid_indices.append(idx)
            except DegenerateHandError:
                continue

        if not valid_indices:
            if wrong_hand_count > 0:
                return (
                    False,
                    RejectReason.WRONG_HAND,
                    f"Expected {target_str} hand, but detected {wrong_hand_count} other hand frames.",
                    [],
                )
            return (
                False,
                RejectReason.NO_HAND,
                "No hand was clearly tracked during the capture window.",
                [],
            )

        # 3. Check stability against running median pose
        # Compute median pose across candidate normalized landmarks
        stacked = np.stack(valid_normalized_landmarks, axis=0)  # shape (N, 20, 3)
        median_pose = np.median(stacked, axis=0)  # shape (20, 3)

        stable_indices: List[int] = []
        deviation_failures = 0

        for i, idx in enumerate(valid_indices):
            feat = valid_normalized_landmarks[i]
            dev = mean_landmark_deviation(feat, median_pose)
            if dev <= max_deviation:
                stable_indices.append(idx)
            else:
                deviation_failures += 1

        if len(stable_indices) < min_valid_frames:
            if deviation_failures > len(stable_indices):
                return (
                    False,
                    RejectReason.HAND_MOVING,
                    f"Hand moved too much during recording (maximum deviation {max_deviation} palm units). Please hold still.",
                    [],
                )
            return (
                False,
                RejectReason.TOO_FEW_VALID_FRAMES,
                f"Captured {len(stable_indices)} stable frames (minimum {min_valid_frames} required).",
                [],
            )

        return True, None, "Static recording successfully validated.", stable_indices
