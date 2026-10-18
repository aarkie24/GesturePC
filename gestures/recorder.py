"""Static gesture recorder managing countdown, burst capture, and sample packaging."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Optional, Tuple
import numpy as np

from app.constants import (
    MODEL_VERSION,
    STATIC_CAPTURE_MAX_DEVIATION,
    STATIC_CAPTURE_WINDOW_MS,
    STATIC_COUNTDOWN_MS,
    STATIC_MAX_SAMPLES,
    STATIC_MAX_SPEED,
    STATIC_MIN_VALID_FRAMES,
)
from domain.enums import GestureType, Hand, RejectReason, TrackingStatus
from domain.models import GestureSample, HandObservation, RecordingResult, TrackingResult
from domain.ports import Clock
from gestures.hand_selector import HandSelector
from gestures.recording_validator import RecordingValidator


class RecorderState(Enum):
    IDLE = auto()
    COUNTDOWN = auto()
    CAPTURING = auto()
    COMPLETED = auto()
    CANCELLED = auto()
    FAILED = auto()


@dataclass(frozen=True)
class RecorderProgress:
    """Live progress reported to UI during recording."""
    state: RecorderState
    countdown_remaining_ms: int
    capture_progress_ratio: float  # 0.0 to 1.0
    quality_hand_present: bool
    quality_hand_still: bool
    feedback_message: str


class StaticGestureRecorder:
    """Manages static gesture recording sessions in RECORDING mode."""

    def __init__(
        self,
        clock: Clock,
        countdown_ms: int = STATIC_COUNTDOWN_MS,
        capture_window_ms: int = STATIC_CAPTURE_WINDOW_MS,
        max_samples: int = STATIC_MAX_SAMPLES,
        target_hand: Hand = Hand.RIGHT,
    ) -> None:
        self._clock = clock
        self.countdown_ms = countdown_ms
        self.capture_window_ms = capture_window_ms
        self.max_samples = max_samples
        self.target_hand = target_hand

        self._state = RecorderState.IDLE
        self._session_start_ts_ns: int = 0
        self._capture_start_ts_ns: int = 0

        self._captured_hands: List[Optional[HandObservation]] = []
        self._captured_timestamps: List[int] = []
        self._frame_aspect_ratio: float = 4.0 / 3.0
        self._result: Optional[RecordingResult] = None
        self._feedback: str = "Ready to record."

    @property
    def state(self) -> RecorderState:
        return self._state

    def start(self, target_hand: Hand) -> None:
        """Starts countdown for a new recording session."""
        self.target_hand = target_hand
        self._state = RecorderState.COUNTDOWN
        self._session_start_ts_ns = self._clock.monotonic_ns()
        self._capture_start_ts_ns = 0
        self._captured_hands.clear()
        self._captured_timestamps.clear()
        self._result = None
        self._feedback = "Get hand ready in camera view..."

    def cancel(self) -> None:
        """Cancels any in-progress recording session."""
        self._state = RecorderState.CANCELLED
        self._feedback = "Recording cancelled."
        self._captured_hands.clear()
        self._captured_timestamps.clear()

    def feed_frame(self, tracking_result: TrackingResult) -> RecorderProgress:
        """Processes a live frame from the camera pipeline.
        
        Returns:
            Current RecorderProgress for UI rendering.
        """
        now_ns = tracking_result.capture_ts_ns or self._clock.monotonic_ns()
        w, h = tracking_result.frame_size
        if h > 0:
            self._frame_aspect_ratio = float(w / h)

        # Select hand according to target
        selection = HandSelector.select_hand(tracking_result, self.target_hand)
        hand_present = selection.status == TrackingStatus.OK and selection.hand is not None
        hand_still = True  # Verified during validation

        if self._state == RecorderState.COUNTDOWN:
            elapsed_ms = int((now_ns - self._session_start_ts_ns) / 1_000_000)
            remaining_ms = max(0, self.countdown_ms - elapsed_ms)
            
            if not hand_present:
                self._feedback = f"Please show your {self.target_hand.value.lower()} hand..."
            else:
                self._feedback = f"Hold still! Starting in {remaining_ms / 1000.0:.1f}s..."

            if remaining_ms == 0:
                self._state = RecorderState.CAPTURING
                self._capture_start_ts_ns = now_ns
                self._feedback = "Capturing pose... Hold steady!"

            return RecorderProgress(
                state=self._state,
                countdown_remaining_ms=remaining_ms,
                capture_progress_ratio=0.0,
                quality_hand_present=hand_present,
                quality_hand_still=hand_still,
                feedback_message=self._feedback,
            )

        elif self._state == RecorderState.CAPTURING:
            self._captured_hands.append(selection.hand)
            self._captured_timestamps.append(now_ns)

            elapsed_capture_ms = int((now_ns - self._capture_start_ts_ns) / 1_000_000)
            ratio = min(1.0, elapsed_capture_ms / float(self.capture_window_ms))

            if elapsed_capture_ms >= self.capture_window_ms:
                self._finish_capture()

            return RecorderProgress(
                state=self._state,
                countdown_remaining_ms=0,
                capture_progress_ratio=ratio,
                quality_hand_present=hand_present,
                quality_hand_still=hand_still,
                feedback_message=self._feedback,
            )

        return RecorderProgress(
            state=self._state,
            countdown_remaining_ms=0,
            capture_progress_ratio=1.0 if self._state == RecorderState.COMPLETED else 0.0,
            quality_hand_present=hand_present,
            quality_hand_still=hand_still,
            feedback_message=self._feedback,
        )

    def _finish_capture(self) -> None:
        """Finishes capture window, validates, and downsamples samples."""
        is_valid, reject_reason, msg, valid_indices = RecordingValidator.validate_static_recording(
            hand_observations=self._captured_hands,
            timestamps_ns=self._captured_timestamps,
            target_hand=self.target_hand,
        )

        total_frames = len(self._captured_timestamps)
        duration_ms = (
            int((self._captured_timestamps[-1] - self._captured_timestamps[0]) / 1e6)
            if total_frames > 1
            else 0
        )
        effective_fps = (total_frames / (duration_ms / 1000.0)) if duration_ms > 0 else 0.0

        if not is_valid:
            self._state = RecorderState.FAILED
            self._feedback = msg
            self._result = RecordingResult(
                gesture_type=GestureType.STATIC,
                hand=self.target_hand,
                samples=(),
                duration_ms=duration_ms,
                effective_fps=effective_fps,
                valid=False,
                reject_reason=reject_reason,
                feedback_key=msg,
            )
            return

        # Select up to max_samples evenly spaced from valid_indices
        if len(valid_indices) > self.max_samples:
            step = len(valid_indices) / float(self.max_samples)
            chosen_indices = [valid_indices[int(i * step)] for i in range(self.max_samples)]
        else:
            chosen_indices = valid_indices

        preprocess_json = json.dumps({"flip_h": True, "normalizer_version": 1})

        # Assemble samples (each sample holds 1 valid frame of raw landmarks as per 7.1/9.2)
        samples_list: List[GestureSample] = []
        for idx_in_chosen, frame_idx in enumerate(chosen_indices):
            hand = self._captured_hands[frame_idx]
            assert hand is not None

            # Raw landmarks shape (1, 21, 3)
            img_landmarks = np.expand_dims(hand.landmarks_image, axis=0)
            world_landmarks = np.expand_dims(hand.landmarks_world, axis=0)

            sample = GestureSample(
                id=None,
                gesture_id=0,  # Assigned when gesture is saved
                sample_index=idx_in_chosen,
                frame_count=1,
                duration_ms=0,
                landmarks_image=img_landmarks,
                landmarks_world=world_landmarks,
                timestamps_ms=None,
                frame_aspect_ratio=self._frame_aspect_ratio,
                tracker_model_id=MODEL_VERSION,
                preprocess_json=preprocess_json,
            )
            samples_list.append(sample)

        self._state = RecorderState.COMPLETED
        self._feedback = f"Successfully captured {len(samples_list)} valid pose samples!"
        self._result = RecordingResult(
            gesture_type=GestureType.STATIC,
            hand=self.target_hand,
            samples=tuple(samples_list),
            duration_ms=duration_ms,
            effective_fps=effective_fps,
            valid=True,
            reject_reason=None,
            feedback_key="SUCCESS",
        )

    def get_result(self) -> Optional[RecordingResult]:
        """Returns the completed RecordingResult if completed or failed."""
        return self._result
