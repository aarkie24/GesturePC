"""Pure recognition engine orchestrating hand selection, normalization, matching, and trigger validation."""

from __future__ import annotations

import datetime
import uuid
from typing import Optional, Tuple
import numpy as np

from app.constants import (
    MARGIN_RATIO,
    SENSITIVITY,
    STATIC_MAX_SPEED,
)
from domain.enums import GestureType, Hand, RejectReason, TrackingStatus, TriggerState
from domain.models import (
    FrameAnalysis,
    RecognitionEvent,
    TemplateSnapshot,
    TrackingResult,
)
from domain.ports import Clock
from gestures.feature_extractor import extract_static_features
from gestures.hand_selector import HandSelector
from gestures.normalizer import (
    DegenerateHandError,
    aspect_correct_image_landmarks,
    compute_palm_unit_image,
)
from gestures.static_matcher import StaticMatcher, StaticTemplate
from gestures.trigger_validator import TriggerValidator


class RecognitionEngine:
    """Orchestrates pure hand gesture recognition without external side effects or I/O."""

    def __init__(
        self,
        clock: Clock,
        trigger_validator: Optional[TriggerValidator] = None,
    ) -> None:
        self._clock = clock
        self._trigger_validator = trigger_validator or TriggerValidator(clock=clock)

        # State for hand speed calculation (Section 7.5: 80 ms time constant smoothing)
        self._last_wrist_pos: Optional[np.ndarray] = None
        self._last_ts_ns: int = 0
        self._last_palm_unit: float = 1.0
        self._smoothed_speed: float = 0.0

    @property
    def trigger_validator(self) -> TriggerValidator:
        return self._trigger_validator

    def reset(self) -> None:
        """Resets engine state and trigger validator."""
        self._trigger_validator.reset()
        self._last_wrist_pos = None
        self._last_ts_ns = 0
        self._last_palm_unit = 1.0
        self._smoothed_speed = 0.0

    def process(
        self,
        tracking_result: TrackingResult,
        snapshot: TemplateSnapshot,
        tracked_hand: Hand = Hand.RIGHT,
        global_sensitivity: float = SENSITIVITY,
        margin_ratio_limit: float = MARGIN_RATIO,
    ) -> Tuple[FrameAnalysis, Optional[RecognitionEvent]]:
        """Processes a single tracking result against compiled templates.
        
        Pure pipeline:
        1. Select hand (HandSelector)
        2. Compute hand speed & check motion state
        3. Extract normalized static features
        4. Match against StaticTemplates in snapshot
        5. Validate candidate stability & cooldown with TriggerValidator
        6. Produce FrameAnalysis and optional RecognitionEvent
        """
        ts_ns = tracking_result.capture_ts_ns or self._clock.monotonic_ns()
        w, h = tracking_result.frame_size

        # 1. Hand Selection
        selection = HandSelector.select_hand(tracking_result, tracked_hand)
        if selection.hand is None or selection.status != TrackingStatus.OK:
            val_res = self._trigger_validator.update(None, ts_ns)
            analysis = FrameAnalysis(
                frame_id=tracking_result.frame_id,
                capture_ts_ns=ts_ns,
                hand_status=selection.status,
                motion_state="NO_HAND",
                hand_speed=0.0,
                best_gesture_id=None,
                best_distance=float("inf"),
                second_gesture_id=None,
                second_distance=float("inf"),
                threshold=0.0,
                margin_ratio=0.0,
                outcome=selection.reject_reason.value if selection.reject_reason else "NO_HAND",
                reject_reason=selection.reject_reason,
                trigger_state=val_res.state,
                accumulated_ms=val_res.accumulated_ms,
            )
            return analysis, None

        hand = selection.hand
        hand_laterality = Hand.RIGHT if hand.label.capitalize() == "Right" else Hand.LEFT

        # 2. Hand Speed Computation
        corrected_image = aspect_correct_image_landmarks(hand.landmarks_image, w, h)
        curr_wrist = corrected_image[0, :2]
        curr_palm = compute_palm_unit_image(corrected_image)
        if curr_palm > 1e-4:
            self._last_palm_unit = curr_palm

        speed = 0.0
        if self._last_wrist_pos is not None and self._last_ts_ns > 0:
            dt_s = (ts_ns - self._last_ts_ns) / 1e9
            if 0.001 <= dt_s <= 0.5:
                delta_px = float(np.linalg.norm(curr_wrist - self._last_wrist_pos))
                delta_palm = delta_px / max(self._last_palm_unit, 1e-4)
                raw_speed = delta_palm / dt_s

                # Exponential smoothing with 80 ms time constant (Section 7.5)
                alpha = 1.0 - np.exp(-dt_s / 0.080)
                self._smoothed_speed += alpha * (raw_speed - self._smoothed_speed)
                speed = self._smoothed_speed

        self._last_wrist_pos = curr_wrist.copy()
        self._last_ts_ns = ts_ns

        motion_state = "MOVING" if speed > STATIC_MAX_SPEED else "STATIONARY"

        # If hand is moving, static matching is gated out (Section 7.4 / 7.5)
        if motion_state == "MOVING":
            val_res = self._trigger_validator.update(None, ts_ns)
            analysis = FrameAnalysis(
                frame_id=tracking_result.frame_id,
                capture_ts_ns=ts_ns,
                hand_status=TrackingStatus.OK,
                motion_state=motion_state,
                hand_speed=speed,
                best_gesture_id=None,
                best_distance=float("inf"),
                second_gesture_id=None,
                second_distance=float("inf"),
                threshold=0.0,
                margin_ratio=0.0,
                outcome="MOVING",
                reject_reason=RejectReason.MOVING,
                trigger_state=val_res.state,
                accumulated_ms=val_res.accumulated_ms,
            )
            return analysis, None

        # 3. Extract Static Features
        try:
            live_features = extract_static_features(hand.landmarks_world)
        except DegenerateHandError:
            val_res = self._trigger_validator.update(None, ts_ns)
            analysis = FrameAnalysis(
                frame_id=tracking_result.frame_id,
                capture_ts_ns=ts_ns,
                hand_status=TrackingStatus.OK,
                motion_state=motion_state,
                hand_speed=speed,
                best_gesture_id=None,
                best_distance=float("inf"),
                second_gesture_id=None,
                second_distance=float("inf"),
                threshold=0.0,
                margin_ratio=0.0,
                outcome="DEGENERATE_HAND",
                reject_reason=RejectReason.DEGENERATE_HAND,
                trigger_state=val_res.state,
                accumulated_ms=val_res.accumulated_ms,
            )
            return analysis, None

        # 4. Match against static templates in current snapshot
        static_templates = [t for t in snapshot.templates if isinstance(t, StaticTemplate)]
        match_result = StaticMatcher.match(
            live_features=live_features,
            selected_hand=hand_laterality,
            templates=static_templates,
            global_sensitivity=global_sensitivity,
            margin_ratio_limit=margin_ratio_limit,
        )

        # 5. Trigger Validation
        candidate_id = match_result.best_gesture_id if match_result.accepted else None
        val_res = self._trigger_validator.update(candidate_id, ts_ns)

        outcome_str = "MATCH" if match_result.accepted else (
            match_result.reject_reason.value if match_result.reject_reason else "NO_MATCH"
        )

        analysis = FrameAnalysis(
            frame_id=tracking_result.frame_id,
            capture_ts_ns=ts_ns,
            hand_status=TrackingStatus.OK,
            motion_state=motion_state,
            hand_speed=speed,
            best_gesture_id=match_result.best_gesture_id,
            best_distance=match_result.best_distance,
            second_gesture_id=match_result.second_gesture_id,
            second_distance=match_result.second_distance,
            threshold=match_result.threshold,
            margin_ratio=match_result.margin_ratio,
            outcome=outcome_str,
            reject_reason=match_result.reject_reason,
            trigger_state=val_res.state,
            accumulated_ms=val_res.accumulated_ms,
        )

        # 6. Build RecognitionEvent if trigger validator fired
        event: Optional[RecognitionEvent] = None
        if val_res.should_fire and match_result.best_gesture_id is not None:
            now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
            event = RecognitionEvent(
                event_id=str(uuid.uuid4()),
                gesture_id=match_result.best_gesture_id,
                gesture_name=match_result.best_gesture_name,
                gesture_type=GestureType.STATIC,
                hand=hand_laterality,
                capture_ts_ns=ts_ns,
                timestamp_utc=now_utc,
                distance=match_result.best_distance,
                threshold=match_result.threshold,
                margin_ratio=match_result.margin_ratio,
            )

        return analysis, event
