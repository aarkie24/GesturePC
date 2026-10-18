"""Unit tests for timestamp-based linear resampling (Section 7.5)."""

import numpy as np
import pytest

from gestures.resampler import resample_step_vectors


def test_resample_uniform_grid_basic():
    # 30 frames at 30 FPS (~33.33 ms interval, 1 second duration)
    timestamps = np.linspace(0, 1000, 31)
    # Step vector: 17 dims, linear ramp from 0 to 1
    steps = np.zeros((31, 17), dtype=np.float32)
    for d in range(17):
        steps[:, d] = np.linspace(0, d + 1, 31)

    # Resample at 15 Hz (step interval ~66.67 ms)
    resampled = resample_step_vectors(steps, timestamps, match_rate_hz=15)

    assert resampled is not None
    assert resampled.shape[1] == 17
    # Duration ~1000 ms at 15 Hz -> ~16 points
    assert 15 <= len(resampled) <= 17

    # Start and end values should be preserved
    np.testing.assert_allclose(resampled[0], steps[0], atol=1e-3)
    np.testing.assert_allclose(resampled[-1], steps[-1], atol=1e-3)


def test_resample_interpolates_short_gaps():
    # Timestamps with a 100 ms gap (below 150 ms max_interp_gap_ms)
    ts = np.array([0, 33, 66, 166, 200, 233, 300, 400], dtype=np.float64)
    steps = np.ones((len(ts), 17), dtype=np.float32) * 2.0

    resampled = resample_step_vectors(steps, ts, max_interp_gap_ms=150)
    assert resampled is not None
    assert len(resampled) >= 2
    np.testing.assert_allclose(resampled, 2.0, atol=1e-5)


def test_resample_invalidates_excessive_gap():
    # Gap of 200 ms (> 150 ms threshold)
    ts = np.array([0, 33, 66, 270, 300, 333, 400], dtype=np.float64)
    steps = np.ones((len(ts), 17), dtype=np.float32)

    resampled = resample_step_vectors(steps, ts, max_interp_gap_ms=150)
    assert resampled is None


def test_resample_rejects_non_monotonic_timestamps():
    ts = np.array([0, 100, 50, 200], dtype=np.float64)
    steps = np.ones((4, 17), dtype=np.float32)

    assert resample_step_vectors(steps, ts) is None


def test_resample_rejects_insufficient_frames():
    ts = np.array([0], dtype=np.float64)
    steps = np.ones((1, 17), dtype=np.float32)

    assert resample_step_vectors(steps, ts) is None
