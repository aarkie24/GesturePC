"""Static gesture template matching using Mean Landmark Deviation (MLD) and margin ratio test."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence, Tuple
import numpy as np

from domain.enums import Hand, RejectReason
from gestures.normalizer import mean_landmark_deviation


@dataclass(frozen=True)
class StaticTemplate:
    """Compiled in-memory template for an enabled static gesture."""
    gesture_id: int
    gesture_name: str
    hand: Hand
    samples: Tuple[np.ndarray, ...]  # Each sample is shape (20, 3) or (60,)
    base_threshold: float
    threshold_scale: float = 1.0

    def effective_threshold(self, global_sensitivity: float = 1.0) -> float:
        """Computes effective threshold: base * sensitivity * threshold_scale."""
        return float(self.base_threshold * global_sensitivity * self.threshold_scale)


@dataclass(frozen=True)
class StaticMatchResult:
    """Result of matching a single live hand pose against compiled templates."""
    best_gesture_id: Optional[int] = None
    best_gesture_name: str = ""
    best_distance: float = float("inf")
    second_gesture_id: Optional[int] = None
    second_gesture_name: str = ""
    second_distance: float = float("inf")
    threshold: float = 0.0
    margin_ratio: float = 0.0
    accepted: bool = False
    reject_reason: Optional[RejectReason] = None


class StaticMatcher:
    """Matches live static feature vectors against a collection of StaticTemplates."""

    @staticmethod
    def match(
        live_features: np.ndarray,
        selected_hand: Hand,
        templates: Sequence[StaticTemplate],
        global_sensitivity: float = 1.0,
        margin_ratio_limit: float = 0.80,
    ) -> StaticMatchResult:
        """Matches a live feature vector against enabled templates matching the selected hand.
        
        Section 7.4 Algorithm:
        1. For every template matching selected_hand:
           d_g = min over its samples of MLD(live, sample)
        2. Sort ascending: best (g1, d1), second (g2, d2)
        3. Accepted iff d1 <= effective(g1) and (no g2 or d1 / max(d2, eps) <= margin_ratio)
        """
        # Filter matching hand
        eligible = [t for t in templates if t.hand == selected_hand or t.hand == Hand.EITHER]
        if not eligible:
            return StaticMatchResult(
                accepted=False,
                reject_reason=RejectReason.ABOVE_THRESHOLD,
            )

        # Compute minimum distance per template
        candidates = []
        for tmpl in eligible:
            if not tmpl.samples:
                continue
            min_d = min(mean_landmark_deviation(live_features, s) for s in tmpl.samples)
            candidates.append((tmpl, min_d))

        if not candidates:
            return StaticMatchResult(
                accepted=False,
                reject_reason=RejectReason.ABOVE_THRESHOLD,
            )

        # Sort ascending by distance
        candidates.sort(key=lambda c: c[1])

        best_tmpl, best_dist = candidates[0]
        eff_threshold = best_tmpl.effective_threshold(global_sensitivity)

        if len(candidates) > 1:
            second_tmpl, second_dist = candidates[1]
            actual_margin = best_dist / max(second_dist, 1e-6)
            second_id = second_tmpl.gesture_id
            second_name = second_tmpl.gesture_name
        else:
            second_dist = float("inf")
            actual_margin = 0.0
            second_id = None
            second_name = ""

        # Check conditions
        if best_dist > eff_threshold:
            return StaticMatchResult(
                best_gesture_id=best_tmpl.gesture_id,
                best_gesture_name=best_tmpl.gesture_name,
                best_distance=best_dist,
                second_gesture_id=second_id,
                second_gesture_name=second_name,
                second_distance=second_dist,
                threshold=eff_threshold,
                margin_ratio=actual_margin,
                accepted=False,
                reject_reason=RejectReason.ABOVE_THRESHOLD,
            )

        if len(candidates) > 1 and actual_margin > margin_ratio_limit:
            return StaticMatchResult(
                best_gesture_id=best_tmpl.gesture_id,
                best_gesture_name=best_tmpl.gesture_name,
                best_distance=best_dist,
                second_gesture_id=second_id,
                second_gesture_name=second_name,
                second_distance=second_dist,
                threshold=eff_threshold,
                margin_ratio=actual_margin,
                accepted=False,
                reject_reason=RejectReason.AMBIGUOUS_MARGIN,
            )

        # Accepted!
        return StaticMatchResult(
            best_gesture_id=best_tmpl.gesture_id,
            best_gesture_name=best_tmpl.gesture_name,
            best_distance=best_dist,
            second_gesture_id=second_id,
            second_gesture_name=second_name,
            second_distance=second_dist,
            threshold=eff_threshold,
            margin_ratio=actual_margin,
            accepted=True,
            reject_reason=None,
        )
