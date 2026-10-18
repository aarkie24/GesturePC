"""Motion segmenter detecting start/end of dynamic gestures from hand speed (Section 7.5)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
from typing import Deque, List, Optional, Tuple
import numpy as np

from app.constants import (
    END_IDLE_MS,
    MAX_INTERP_GAP_MS,
    MAX_SEGMENT_MS,
    MOTION_END_SPEED,
    MOTION_START_MS,
    MOTION_START_SPEED,
    SEGMENT_LOOKBACK_MS,
)
from gestures.normalizer import (
    aspect_correct_image_landmarks,
    compute_palm_unit_image,
)


class SegmenterState(Enum):
    IDLE = auto()
    ACTIVE = auto()
    ENDED = auto()
    ABORTED = auto()


@dataclass(frozen=True)
class SegmentFrame:
    """Frame observation cached within a motion segment."""
    landmarks_world: np.ndarray  # shape (21, 3)
    landmarks_image: np.ndarray  # shape (21, 3)
    timestamp_ns: int
    wrist_corrected: np.ndarray  # shape (2,)
    palm_unit: float  # in aspect-corrected image space


@dataclass(frozen=True)
class MotionSegment:
    """A completed physical motion segment bounded by onset and idle rest."""
    frames: Tuple[SegmentFrame, ...]
    segment_palm_scale: float
    start_ts_ns: int
    end_ts_ns: int
    duration_ms: int

    @property
    def timestamps_ms(self) -> np.ndarray:
        """Relative timestamps in milliseconds starting at 0."""
        if not self.frames:
            return np.empty((0,), dtype=np.float32)
        base = self.frames[0].timestamp_ns
        return np.array([(f.timestamp_ns - base) / 1e6 for f in self.frames], dtype=np.float32)

    @property
    def wrist_path_length_palm(self) -> float:
        """Wrist path length in palm units over the segment."""
        if len(self.frames) < 2:
            return 0.0
        scale = max(self.segment_palm_scale, 1e-4)
        wrists = np.array([f.wrist_corrected for f in self.frames])
        diffs = np.linalg.norm(np.diff(wrists, axis=0), axis=1)
        return float(np.sum(diffs) / scale)


class MotionSegmenter:
    """Identical motion segmenter used by recording and live recognition (Section 7.5).
    
    - Finite-difference wrist speed in aspect-corrected image space divided by
      the running-median palm size (1 s window), smoothed with an 80 ms time constant.
    - IDLE -> ACTIVE when speed >= motion_start_speed (0.8 palm/s) for motion_start_ms (100 ms).
    - ACTIVE -> ENDED when speed <= motion_end_speed (0.3 palm/s) for end_idle_ms (250 ms),
      or segment reaches max_segment_ms (4500 ms).
    - ABORTED on a tracking gap > max_interp_gap_ms (150 ms) or hand missing/changed.
    - Ring buffer of segment_lookback_ms (300 ms) pre-motion frames.
    """

    def __init__(
        self,
        motion_start_speed: float = MOTION_START_SPEED,
        motion_start_ms: int = MOTION_START_MS,
        motion_end_speed: float = MOTION_END_SPEED,
        end_idle_ms: int = END_IDLE_MS,
        segment_lookback_ms: int = SEGMENT_LOOKBACK_MS,
        max_segment_ms: int = MAX_SEGMENT_MS,
        max_interp_gap_ms: int = MAX_INTERP_GAP_MS,
    ) -> None:
        self.motion_start_speed = motion_start_speed
        self.motion_start_ms = motion_start_ms
        self.motion_end_speed = motion_end_speed
        self.end_idle_ms = end_idle_ms
        self.segment_lookback_ms = segment_lookback_ms
        self.max_segment_ms = max_segment_ms
        self.max_interp_gap_ms = max_interp_gap_ms

        self._state = SegmenterState.IDLE
        self._lookback_buffer: Deque[SegmentFrame] = deque()
        self._palm_history: Deque[Tuple[int, float]] = deque()  # (ts_ns, palm_size)
        self._active_frames: List[SegmentFrame] = []

        self._last_wrist_pos: Optional[np.ndarray] = None
        self._last_ts_ns: int = 0
        self._smoothed_speed: float = 0.0

        self._motion_start_accum_ms: float = 0.0
        self._motion_end_accum_ms: float = 0.0
        self._active_start_ts_ns: int = 0
        self._completed_segment: Optional[MotionSegment] = None

    @property
    def state(self) -> SegmenterState:
        return self._state

    @property
    def smoothed_speed(self) -> float:
        return self._smoothed_speed

    def reset(self) -> None:
        """Resets all internal segmenter state to IDLE."""
        self._state = SegmenterState.IDLE
        self._lookback_buffer.clear()
        self._palm_history.clear()
        self._active_frames.clear()
        self._last_wrist_pos = None
        self._last_ts_ns = 0
        self._smoothed_speed = 0.0
        self._motion_start_accum_ms = 0.0
        self._motion_end_accum_ms = 0.0
        self._active_start_ts_ns = 0
        self._completed_segment = None

    def pop_segment(self) -> Optional[MotionSegment]:
        """Retrieves and clears the completed motion segment, transitioning back to IDLE."""
        seg = self._completed_segment
        self._completed_segment = None
        if self._state in (SegmenterState.ENDED, SegmenterState.ABORTED):
            self._state = SegmenterState.IDLE
            self._motion_start_accum_ms = 0.0
            self._motion_end_accum_ms = 0.0
            self._active_frames.clear()
        return seg

    def update(
        self,
        landmarks_world: Optional[np.ndarray],
        landmarks_image: Optional[np.ndarray],
        frame_width: int,
        frame_height: int,
        timestamp_ns: int,
    ) -> SegmenterState:
        """Processes a single frame observation and updates the segmenter state machine."""
        # Handle tracking loss
        if landmarks_world is None or landmarks_image is None:
            if self._state == SegmenterState.ACTIVE:
                # If gap exceeds threshold while active, abort
                if self._last_ts_ns > 0 and (timestamp_ns - self._last_ts_ns) / 1e6 > self.max_interp_gap_ms:
                    self._state = SegmenterState.ABORTED
                    self._active_frames.clear()
            elif self._state == SegmenterState.IDLE:
                self._lookback_buffer.clear()
                self._motion_start_accum_ms = 0.0
                self._last_wrist_pos = None
                self._smoothed_speed = 0.0
            self._last_ts_ns = timestamp_ns
            return self._state

        # Check gap between tracked frames
        if self._last_ts_ns > 0:
            dt_gap_ms = (timestamp_ns - self._last_ts_ns) / 1e6
            if dt_gap_ms > self.max_interp_gap_ms and self._state == SegmenterState.ACTIVE:
                self._state = SegmenterState.ABORTED
                self._active_frames.clear()
                self._last_ts_ns = timestamp_ns
                return self._state

        # Compute aspect-corrected wrist & palm unit
        corrected_image = aspect_correct_image_landmarks(landmarks_image, frame_width, frame_height)
        curr_wrist = corrected_image[0, :2]
        curr_palm = compute_palm_unit_image(corrected_image)

        # Update running palm history (1 s window)
        if curr_palm > 1e-4:
            self._palm_history.append((timestamp_ns, curr_palm))
        one_sec_ago = timestamp_ns - 1_000_000_000
        while self._palm_history and self._palm_history[0][0] < one_sec_ago:
            self._palm_history.popleft()

        median_palm = (
            float(np.median([p[1] for p in self._palm_history]))
            if self._palm_history
            else max(curr_palm, 1e-4)
        )
        median_palm = max(median_palm, 1e-4)

        # Compute speed
        dt_s = (timestamp_ns - self._last_ts_ns) / 1e9 if self._last_ts_ns > 0 else 0.0
        if self._last_wrist_pos is not None and 0.001 <= dt_s <= 0.5:
            delta_px = float(np.linalg.norm(curr_wrist - self._last_wrist_pos))
            delta_palm = delta_px / median_palm
            raw_speed = delta_palm / dt_s

            # 80 ms EMA smoothing
            alpha = 1.0 - np.exp(-dt_s / 0.080)
            self._smoothed_speed += alpha * (raw_speed - self._smoothed_speed)
        else:
            self._smoothed_speed = 0.0

        self._last_wrist_pos = curr_wrist.copy()
        dt_ms = dt_s * 1000.0 if dt_s > 0 else 33.3
        self._last_ts_ns = timestamp_ns

        frame_obs = SegmentFrame(
            landmarks_world=landmarks_world.copy(),
            landmarks_image=landmarks_image.copy(),
            timestamp_ns=timestamp_ns,
            wrist_corrected=curr_wrist.copy(),
            palm_unit=curr_palm,
        )

        # Update state machine
        if self._state == SegmenterState.IDLE:
            # Maintain lookback buffer
            self._lookback_buffer.append(frame_obs)
            lookback_cutoff = timestamp_ns - int(self.segment_lookback_ms * 1e6)
            while self._lookback_buffer and self._lookback_buffer[0].timestamp_ns < lookback_cutoff:
                self._lookback_buffer.popleft()

            if self._smoothed_speed >= self.motion_start_speed:
                self._motion_start_accum_ms += dt_ms
                if self._motion_start_accum_ms >= self.motion_start_ms:
                    # Transition to ACTIVE! Include lookback buffer frames
                    self._state = SegmenterState.ACTIVE
                    self._active_start_ts_ns = (
                        self._lookback_buffer[0].timestamp_ns if self._lookback_buffer else timestamp_ns
                    )
                    self._active_frames = list(self._lookback_buffer)
                    self._motion_end_accum_ms = 0.0
            else:
                self._motion_start_accum_ms = 0.0

        elif self._state == SegmenterState.ACTIVE:
            self._active_frames.append(frame_obs)
            total_active_ms = (timestamp_ns - self._active_start_ts_ns) / 1e6

            # Check timeout
            if total_active_ms >= self.max_segment_ms:
                self._finish_segment()
                return self._state

            # Check motion end
            if self._smoothed_speed <= self.motion_end_speed:
                self._motion_end_accum_ms += dt_ms
                if self._motion_end_accum_ms >= self.end_idle_ms:
                    self._finish_segment()
                    return self._state
            else:
                self._motion_end_accum_ms = 0.0

        elif self._state in (SegmenterState.ENDED, SegmenterState.ABORTED):
            # Auto-reset on next frame
            self.reset()
            self._lookback_buffer.append(frame_obs)

        return self._state

    def _finish_segment(self) -> None:
        """Finishes active segment and packages MotionSegment."""
        if not self._active_frames:
            self._state = SegmenterState.IDLE
            return

        palms = [f.palm_unit for f in self._active_frames if f.palm_unit > 1e-4]
        seg_palm_scale = float(np.median(palms)) if palms else 1.0
        start_ts = self._active_frames[0].timestamp_ns
        end_ts = self._active_frames[-1].timestamp_ns
        duration_ms = int((end_ts - start_ts) / 1e6)

        self._completed_segment = MotionSegment(
            frames=tuple(self._active_frames),
            segment_palm_scale=seg_palm_scale,
            start_ts_ns=start_ts,
            end_ts_ns=end_ts,
            duration_ms=duration_ms,
        )
        self._state = SegmenterState.ENDED
