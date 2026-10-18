"""Validation logic for recorded gesture samples against numerical thresholds."""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple
import numpy as np

from app.constants import (
    DYNAMIC_MIN_DURATION_MS,
    MAX_INTERP_GAP_MS,
    MAX_MISSING_RATIO,
    MIN_EFFECTIVE_FPS,
    MIN_MOTION_PATH_PALM,
    STATIC_CAPTURE_MAX_DEVIATION,
    STATIC_MAX_SPEED,
    STATIC_MIN_VALID_FRAMES,
)
from domain.enums import Hand, RejectReason
from domain.models import HandObservation
from gestures.normalizer import (
    DegenerateHandError,
    aspect_correct_image_landmarks,
    compute_palm_unit_image,
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

    @staticmethod
    def validate_dynamic_recording(
        hand_observations: Sequence[Optional[HandObservation]],
        timestamps_ns: Sequence[int],
        target_hand: Hand,
        frame_width: int,
        frame_height: int,
        min_duration_ms: int = DYNAMIC_MIN_DURATION_MS,
        min_motion_path_palm: float = MIN_MOTION_PATH_PALM,
        max_missing_ratio: float = MAX_MISSING_RATIO,
        max_interp_gap_ms: int = MAX_INTERP_GAP_MS,
        min_effective_fps: float = MIN_EFFECTIVE_FPS,
    ) -> Tuple[bool, Optional[RejectReason], str, float, List[int]]:
        """Validates a recorded dynamic gesture segment per Section 7.5.
        
        Rules:
        1. Duration >= dynamic_min_duration_ms (400 ms)
        2. Wrist path length >= min_motion_path_palm (1.5 palm units)
        3. Missing-frame ratio <= max_missing_ratio (0.20)
        4. No tracking gap longer than max_interp_gap_ms (150 ms)
        5. Effective frame rate >= min_effective_fps (15 FPS)
        6. Single hand label matching target hand throughout
        
        Returns:
            (is_valid, reject_reason, feedback_message, path_length_palm, valid_indices)
        """
        total_frames = len(hand_observations)
        if total_frames == 0 or len(timestamps_ns) == 0:
            return False, RejectReason.NO_HAND, "No frames captured during recording window.", 0.0, []

        duration_ms = (timestamps_ns[-1] - timestamps_ns[0]) / 1e6
        if duration_ms < min_duration_ms:
            return (
                False,
                RejectReason.TOO_SHORT,
                f"Movement too short: {duration_ms:.0f} ms (minimum {min_duration_ms} ms required).",
                0.0,
                [],
            )

        duration_s = duration_ms / 1000.0
        effective_fps = total_frames / duration_s if duration_s > 0 else 0.0
        if effective_fps < min_effective_fps:
            return (
                False,
                RejectReason.LOW_FPS,
                f"Effective frame rate too low: {effective_fps:.1f} FPS (minimum {min_effective_fps} FPS).",
                0.0,
                [],
            )

        # Check missing ratio
        missing_count = sum(1 for h in hand_observations if h is None)
        missing_ratio = missing_count / total_frames
        if missing_ratio > max_missing_ratio:
            return (
                False,
                RejectReason.TOO_MANY_GAPS,
                f"Tracking lost in {missing_ratio * 100:.1f}% of frames (maximum {max_missing_ratio * 100:.0f}% allowed).",
                0.0,
                [],
            )

        # Check consecutive gaps
        for i in range(len(timestamps_ns) - 1):
            gap_ms = (timestamps_ns[i + 1] - timestamps_ns[i]) / 1e6
            if gap_ms > max_interp_gap_ms:
                return (
                    False,
                    RejectReason.TOO_MANY_GAPS,
                    f"Tracking gap exceeded {max_interp_gap_ms} ms ({gap_ms:.0f} ms).",
                    0.0,
                    [],
                )

        # Hand label check
        target_str = target_hand.value.capitalize()
        valid_indices: List[int] = []
        for idx, h in enumerate(hand_observations):
            if h is None:
                continue
            if target_hand != Hand.EITHER and h.label.capitalize() != target_str:
                return (
                    False,
                    RejectReason.WRONG_HAND,
                    f"Expected {target_str} hand, but detected {h.label} hand during movement.",
                    0.0,
                    [],
                )
            valid_indices.append(idx)

        if len(valid_indices) < 2:
            return False, RejectReason.NO_HAND, "Insufficient tracked hand frames.", 0.0, []

        # Path length calculation in palm units
        palms: List[float] = []
        wrists: List[np.ndarray] = []
        for idx in valid_indices:
            h = hand_observations[idx]
            assert h is not None
            corrected = aspect_correct_image_landmarks(h.landmarks_image, frame_width, frame_height)
            wrists.append(corrected[0, :2])
            p = compute_palm_unit_image(corrected)
            if p > 1e-4:
                palms.append(p)

        median_palm = float(np.median(palms)) if palms else 1.0
        median_palm = max(median_palm, 1e-4)

        wrist_arr = np.array(wrists)
        diffs = np.linalg.norm(np.diff(wrist_arr, axis=0), axis=1)
        path_length = float(np.sum(diffs) / median_palm)

        if path_length < min_motion_path_palm:
            return (
                False,
                RejectReason.INSUFFICIENT_MOTION,
                f"Movement too small: {path_length:.2f} palm units (minimum {min_motion_path_palm:.1f} required). Please make a clearer gesture.",
                path_length,
                [],
            )

        return (
            True,
            None,
            "Dynamic motion successfully validated.",
            path_length,
            valid_indices,
        )

