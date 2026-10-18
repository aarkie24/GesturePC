"""Banded DTW matching with length pre-filter and early abandoning (Section 7.5)."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Optional, Sequence, Tuple
import numpy as np

from app.constants import (
    DTW_BAND_FRACTION,
    DYNAMIC_D_MAX,
    DYNAMIC_MARGIN_RATIO,
    DYNAMIC_SHAPE_WEIGHT,
    DYNAMIC_TRAJECTORY_WEIGHT,
    SENSITIVITY,
)
from domain.enums import Hand, RejectReason


@dataclass(frozen=True)
class DynamicTemplate:
    """Compiled dynamic gesture template containing resampled step vector sequences."""
    gesture_id: int
    gesture_name: str
    hand: Hand
    samples: Tuple[np.ndarray, ...]  # Tuple of float32 arrays of shape (T_i, 17)
    base_threshold: float
    threshold_scale: float = 1.0

    def effective_threshold(self, global_sensitivity: float = SENSITIVITY) -> float:
        return float(self.base_threshold * global_sensitivity * self.threshold_scale)


@dataclass(frozen=True)
class DynamicMatchResult:
    """Result of matching a dynamic motion segment against compiled dynamic templates."""
    accepted: bool
    best_gesture_id: Optional[int]
    best_gesture_name: str
    best_distance: float
    second_gesture_id: Optional[int]
    second_distance: float
    threshold: float
    margin_ratio: float
    reject_reason: Optional[RejectReason]


def compute_step_cost(
    a: np.ndarray,
    b: np.ndarray,
    w_shape: float = DYNAMIC_SHAPE_WEIGHT,
    w_traj: float = DYNAMIC_TRAJECTORY_WEIGHT,
) -> float:
    """Computes weighted dynamic step cost between two 17-dimensional step vectors.
    
    Section 7.3:
    cost(a, b) = w_shape * mean_tip ||Delta tip|| + w_traj * ||Delta wrist||
    """
    # Shape part: 5 fingertips x 3 coords
    shape_a = a[:15].reshape(5, 3)
    shape_b = b[:15].reshape(5, 3)
    tip_diffs = np.linalg.norm(shape_a - shape_b, axis=1)
    mean_tip_diff = float(np.mean(tip_diffs))

    # Trajectory part: 2 coords (x', y')
    traj_a = a[15:17]
    traj_b = b[15:17]
    wrist_diff = float(np.linalg.norm(traj_a - traj_b))

    return float(w_shape * mean_tip_diff + w_traj * wrist_diff)


def compute_pairwise_step_costs(
    seq_a: np.ndarray,
    seq_b: np.ndarray,
    w_shape: float = DYNAMIC_SHAPE_WEIGHT,
    w_traj: float = DYNAMIC_TRAJECTORY_WEIGHT,
) -> np.ndarray:
    """Vectorized pairwise step costs matrix between seq_a (N, 17) and seq_b (M, 17)."""
    # seq_a[:, :15] shape (N, 5, 3), seq_b[:, :15] shape (M, 5, 3)
    shape_a = seq_a[:, :15].reshape(-1, 1, 5, 3)
    shape_b = seq_b[:, :15].reshape(1, -1, 5, 3)
    # (N, M, 5) -> mean over axis 2 -> (N, M)
    mean_tip = np.mean(np.linalg.norm(shape_a - shape_b, axis=-1), axis=-1)

    traj_a = seq_a[:, 15:17].reshape(-1, 1, 2)
    traj_b = seq_b[:, 15:17].reshape(1, -1, 2)
    wrist_diff = np.linalg.norm(traj_a - traj_b, axis=-1)

    return (w_shape * mean_tip + w_traj * wrist_diff).astype(np.float32)


def banded_dtw_distance(
    seq_a: np.ndarray,
    seq_b: np.ndarray,
    band_fraction: float = DTW_BAND_FRACTION,
    w_shape: float = DYNAMIC_SHAPE_WEIGHT,
    w_traj: float = DYNAMIC_TRAJECTORY_WEIGHT,
    early_abandon_threshold: Optional[float] = None,
) -> float:
    """Computes Sakoe-Chiba banded DTW normalized distance D[n-1, m-1] / (n + m).
    
    Section 7.5:
    - Band width = band_fraction * max(n, m)
    - Early abandoning stops comparison when (min_row_cost / (n + m)) > early_abandon_threshold.
    - Length ratio pre-filter: 0.5 <= n/m <= 2.0.
    
    Returns:
        float normalized distance in weighted palm units, or float('inf').
    """
    n = len(seq_a)
    m = len(seq_b)
    if n == 0 or m == 0:
        return float("inf")

    # Length-ratio pre-filter (0.5 to 2.0)
    ratio = n / m
    if ratio < 0.5 or ratio > 2.0:
        return float("inf")

    # Sakoe-Chiba band width
    max_len = max(n, m)
    band_width = max(1, int(math.ceil(band_fraction * max_len)))

    # Pairwise cost matrix (N, M)
    cost_matrix = compute_pairwise_step_costs(seq_a, seq_b, w_shape, w_traj)

    # DP matrix initialized to infinity
    dp = np.full((n, m), fill_value=np.inf, dtype=np.float32)

    # Initial cell
    dp[0, 0] = cost_matrix[0, 0]

    norm_factor = float(n + m)

    # DP execution row by row
    for i in range(n):
        # Center column along diagonal projection
        center_j = int(i * (m / n))
        j_min = max(0, center_j - band_width)
        j_max = min(m - 1, center_j + band_width)

        # Ensure start and end corners are in-band
        if i == 0:
            j_min = 0
        if i == n - 1:
            j_max = m - 1

        row_min = float("inf")

        for j in range(j_min, j_max + 1):
            if i == 0 and j == 0:
                row_min = min(row_min, float(dp[0, 0]))
                continue

            prev_costs = []
            if i > 0 and j > 0:
                prev_costs.append(dp[i - 1, j - 1])
            if i > 0:
                prev_costs.append(dp[i - 1, j])
            if j > 0:
                prev_costs.append(dp[i, j - 1])

            if prev_costs:
                best_prev = min(prev_costs)
                if not np.isinf(best_prev):
                    cost = cost_matrix[i, j] + best_prev
                    dp[i, j] = cost
                    if cost < row_min:
                        row_min = cost

        # Early abandoning check
        if early_abandon_threshold is not None and not np.isinf(early_abandon_threshold):
            if (row_min / norm_factor) > early_abandon_threshold:
                return float("inf")

    final_cost = dp[n - 1, m - 1]
    if np.isinf(final_cost):
        return float("inf")

    return float(final_cost / norm_factor)


class DynamicMatcher:
    """Pure nearest-neighbor banded DTW matcher with margin ratio test."""

    @staticmethod
    def match(
        live_steps: np.ndarray,
        selected_hand: Hand,
        templates: Sequence[DynamicTemplate],
        global_sensitivity: float = SENSITIVITY,
        margin_ratio_limit: float = DYNAMIC_MARGIN_RATIO,
    ) -> DynamicMatchResult:
        """Matches a resampled motion segment against enabled dynamic templates.
        
        Section 7.5:
        1. For every enabled dynamic gesture whose hand equals selected hand:
           d_g = min over its samples of banded_dtw(live, sample)
        2. Sort ascending: best (g1, d1), second (g2, d2)
        3. Accepted iff d1 <= effective(g1) and (g2 is None or d1 / max(d2, eps) <= margin_ratio_limit).
        """
        # Filter matching hand
        eligible = [t for t in templates if t.hand == selected_hand or selected_hand == Hand.EITHER]
        if not eligible or len(live_steps) < 2:
            return DynamicMatchResult(
                accepted=False,
                best_gesture_id=None,
                best_gesture_name="",
                best_distance=float("inf"),
                second_gesture_id=None,
                second_distance=float("inf"),
                threshold=0.0,
                margin_ratio=1.0,
                reject_reason=RejectReason.SEGMENT_NO_MATCH,
            )

        scored: list[tuple[float, DynamicTemplate]] = []

        for t in eligible:
            eff_thresh = t.effective_threshold(global_sensitivity)
            min_dist = float("inf")
            for sample in t.samples:
                d = banded_dtw_distance(
                    live_steps,
                    sample,
                    early_abandon_threshold=min(eff_thresh, min_dist),
                )
                if d < min_dist:
                    min_dist = d
            scored.append((min_dist, t))

        scored.sort(key=lambda x: x[0])

        best_dist, best_t = scored[0]
        second_dist, second_t = (scored[1][0], scored[1][1]) if len(scored) > 1 else (float("inf"), None)

        threshold = best_t.effective_threshold(global_sensitivity)
        margin_ratio = float(best_dist / max(second_dist, 1e-6)) if not math.isinf(second_dist) else 0.0

        if math.isinf(best_dist) or best_dist > threshold:
            return DynamicMatchResult(
                accepted=False,
                best_gesture_id=best_t.gesture_id,
                best_gesture_name=best_t.gesture_name,
                best_distance=best_dist,
                second_gesture_id=second_t.gesture_id if second_t else None,
                second_distance=second_dist,
                threshold=threshold,
                margin_ratio=margin_ratio,
                reject_reason=RejectReason.ABOVE_THRESHOLD,
            )

        if second_t is not None and margin_ratio > margin_ratio_limit:
            return DynamicMatchResult(
                accepted=False,
                best_gesture_id=best_t.gesture_id,
                best_gesture_name=best_t.gesture_name,
                best_distance=best_dist,
                second_gesture_id=second_t.gesture_id,
                second_distance=second_dist,
                threshold=threshold,
                margin_ratio=margin_ratio,
                reject_reason=RejectReason.AMBIGUOUS_MARGIN,
            )

        return DynamicMatchResult(
            accepted=True,
            best_gesture_id=best_t.gesture_id,
            best_gesture_name=best_t.gesture_name,
            best_distance=best_dist,
            second_gesture_id=second_t.gesture_id if second_t else None,
            second_distance=second_dist,
            threshold=threshold,
            margin_ratio=margin_ratio,
            reject_reason=None,
        )
