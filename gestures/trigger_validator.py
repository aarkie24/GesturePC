"""Trigger validation state machine managing stability, cooldowns, and rearming."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from app.constants import (
    COOLDOWN_MS,
    GLOBAL_COOLDOWN_MS,
    MAX_GAP_MS,
    REARM_RELEASE_MS,
    STABLE_DURATION_MS,
)
from domain.enums import TriggerState
from domain.ports import Clock


@dataclass
class _GestureTriggerTracker:
    """Internal tracking state for a specific gesture."""
    state: TriggerState = TriggerState.IDLE
    accumulated_ms: int = 0
    first_candidate_ts_ns: int = 0
    last_candidate_ts_ns: int = 0
    fired_ts_ns: int = 0
    rearm_start_ts_ns: int = 0


@dataclass(frozen=True)
class TriggerValidationResult:
    """Outcome of trigger validation for the current frame."""
    state: TriggerState
    accumulated_ms: int
    should_fire: bool


class TriggerValidator:
    """Enforces temporal stability, per-gesture cooldown, global cooldown, and rearming.
    
    Section 7.6: The ONLY component that owns time-based cooldown logic.
    """

    def __init__(
        self,
        clock: Clock,
        stable_duration_ms: int = STABLE_DURATION_MS,
        max_gap_ms: int = MAX_GAP_MS,
        cooldown_ms: int = COOLDOWN_MS,
        rearm_release_ms: int = REARM_RELEASE_MS,
        global_cooldown_ms: int = GLOBAL_COOLDOWN_MS,
    ) -> None:
        self._clock = clock
        self.stable_duration_ms = stable_duration_ms
        self.max_gap_ms = max_gap_ms
        self.cooldown_ms = cooldown_ms
        self.rearm_release_ms = rearm_release_ms
        self.global_cooldown_ms = global_cooldown_ms

        self._trackers: Dict[int, _GestureTriggerTracker] = {}
        self._last_global_fired_ts_ns: int = 0

    def update(
        self,
        candidate_gesture_id: Optional[int],
        frame_ts_ns: int,
    ) -> TriggerValidationResult:
        """Evaluates accepted frame candidate against stability, cooldown and rearming.
        
        Args:
            candidate_gesture_id: The ID of the accepted frame candidate, or None if no candidate.
            frame_ts_ns: Monotonic timestamp of the frame in nanoseconds.
            
        Returns:
            TriggerValidationResult with current state, accumulated time, and fire flag.
        """
        # If no candidate, update release timers for all gestures currently in REARMING or COOLDOWN
        if candidate_gesture_id is None:
            self._update_non_candidates(candidate_id=None, frame_ts_ns=frame_ts_ns)
            return TriggerValidationResult(
                state=TriggerState.IDLE,
                accumulated_ms=0,
                should_fire=False,
            )

        tracker = self._get_tracker(candidate_gesture_id)

        # Update other gestures not matching candidate_gesture_id
        self._update_non_candidates(candidate_id=candidate_gesture_id, frame_ts_ns=frame_ts_ns)

        # Handle current state of the candidate gesture
        if tracker.state == TriggerState.IDLE:
            tracker.state = TriggerState.ACCUMULATING
            tracker.accumulated_ms = 0
            tracker.first_candidate_ts_ns = frame_ts_ns
            tracker.last_candidate_ts_ns = frame_ts_ns
            return TriggerValidationResult(
                state=TriggerState.ACCUMULATING,
                accumulated_ms=0,
                should_fire=False,
            )

        elif tracker.state == TriggerState.ACCUMULATING:
            gap_ms = int((frame_ts_ns - tracker.last_candidate_ts_ns) / 1_000_000)
            if gap_ms > self.max_gap_ms:
                # Tracking gap exceeded max_gap_ms -> reset to IDLE and restart
                tracker.state = TriggerState.ACCUMULATING
                tracker.accumulated_ms = 0
                tracker.first_candidate_ts_ns = frame_ts_ns
                tracker.last_candidate_ts_ns = frame_ts_ns
                return TriggerValidationResult(
                    state=TriggerState.ACCUMULATING,
                    accumulated_ms=0,
                    should_fire=False,
                )

            # Accumulate time
            tracker.last_candidate_ts_ns = frame_ts_ns
            tracker.accumulated_ms = int(
                (frame_ts_ns - tracker.first_candidate_ts_ns) / 1_000_000
            )

            if tracker.accumulated_ms >= self.stable_duration_ms:
                # Check global cooldown
                global_elapsed_ms = int((frame_ts_ns - self._last_global_fired_ts_ns) / 1_000_000)
                if self._last_global_fired_ts_ns > 0 and global_elapsed_ms < self.global_cooldown_ms:
                    # Suppressed by global cooldown
                    return TriggerValidationResult(
                        state=TriggerState.ACCUMULATING,
                        accumulated_ms=tracker.accumulated_ms,
                        should_fire=False,
                    )

                # Fire!
                tracker.state = TriggerState.FIRED
                tracker.fired_ts_ns = frame_ts_ns
                tracker.rearm_start_ts_ns = 0
                self._last_global_fired_ts_ns = frame_ts_ns
                return TriggerValidationResult(
                    state=TriggerState.FIRED,
                    accumulated_ms=tracker.accumulated_ms,
                    should_fire=True,
                )

            return TriggerValidationResult(
                state=TriggerState.ACCUMULATING,
                accumulated_ms=tracker.accumulated_ms,
                should_fire=False,
            )

        elif tracker.state == TriggerState.FIRED:
            # Immediately enter COOLDOWN after FIRED
            tracker.state = TriggerState.COOLDOWN
            return TriggerValidationResult(
                state=TriggerState.COOLDOWN,
                accumulated_ms=0,
                should_fire=False,
            )

        elif tracker.state == TriggerState.COOLDOWN:
            elapsed_ms = int((frame_ts_ns - tracker.fired_ts_ns) / 1_000_000)
            if elapsed_ms >= self.cooldown_ms:
                tracker.state = TriggerState.REARMING
                tracker.rearm_start_ts_ns = 0  # Still being held, so release not started
            return TriggerValidationResult(
                state=tracker.state,
                accumulated_ms=0,
                should_fire=False,
            )

        elif tracker.state == TriggerState.REARMING:
            # Candidate is still active, so release timer cannot accumulate
            tracker.rearm_start_ts_ns = 0
            return TriggerValidationResult(
                state=TriggerState.REARMING,
                accumulated_ms=0,
                should_fire=False,
            )

        return TriggerValidationResult(
            state=TriggerState.IDLE,
            accumulated_ms=0,
            should_fire=False,
        )

    def _update_non_candidates(self, candidate_id: Optional[int], frame_ts_ns: int) -> None:
        """Updates release and cooldown timers for gestures that are NOT the active candidate."""
        for gid, tracker in self._trackers.items():
            if gid == candidate_id:
                continue

            if tracker.state == TriggerState.ACCUMULATING:
                gap_ms = int((frame_ts_ns - tracker.last_candidate_ts_ns) / 1_000_000)
                if gap_ms > self.max_gap_ms:
                    tracker.state = TriggerState.IDLE
                    tracker.accumulated_ms = 0

            if tracker.state == TriggerState.FIRED:
                tracker.state = TriggerState.COOLDOWN

            if tracker.state == TriggerState.COOLDOWN:
                elapsed_ms = int((frame_ts_ns - tracker.fired_ts_ns) / 1_000_000)
                if elapsed_ms >= self.cooldown_ms:
                    tracker.state = TriggerState.REARMING
                    cooldown_ns = int(self.cooldown_ms * 1_000_000)
                    tracker.rearm_start_ts_ns = max(tracker.fired_ts_ns + cooldown_ns, frame_ts_ns - (elapsed_ms - self.cooldown_ms) * 1_000_000)

            if tracker.state == TriggerState.REARMING:
                if tracker.rearm_start_ts_ns == 0:
                    tracker.rearm_start_ts_ns = frame_ts_ns
                else:
                    released_ms = int((frame_ts_ns - tracker.rearm_start_ts_ns) / 1_000_000)
                    if released_ms >= self.rearm_release_ms:
                        # Full release observed -> gesture is fully rearmed to IDLE
                        tracker.state = TriggerState.IDLE
                        tracker.accumulated_ms = 0

    def _get_tracker(self, gesture_id: int) -> _GestureTriggerTracker:
        if gesture_id not in self._trackers:
            self._trackers[gesture_id] = _GestureTriggerTracker()
        return self._trackers[gesture_id]

    def can_fire_dynamic(self, gesture_id: int, frame_ts_ns: int) -> bool:
        """Checks if a dynamic gesture can fire given global cooldown and gesture cooldown."""
        global_elapsed_ms = int((frame_ts_ns - self._last_global_fired_ts_ns) / 1_000_000)
        if self._last_global_fired_ts_ns > 0 and global_elapsed_ms < self.global_cooldown_ms:
            return False

        tracker = self._get_tracker(gesture_id)
        if tracker.state in (TriggerState.FIRED, TriggerState.COOLDOWN):
            elapsed_ms = int((frame_ts_ns - tracker.fired_ts_ns) / 1_000_000)
            if elapsed_ms < self.cooldown_ms:
                return False
        return True

    def record_fire(self, gesture_id: int, frame_ts_ns: int) -> None:
        """Records a fire event for a gesture, setting cooldowns."""
        tracker = self._get_tracker(gesture_id)
        tracker.state = TriggerState.COOLDOWN
        tracker.fired_ts_ns = frame_ts_ns
        tracker.rearm_start_ts_ns = 0
        tracker.accumulated_ms = 0
        self._last_global_fired_ts_ns = frame_ts_ns

    def reset_accumulating(self) -> None:
        """Resets all accumulating static candidates to IDLE (Section 7.5)."""
        for tracker in self._trackers.values():
            if tracker.state == TriggerState.ACCUMULATING:
                tracker.state = TriggerState.IDLE
                tracker.accumulated_ms = 0

    def reset_gesture(self, gesture_id: int) -> None:
        """Resets trigger state for a single gesture."""
        if gesture_id in self._trackers:
            self._trackers[gesture_id] = _GestureTriggerTracker()

    def reset(self) -> None:
        """Resets all trigger validator states (e.g. on mode switch or camera restart)."""
        self._trackers.clear()
        self._last_global_fired_ts_ns = 0

