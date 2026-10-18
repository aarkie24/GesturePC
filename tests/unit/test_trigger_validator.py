"""Unit tests for TriggerValidator state machine, stability hold, cooldowns, and rearming."""

import pytest

from domain.enums import TriggerState
from gestures.trigger_validator import TriggerValidator
from tests.fakes.fake_clock import FakeClock


def test_trigger_validator_stability_accumulation():
    """Trigger accumulates stable candidate frames up to stable_duration_ms before firing."""
    clock = FakeClock(initial_time=1000.0)
    validator = TriggerValidator(
        clock=clock,
        stable_duration_ms=400,
        max_gap_ms=120,
        cooldown_ms=1500,
        rearm_release_ms=300,
    )

    t0_ns = clock.monotonic_ns()

    # Frame 0: Candidate starts
    res = validator.update(candidate_gesture_id=1, frame_ts_ns=t0_ns)
    assert res.state == TriggerState.ACCUMULATING
    assert res.accumulated_ms == 0
    assert res.should_fire is False

    # Frames streamed at 33 ms intervals up to 200 ms
    for i in range(1, 7):
        t_ns = t0_ns + i * 33_333_333
        res = validator.update(candidate_gesture_id=1, frame_ts_ns=t_ns)
        assert res.state == TriggerState.ACCUMULATING

    assert 190 <= res.accumulated_ms <= 210
    assert res.should_fire is False

    # Frames streamed further up to 400 ms
    for i in range(7, 14):
        t_ns = t0_ns + i * 33_333_333
        res = validator.update(candidate_gesture_id=1, frame_ts_ns=t_ns)

    assert res.state == TriggerState.FIRED
    assert res.should_fire is True


def test_held_pose_fires_only_once():
    """A pose held continuously for 10 seconds fires exactly once (Section 7.6 / AC-06)."""
    clock = FakeClock(initial_time=1000.0)
    validator = TriggerValidator(
        clock=clock,
        stable_duration_ms=400,
        cooldown_ms=1500,
        rearm_release_ms=300,
    )

    t0_ns = clock.monotonic_ns()
    fire_count = 0

    # Simulate 10 seconds (300 frames at 33 ms intervals)
    for frame_idx in range(300):
        t_ns = t0_ns + frame_idx * 33_333_333
        res = validator.update(candidate_gesture_id=1, frame_ts_ns=t_ns)
        if res.should_fire:
            fire_count += 1

    assert fire_count == 1, f"Held pose fired {fire_count} times, expected exactly 1"


def test_rearming_after_cooldown_and_release():
    """Gesture can fire again only after both cooldown elapses AND release is observed for 300 ms."""
    clock = FakeClock(initial_time=1000.0)
    validator = TriggerValidator(
        clock=clock,
        stable_duration_ms=400,
        cooldown_ms=1500,
        rearm_release_ms=300,
    )

    t0_ns = clock.monotonic_ns()

    # Reach fire at 400 ms by streaming frames at 33 ms
    for i in range(14):
        t_ns = t0_ns + i * 33_333_333
        validator.update(candidate_gesture_id=1, frame_ts_ns=t_ns)

    # In cooldown up to 1900 ms (400 + 1500)
    # Release hand at 2000 ms
    t_release_ns = t0_ns + 2000_000_000
    validator.update(candidate_gesture_id=None, frame_ts_ns=t_release_ns)

    # Release held for 350 ms (> 300 ms) -> gesture rearmed to IDLE
    t_rearmed_ns = t_release_ns + 350_000_000
    validator.update(candidate_gesture_id=None, frame_ts_ns=t_rearmed_ns)

    # Present gesture again and hold for 400 ms (streamed at 33 ms) -> fires second time!
    for i in range(14):
        t_ns = t_rearmed_ns + (i + 1) * 33_333_333
        res2 = validator.update(candidate_gesture_id=1, frame_ts_ns=t_ns)

    assert res2.state == TriggerState.FIRED
    assert res2.should_fire is True


def test_tracking_gap_tolerance_and_reset():
    """Gaps <= 120 ms are tolerated; gaps > 120 ms reset accumulation to 0."""
    clock = FakeClock(initial_time=1000.0)
    validator = TriggerValidator(clock=clock, stable_duration_ms=400, max_gap_ms=120)

    t0_ns = clock.monotonic_ns()
    validator.update(candidate_gesture_id=1, frame_ts_ns=t0_ns)

    # Short gap of 80 ms (< 120 ms)
    res_short = validator.update(candidate_gesture_id=1, frame_ts_ns=t0_ns + 80_000_000)
    assert res_short.state == TriggerState.ACCUMULATING
    assert res_short.accumulated_ms == 80

    # Long gap of 200 ms (> 120 ms) -> resets accumulator
    res_long = validator.update(candidate_gesture_id=1, frame_ts_ns=t0_ns + 280_000_000)
    assert res_long.state == TriggerState.ACCUMULATING
    assert res_long.accumulated_ms == 0
