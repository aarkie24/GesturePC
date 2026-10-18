"""Timestamp-based linear resampling and bounded gap interpolation (Section 7.5)."""

from __future__ import annotations

from typing import Optional
import numpy as np

from app.constants import MATCH_RATE_HZ, MAX_INTERP_GAP_MS


def resample_step_vectors(
    step_vectors: np.ndarray,
    timestamps_ms: np.ndarray,
    match_rate_hz: float = MATCH_RATE_HZ,
    max_interp_gap_ms: float = MAX_INTERP_GAP_MS,
) -> Optional[np.ndarray]:
    """Resamples a temporal sequence of step vectors to a fixed grid of match_rate_hz.
    
    Section 7.5:
    Each sample and each live segment is converted to a fixed grid of match_rate_hz (15 Hz)
    by linear interpolation of the step vectors over their real timestamps. Gaps up to
    max_interp_gap_ms (150 ms) are interpolated; longer gaps invalidate the sequence.
    
    Args:
        step_vectors: float32 array of shape (N, D), typically D=17.
        timestamps_ms: float32 or int array of shape (N,) monotonically non-decreasing.
        match_rate_hz: target frequency in Hz (default 15 Hz).
        max_interp_gap_ms: maximum allowable tracking gap in ms (default 150 ms).
        
    Returns:
        float32 array of shape (K, D) where K >= 2, or None if the sequence is invalid.
    """
    if step_vectors.ndim != 2:
        return None
    n_frames, n_dims = step_vectors.shape
    if n_frames < 2 or len(timestamps_ms) != n_frames:
        return None

    ts = np.asarray(timestamps_ms, dtype=np.float64)
    # Check monotonic non-decreasing
    diffs = np.diff(ts)
    if np.any(diffs < 0):
        return None

    # Check for excessive gaps
    if np.any(diffs > max_interp_gap_ms):
        return None

    duration_ms = ts[-1] - ts[0]
    if duration_ms <= 0:
        return None

    # Remove any duplicate timestamps by keeping first occurrence
    unique_mask = np.concatenate([[True], diffs > 1e-4])
    clean_ts = ts[unique_mask]
    clean_vecs = step_vectors[unique_mask]

    if len(clean_ts) < 2:
        return None

    step_interval_ms = 1000.0 / match_rate_hz
    # Generate uniform grid starting at ts[0] through ts[-1]
    # np.arange may exclude ts[-1] due to floating precision, so include half-step margin
    grid = np.arange(clean_ts[0], clean_ts[-1] + (step_interval_ms * 0.1), step_interval_ms)
    # Clamp grid points to avoid extrapolation
    grid = np.clip(grid, clean_ts[0], clean_ts[-1])

    if len(grid) < 2:
        # At least 2 points required for DTW
        grid = np.array([clean_ts[0], clean_ts[-1]], dtype=np.float64)

    # Linear interpolation along each dimension
    resampled = np.empty((len(grid), n_dims), dtype=np.float32)
    for d in range(n_dims):
        resampled[:, d] = np.interp(grid, clean_ts, clean_vecs[:, d])

    return resampled
