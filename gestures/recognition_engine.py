"""Pure recognition engine orchestrating hand selection, normalization, matching, and trigger validation."""

from __future__ import annotations

import datetime
import uuid
from typing import Optional, Tuple
import numpy as np

from app.constants import (
    DYNAMIC_MARGIN_RATIO,
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
from gestures.dynamic_matcher import DynamicMatcher, DynamicTemplate
from gestures.feature_extractor import (
    extract_dynamic_step_features,
    extract_static_features,
)
from gestures.hand_selector import HandSelector
from gestures.normalizer import (
    DegenerateHandError,
    aspect_correct_image_landmarks,
    compute_palm_unit_image,
)
from gestures.resampler import resample_step_vectors
from gestures.segmenter import MotionSegmenter, SegmenterState
from gestures.static_matcher import StaticMatcher, StaticTemplate
from gestures.trigger_validator import TriggerValidator


class RecognitionEngine:
    """Orchestrates pure hand gesture recognition without external side effects or I/O."""

    def __init__(
        self,
        clock: Clock,
        trigger_validator: Optional[TriggerValidator] = None,
        segmenter: Optional[MotionSegmenter] = None,
    ) -> None:
        self._clock = clock
        self._trigger_validator = trigger_validator or TriggerValidator(clock=clock)
        self._segmenter = segmenter or MotionSegmenter()

    @property
    def trigger_validator(self) -> TriggerValidator:
        return self._trigger_validator

    @property
    def segmenter(self) -> MotionSegmenter:
        return self._segmenter

    def reset(self) -> None:
        """Resets engine state, trigger validator, and motion segmenter."""
        self._trigger_validator.reset()
        self._segmenter.reset()

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
        2. Feed MotionSegmenter to track dynamic movements
        3. Arbitrate static vs dynamic gestures (Section 7.5)
        4. If segment completed (ENDED): match against DynamicTemplates
        5. If IDLE and still: match against StaticTemplates and evaluate TriggerValidator
        6. Produce FrameAnalysis and optional RecognitionEvent
        """
        ts_ns = tracking_result.capture_ts_ns or self._clock.monotonic_ns()
        w, h = tracking_result.frame_size

        # 1. Hand Selection
        selection = HandSelector.select_hand(tracking_result, tracked_hand)
        if selection.hand is None or selection.status != TrackingStatus.OK:
            self._segmenter.update(None, None, w, h, ts_ns)
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

        # 2. Update Motion Segmenter & speed
        seg_state = self._segmenter.update(
            landmarks_world=hand.landmarks_world,
            landmarks_image=hand.landmarks_image,
            frame_width=w,
            frame_height=h,
            timestamp_ns=ts_ns,
        )
        speed = self._segmenter.smoothed_speed

        # 3. Static/Dynamic Arbitration (Section 7.5)
        # Case A: Motion segment ended -> match dynamic gesture once
        if seg_state == SegmenterState.ENDED:
            # Static accumulation restarts from zero (Section 7.5)
            self._trigger_validator.reset_accumulating()
            seg = self._segmenter.pop_segment()

            if seg is not None and len(seg.frames) >= 2:
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

                steps_arr = np.stack(steps, axis=0)
                resampled = resample_step_vectors(steps_arr, seg.timestamps_ms)

                if resampled is not None:
                    dyn_templates = [t for t in snapshot.templates if isinstance(t, DynamicTemplate)]
                    dyn_result = DynamicMatcher.match(
                        live_steps=resampled,
                        selected_hand=hand_laterality,
                        templates=dyn_templates,
                        global_sensitivity=global_sensitivity,
                        margin_ratio_limit=DYNAMIC_MARGIN_RATIO,
                    )

                    event: Optional[RecognitionEvent] = None
                    if dyn_result.accepted and dyn_result.best_gesture_id is not None:
                        if self._trigger_validator.can_fire_dynamic(dyn_result.best_gesture_id, ts_ns):
                            self._trigger_validator.record_fire(dyn_result.best_gesture_id, ts_ns)
                            now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
                            event = RecognitionEvent(
                                event_id=str(uuid.uuid4()),
                                gesture_id=dyn_result.best_gesture_id,
                                gesture_name=dyn_result.best_gesture_name,
                                gesture_type=GestureType.DYNAMIC,
                                hand=hand_laterality,
                                capture_ts_ns=ts_ns,
                                timestamp_utc=now_utc,
                                distance=dyn_result.best_distance,
                                threshold=dyn_result.threshold,
                                margin_ratio=dyn_result.margin_ratio,
                            )
                            outcome_str = "MATCH"
                            trigger_st = TriggerState.FIRED
                        else:
                            outcome_str = "COOLDOWN"
                            trigger_st = TriggerState.COOLDOWN
                    else:
                        outcome_str = "SEGMENT_NO_MATCH"
                        trigger_st = TriggerState.IDLE

                    analysis = FrameAnalysis(
                        frame_id=tracking_result.frame_id,
                        capture_ts_ns=ts_ns,
                        hand_status=TrackingStatus.OK,
                        motion_state="ENDED",
                        hand_speed=speed,
                        best_gesture_id=dyn_result.best_gesture_id,
                        best_distance=dyn_result.best_distance,
                        second_gesture_id=dyn_result.second_gesture_id,
                        second_distance=dyn_result.second_distance,
                        threshold=dyn_result.threshold,
                        margin_ratio=dyn_result.margin_ratio,
                        outcome=outcome_str,
                        reject_reason=dyn_result.reject_reason or (
                            None if dyn_result.accepted else RejectReason.SEGMENT_NO_MATCH
                        ),
                        trigger_state=trigger_st,
                        accumulated_ms=0,
                    )
                    return analysis, event

        # Case B: Segment is aborted
        if seg_state == SegmenterState.ABORTED:
            self._trigger_validator.reset_accumulating()
            self._segmenter.reset()

        # Case C: Hand moving or segmenter active -> static matching is gated out (Section 7.5)
        if seg_state == SegmenterState.ACTIVE or speed > STATIC_MAX_SPEED:
            val_res = self._trigger_validator.update(None, ts_ns)
            analysis = FrameAnalysis(
                frame_id=tracking_result.frame_id,
                capture_ts_ns=ts_ns,
                hand_status=TrackingStatus.OK,
                motion_state="MOVING",
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

        # Case D: IDLE & stationary -> static gesture matching
        motion_state = "STATIONARY"
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
