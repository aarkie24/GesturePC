"""Feature extraction from normalized hand landmarks."""

from __future__ import annotations

from typing import Tuple
import numpy as np

from gestures.normalizer import (
    aspect_correct_image_landmarks,
    normalize_world_landmarks,
)

FEATURE_VERSION = 1


def extract_static_features(landmarks_world: np.ndarray) -> np.ndarray:
    """Extracts 60-dimensional static feature vector from raw metric world landmarks.
    
    1. Normalizes landmarks_world (subtracts wrist, scales by palm unit, drops wrist).
    2. Flattens (20, 3) array into a 60-element 1D float32 vector.
    
    Args:
        landmarks_world: float32 array of shape (21, 3).
        
    Returns:
        float32 array of shape (60,).
    """
    normalized_20 = normalize_world_landmarks(landmarks_world)
    return normalized_20.reshape(-1).astype(np.float32)


def extract_dynamic_step_features(
    landmarks_world: np.ndarray,
    landmarks_image: np.ndarray,
    frame_width: int,
    frame_height: int,
    ref_wrist_image: np.ndarray,
    segment_palm_scale: float,
) -> np.ndarray:
    """Extracts 17-dimensional dynamic per-step vector (Section 7.3).
    
    - Shape (15): fingertips (4, 8, 12, 16, 20) from normalized world representation.
      Note: in normalized_20, indices are shifted by 1 since wrist (0) was dropped.
      Landmark 4 -> index 3
      Landmark 8 -> index 7
      Landmark 12 -> index 11
      Landmark 16 -> index 15
      Landmark 20 -> index 19
    - Trajectory (2): wrist position from aspect-corrected image landmarks relative to
      the wrist at the first step of the segment, divided by segment_palm_scale.
      
    Returns:
        float32 array of shape (17,).
    """
    normalized_20 = normalize_world_landmarks(landmarks_world)
    tip_indices = [3, 7, 11, 15, 19]  # 4, 8, 12, 16, 20 minus 1
    shape_features = normalized_20[tip_indices, :].reshape(-1)  # 15 values

    # Trajectory
    corrected_image = aspect_correct_image_landmarks(landmarks_image, frame_width, frame_height)
    curr_wrist = corrected_image[0, :2]  # (x', y')
    
    scale = max(segment_palm_scale, 1e-6)
    delta_wrist = (curr_wrist - ref_wrist_image[:2]) / scale  # 2 values
    
    step_vec = np.concatenate([shape_features, delta_wrist]).astype(np.float32)
    return step_vec
