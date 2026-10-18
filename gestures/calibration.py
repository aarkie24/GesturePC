"""Threshold derivation and collision checking for static and dynamic gestures."""

from __future__ import annotations

from typing import List, Sequence, Tuple
import numpy as np

from app.constants import (
    STATIC_THRESHOLD_MAX,
    STATIC_THRESHOLD_MIN,
    THRESHOLD_SLACK,
)
from gestures.normalizer import mean_landmark_deviation


def calculate_static_base_threshold(
    sample_features: Sequence[np.ndarray],
    threshold_slack: float = THRESHOLD_SLACK,
    threshold_min: float = STATIC_THRESHOLD_MIN,
    threshold_max: float = STATIC_THRESHOLD_MAX,
) -> float:
    """Calculates base threshold for a static gesture from its sample features.
    
    Formula (Section 7.4):
    For each sample i:
        r_i = min over j != i of MLD(sample_i, sample_j)
    base = clamp(threshold_slack * p95(r), threshold_min, threshold_max)
    """
    n = len(sample_features)
    if n < 2:
        # Fallback default if only 1 sample exists
        return float((threshold_min + threshold_max) / 2.0)

    # Compute pairwise distances
    r_list: List[float] = []
    for i in range(n):
        min_dist = float("inf")
        for j in range(n):
            if i != j:
                dist = mean_landmark_deviation(sample_features[i], sample_features[j])
                if dist < min_dist:
                    min_dist = dist
        r_list.append(min_dist)

    p95 = float(np.percentile(r_list, 95))
    raw_base = threshold_slack * p95
    base = float(np.clip(raw_base, threshold_min, threshold_max))
    return base


def check_static_collisions(
    new_sample_features: Sequence[np.ndarray],
    new_threshold: float,
    existing_gestures: Sequence[Tuple[str, Sequence[np.ndarray], float]],
) -> List[Tuple[str, float]]:
    """Checks for collisions between new static samples and existing enabled static gestures of same hand.
    
    Section 7.4:
    If min MLD(new, existing) <= max(threshold_new, threshold_existing),
    collision is reported.
    
    Args:
        new_sample_features: List of 60-element static feature arrays for the new gesture.
        new_threshold: Effective threshold of the new gesture.
        existing_gestures: List of (gesture_name, sample_features_list, existing_threshold).
        
    Returns:
        List of (colliding_gesture_name, minimum_distance).
    """
    collisions: List[Tuple[str, float]] = []

    for name, existing_samples, existing_threshold in existing_gestures:
        if not existing_samples:
            continue
        
        min_mld = float("inf")
        for new_feat in new_sample_features:
            for exist_feat in existing_samples:
                d = mean_landmark_deviation(new_feat, exist_feat)
                if d < min_mld:
                    min_mld = d

        conflict_limit = max(new_threshold, existing_threshold)
        if min_mld <= conflict_limit:
            collisions.append((name, min_mld))

    return collisions
