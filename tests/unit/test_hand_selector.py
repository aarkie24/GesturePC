"""Unit tests for hand selector verifying every row of Section 7.2 specification table."""

import numpy as np
import pytest

from domain.enums import Hand, RejectReason, TrackingStatus
from domain.models import HandObservation, TrackingResult
from gestures.hand_selector import HandSelector


def _make_hand(label: str) -> HandObservation:
    arr = np.zeros((21, 3), dtype=np.float32)
    return HandObservation(
        label=label,
        label_score=0.99,
        presence_score=0.99,
        landmarks_image=arr,
        landmarks_world=arr,
    )


def test_hand_selector_table_rows():
    # 1. No hands detected -> NO_HAND
    res_empty = TrackingResult(1, 1000, (640, 480), TrackingStatus.NO_HAND, ())
    sel = HandSelector.select_hand(res_empty, Hand.RIGHT)
    assert sel.status == TrackingStatus.NO_HAND
    assert sel.reject_reason == RejectReason.NO_HAND
    assert sel.hand is None

    # 2. Tracked RIGHT, exactly one Right hand -> OK
    h_right = _make_hand("Right")
    res_r = TrackingResult(2, 2000, (640, 480), TrackingStatus.OK, (h_right,))
    sel = HandSelector.select_hand(res_r, Hand.RIGHT)
    assert sel.status == TrackingStatus.OK
    assert sel.reject_reason is None
    assert sel.hand == h_right

    # 3. Tracked RIGHT, only a Left hand -> WRONG_HAND
    h_left = _make_hand("Left")
    res_l = TrackingResult(3, 3000, (640, 480), TrackingStatus.OK, (h_left,))
    sel = HandSelector.select_hand(res_l, Hand.RIGHT)
    assert sel.status == TrackingStatus.NO_HAND
    assert sel.reject_reason == RejectReason.WRONG_HAND
    assert sel.hand is None

    # 4. Tracked RIGHT, two Right hands detected -> AMBIGUOUS_HANDS
    res_two_r = TrackingResult(4, 4000, (640, 480), TrackingStatus.OK, (h_right, _make_hand("Right")))
    sel = HandSelector.select_hand(res_two_r, Hand.RIGHT)
    assert sel.status == TrackingStatus.NO_HAND
    assert sel.reject_reason == RejectReason.AMBIGUOUS_HANDS
    assert sel.hand is None

    # 5. Tracked EITHER, one detection -> OK
    sel_either_one = HandSelector.select_hand(res_l, Hand.EITHER)
    assert sel_either_one.status == TrackingStatus.OK
    assert sel_either_one.hand == h_left

    # 6. Tracked EITHER, two detections -> AMBIGUOUS_HANDS
    res_both = TrackingResult(5, 5000, (640, 480), TrackingStatus.OK, (h_right, h_left))
    sel_either_two = HandSelector.select_hand(res_both, Hand.EITHER)
    assert sel_either_two.status == TrackingStatus.NO_HAND
    assert sel_either_two.reject_reason == RejectReason.AMBIGUOUS_HANDS
    assert sel_either_two.hand is None
