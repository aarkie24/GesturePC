"""Hand selection logic applying tracked_hand configuration to tracking results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from domain.enums import Hand, RejectReason, TrackingStatus
from domain.models import HandObservation, TrackingResult


@dataclass(frozen=True)
class SelectedHandResult:
    """Outcome of selecting a hand from a tracking result."""
    hand: Optional[HandObservation]
    status: TrackingStatus
    reject_reason: Optional[RejectReason] = None


class HandSelector:
    """Selects exactly one hand per frame according to Section 7.2 of the specification."""

    @staticmethod
    def select_hand(tracking_result: TrackingResult, tracked_hand: Hand) -> SelectedHandResult:
        """Applies the tracked_hand setting to a TrackingResult.
        
        Rules ( 7.2):
        - tracked_hand == RIGHT or LEFT:
            - exactly one detection with that label -> that hand is selected (status OK).
            - only a hand with other label -> status NO_HAND, reject_reason WRONG_HAND.
            - two detections with tracked label -> status NO_HAND, reject_reason AMBIGUOUS_HANDS.
        - tracked_hand == EITHER:
            - one detection -> selected (status OK).
            - two detections -> status NO_HAND, reject_reason AMBIGUOUS_HANDS.
        - any:
            - no detections -> status NO_HAND, reject_reason NO_HAND.
        """
        if tracking_result.status != TrackingStatus.OK or not tracking_result.hands:
            return SelectedHandResult(
                hand=None,
                status=TrackingStatus.NO_HAND,
                reject_reason=RejectReason.NO_HAND,
            )

        hands = tracking_result.hands

        if tracked_hand == Hand.EITHER:
            if len(hands) == 1:
                return SelectedHandResult(
                    hand=hands[0],
                    status=TrackingStatus.OK,
                    reject_reason=None,
                )
            else:
                return SelectedHandResult(
                    hand=None,
                    status=TrackingStatus.NO_HAND,
                    reject_reason=RejectReason.AMBIGUOUS_HANDS,
                )

        # Tracked hand is specifically RIGHT or LEFT
        target_label = tracked_hand.value.capitalize()  # "Right" or "Left"
        matching_hands = [h for h in hands if h.label.capitalize() == target_label]
        other_hands = [h for h in hands if h.label.capitalize() != target_label]

        if len(matching_hands) == 1:
            return SelectedHandResult(
                hand=matching_hands[0],
                status=TrackingStatus.OK,
                reject_reason=None,
            )
        elif len(matching_hands) > 1:
            return SelectedHandResult(
                hand=None,
                status=TrackingStatus.NO_HAND,
                reject_reason=RejectReason.AMBIGUOUS_HANDS,
            )
        else:
            # 0 matching hands
            if other_hands:
                return SelectedHandResult(
                    hand=None,
                    status=TrackingStatus.NO_HAND,
                    reject_reason=RejectReason.WRONG_HAND,
                )
            else:
                return SelectedHandResult(
                    hand=None,
                    status=TrackingStatus.NO_HAND,
                    reject_reason=RejectReason.NO_HAND,
                )
