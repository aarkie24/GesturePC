"""Static gesture recorder managing countdown, burst capture, and sample packaging."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Optional, Tuple
import numpy as np

from app.constants import (
    DYNAMIC_D_MAX,
    DYNAMIC_MAX_WINDOW_MS,
    DYNAMIC_MIN_DURATION_MS,
    DYNAMIC_SAMPLES_REQUIRED,
    MIN_MOTION_PATH_PALM,
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
from gestures.calibration import check_dynamic_sample_consistency
from gestures.feature_extractor import extract_dynamic_step_features
from gestures.hand_selector import HandSelector
from gestures.recording_validator import RecordingValidator
from gestures.resampler import resample_step_vectors
from gestures.segmenter import MotionSegment, MotionSegmenter, SegmenterState


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


@dataclass(frozen=True)
class DynamicRecorderProgress:
    """Live progress reported to UI during dynamic gesture recording."""
    state: RecorderState
    repetition_index: int  # 0, 1, 2
    repetitions_completed: int  # 0 to 3
    repetitions_target: int  # 3
    countdown_remaining_ms: int
    capture_progress_ratio: float
    hand_present: bool
    hand_speed: float
    segmenter_state: str  # "IDLE", "ACTIVE", "ENDED", "ABORTED"
    feedback_message: str


class DynamicGestureRecorder:
    """Manages dynamic gesture recording sessions with auto-stopping MotionSegmenter."""

    def __init__(
        self,
        clock: Clock,
        countdown_ms: int = STATIC_COUNTDOWN_MS,
        max_window_ms: int = DYNAMIC_MAX_WINDOW_MS,
        samples_required: int = DYNAMIC_SAMPLES_REQUIRED,
        target_hand: Hand = Hand.RIGHT,
    ) -> None:
        self._clock = clock
        self.countdown_ms = countdown_ms
        self.max_window_ms = max_window_ms
        self.samples_required = samples_required
        self.target_hand = target_hand

        self._segmenter = MotionSegmenter()
        self._state = RecorderState.IDLE
        self._current_repetition: int = 0
        self._session_start_ts_ns: int = 0
        self._capture_start_ts_ns: int = 0

        # List of (MotionSegment, resampled_steps_17)
        self._collected_repetitions: List[Tuple[MotionSegment, np.ndarray]] = []
        self._frame_aspect_ratio: float = 4.0 / 3.0
        self._result: Optional[RecordingResult] = None
        self._feedback: str = "Ready to record dynamic gesture."

    @property
    def state(self) -> RecorderState:
        return self._state

    def start(self, target_hand: Hand) -> None:
        """Starts a dynamic recording session requiring samples_required valid repetitions."""
        self.target_hand = target_hand
        self._state = RecorderState.COUNTDOWN
        self._current_repetition = 0
        self._collected_repetitions.clear()
        self._result = None
        self._segmenter.reset()
        self._session_start_ts_ns = self._clock.monotonic_ns()
        self._capture_start_ts_ns = 0
        self._feedback = f"Repetition 1 of {self.samples_required}: Get ready..."

    def cancel(self) -> None:
        """Cancels recording session and resets state."""
        self._state = RecorderState.CANCELLED
        self._feedback = "Dynamic recording cancelled."
        self._collected_repetitions.clear()
        self._segmenter.reset()

    def feed_frame(self, tracking_result: TrackingResult) -> DynamicRecorderProgress:
        """Processes a live frame from camera pipeline."""
        now_ns = tracking_result.capture_ts_ns or self._clock.monotonic_ns()
        w, h = tracking_result.frame_size
        if h > 0:
            self._frame_aspect_ratio = float(w / h)

        selection = HandSelector.select_hand(tracking_result, self.target_hand)
        hand_present = selection.status == TrackingStatus.OK and selection.hand is not None
        hand_obs = selection.hand

        landmarks_world = hand_obs.landmarks_world if hand_obs else None
        landmarks_image = hand_obs.landmarks_image if hand_obs else None

        if self._state == RecorderState.COUNTDOWN:
            elapsed_ms = int((now_ns - self._session_start_ts_ns) / 1_000_000)
            remaining_ms = max(0, self.countdown_ms - elapsed_ms)

            target_name = self.target_hand.value.lower()
            if not hand_present:
                self._feedback = f"Repetition {self._current_repetition + 1}/{self.samples_required}: Show {target_name} hand..."
            else:
                self._feedback = f"Repetition {self._current_repetition + 1}/{self.samples_required}: Starting in {remaining_ms / 1000.0:.1f}s..."

            if remaining_ms == 0:
                self._state = RecorderState.CAPTURING
                self._capture_start_ts_ns = now_ns
                self._segmenter.reset()
                self._feedback = f"Perform movement {self._current_repetition + 1}/{self.samples_required} now!"

            return DynamicRecorderProgress(
                state=self._state,
                repetition_index=self._current_repetition,
                repetitions_completed=len(self._collected_repetitions),
                repetitions_target=self.samples_required,
                countdown_remaining_ms=remaining_ms,
                capture_progress_ratio=0.0,
                hand_present=hand_present,
                hand_speed=0.0,
                segmenter_state="IDLE",
                feedback_message=self._feedback,
            )

        elif self._state == RecorderState.CAPTURING:
            # Update segmenter
            seg_state = self._segmenter.update(landmarks_world, landmarks_image, w, h, now_ns)

            elapsed_capture_ms = int((now_ns - self._capture_start_ts_ns) / 1_000_000)
            ratio = min(1.0, elapsed_capture_ms / float(self.max_window_ms))

            if seg_state == SegmenterState.ACTIVE:
                self._feedback = f"Recording motion ({self._segmenter.smoothed_speed:.1f} palm/s)..."
            elif seg_state == SegmenterState.ENDED:
                self._process_ended_segment(w, h, now_ns)
            elif seg_state == SegmenterState.ABORTED:
                # Retry repetition
                self._feedback = "Tracking lost during motion. Let's retry this repetition..."
                self._restart_countdown(now_ns)
            elif elapsed_capture_ms >= self.max_window_ms:
                # Capture window timed out
                self._feedback = "Movement window timed out. Let's retry this repetition..."
                self._restart_countdown(now_ns)

            return DynamicRecorderProgress(
                state=self._state,
                repetition_index=self._current_repetition,
                repetitions_completed=len(self._collected_repetitions),
                repetitions_target=self.samples_required,
                countdown_remaining_ms=0,
                capture_progress_ratio=ratio,
                hand_present=hand_present,
                hand_speed=self._segmenter.smoothed_speed,
                segmenter_state=seg_state.name,
                feedback_message=self._feedback,
            )

        return DynamicRecorderProgress(
            state=self._state,
            repetition_index=self._current_repetition,
            repetitions_completed=len(self._collected_repetitions),
            repetitions_target=self.samples_required,
            countdown_remaining_ms=0,
            capture_progress_ratio=1.0 if self._state == RecorderState.COMPLETED else 0.0,
            hand_present=hand_present,
            hand_speed=0.0,
            segmenter_state="IDLE",
            feedback_message=self._feedback,
        )

    def _restart_countdown(self, now_ns: int) -> None:
        """Restarts countdown for the current repetition."""
        self._state = RecorderState.COUNTDOWN
        self._session_start_ts_ns = now_ns
        self._segmenter.reset()

    def _process_ended_segment(self, w: int, h: int, now_ns: int) -> None:
        """Processes and validates an ended motion segment."""
        seg = self._segmenter.pop_segment()
        if seg is None or len(seg.frames) < 2:
            self._restart_countdown(now_ns)
            return

        # Prepare observations for validator
        observations = [
            HandObservation(
                label=self.target_hand.value.capitalize(),
                label_score=1.0,
                presence_score=1.0,
                landmarks_image=f.landmarks_image,
                landmarks_world=f.landmarks_world,
            )
            for f in seg.frames
        ]
        timestamps = [f.timestamp_ns for f in seg.frames]

        is_valid, reject_reason, msg, path_length, valid_indices = RecordingValidator.validate_dynamic_recording(
            hand_observations=observations,
            timestamps_ns=timestamps,
            target_hand=self.target_hand,
            frame_width=w,
            frame_height=h,
        )

        if not is_valid:
            self._feedback = f"{msg} Retrying repetition {self._current_repetition + 1}..."
            self._restart_countdown(now_ns)
            return

        # Extract step vectors
        ref_wrist = seg.frames[0].wrist_corrected
        palm_scale = seg.segment_palm_scale
        steps = []
        for f in seg.frames:
            s_vec = extract_dynamic_step_features(
                landmarks_world=f.landmarks_world,
                landmarks_image=f.landmarks_image,
                frame_width=w,
                frame_height=h,
                ref_wrist_image=ref_wrist,
                segment_palm_scale=palm_scale,
            )
            steps.append(s_vec)

        steps_arr = np.stack(steps, axis=0)  # shape (N, 17)
        resampled = resample_step_vectors(steps_arr, seg.timestamps_ms)
        if resampled is None:
            self._feedback = f"Excessive tracking gap in repetition {self._current_repetition + 1}. Please retry..."
            self._restart_countdown(now_ns)
            return

        # Successfully recorded repetition
        self._collected_repetitions.append((seg, resampled))
        self._current_repetition += 1

        if self._current_repetition >= self.samples_required:
            self._finish_session()
        else:
            self._feedback = f"Repetition {self._current_repetition} saved! Get ready for next repetition..."
            self._restart_countdown(now_ns)

    def _finish_session(self) -> None:
        """Runs consistency check across repetitions and compiles RecordingResult."""
        all_resampled = [r[1] for r in self._collected_repetitions]
        is_consistent, max_dtw = check_dynamic_sample_consistency(all_resampled)

        preprocess_json = json.dumps({"flip_h": True, "normalizer_version": 1})
        samples_list: List[GestureSample] = []
        total_duration = 0

        for idx, (seg, resampled) in enumerate(self._collected_repetitions):
            total_duration += seg.duration_ms
            img_landmarks = np.stack([f.landmarks_image for f in seg.frames], axis=0)
            world_landmarks = np.stack([f.landmarks_world for f in seg.frames], axis=0)
            ts_ms = seg.timestamps_ms.astype(np.int32)

            sample = GestureSample(
                id=None,
                gesture_id=0,
                sample_index=idx,
                frame_count=len(seg.frames),
                duration_ms=seg.duration_ms,
                landmarks_image=img_landmarks,
                landmarks_world=world_landmarks,
                timestamps_ms=ts_ms,
                frame_aspect_ratio=self._frame_aspect_ratio,
                tracker_model_id=MODEL_VERSION,
                preprocess_json=preprocess_json,
            )
            samples_list.append(sample)

        total_frames = sum(s.frame_count for s in samples_list)
        fps = (total_frames / (total_duration / 1000.0)) if total_duration > 0 else 0.0

        if not is_consistent:
            self._state = RecorderState.FAILED
            self._feedback = (
                f"Repetitions differed too much (DTW distance {max_dtw:.2f} > {DYNAMIC_D_MAX}). "
                f"Please record more consistent movements."
            )
            self._result = RecordingResult(
                gesture_type=GestureType.DYNAMIC,
                hand=self.target_hand,
                samples=(),
                duration_ms=total_duration,
                effective_fps=fps,
                valid=False,
                reject_reason=RejectReason.INCONSISTENT_SAMPLES,
                feedback_key="INCONSISTENT_SAMPLES",
            )
            return

        self._state = RecorderState.COMPLETED
        self._feedback = f"Successfully recorded {len(samples_list)} dynamic repetitions! (max DTW: {max_dtw:.2f})"
        self._result = RecordingResult(
            gesture_type=GestureType.DYNAMIC,
            hand=self.target_hand,
            samples=tuple(samples_list),
            duration_ms=total_duration,
            effective_fps=fps,
            valid=True,
            reject_reason=None,
            feedback_key="SUCCESS",
        )

    def get_result(self) -> Optional[RecordingResult]:
        return self._result

