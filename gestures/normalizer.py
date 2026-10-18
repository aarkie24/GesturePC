"""Normalization and coordinate transformation for hand landmarks."""

from __future__ import annotations

from typing import Tuple
import numpy as np

NORMALIZER_VERSION = 1
DEGENERATE_PALM_EPSILON = 1e-6


class DegenerateHandError(ValueError):
    """Raised when palm unit is below threshold indicating degenerate landmark data."""
    pass


def normalize_world_landmarks(landmarks_world: np.ndarray) -> np.ndarray:
    """Normalizes metric world landmarks according to Section 7.3.
    
    1. Subtract wrist (landmark 0).
    2. Divide by palm unit ||L9 - L0||.
    3. Drop wrist (now zero): returns 20 landmarks x 3 = 60 values (shape (20, 3)).
    
    Args:
        landmarks_world: float32 array of shape (21, 3).
        
    Returns:
        float32 array of shape (20, 3) representing normalized non-wrist landmarks.
        
    Raises:
        DegenerateHandError: if palm unit is below 1e-6.
        ValueError: if input shape is not (21, 3).
    """
    if landmarks_world.shape != (21, 3):
        raise ValueError(f"Expected landmarks_world shape (21, 3), got {landmarks_world.shape}")

    wrist = landmarks_world[0:1, :]  # shape (1, 3)
    middle_mcp = landmarks_world[9:10, :]  # shape (1, 3)
    
    palm_unit = float(np.linalg.norm(middle_mcp - wrist))
    if palm_unit < DEGENERATE_PALM_EPSILON or np.isnan(palm_unit):
        raise DegenerateHandError(f"Degenerate palm unit: {palm_unit} < {DEGENERATE_PALM_EPSILON}")

    # Translate wrist to origin and scale by palm unit
    centered = landmarks_world - wrist
    normalized = centered / palm_unit

    # Drop wrist (index 0), keep remaining 20 landmarks
    normalized_20 = normalized[1:21, :].astype(np.float32)
    return normalized_20


def aspect_correct_image_landmarks(
    landmarks_image: np.ndarray, width: int, height: int
) -> np.ndarray:
    """Applies aspect correction to image landmarks (Section 7.1).
    
    x' = x * (width / height)
    y' = y
    z' = z
    """
    if landmarks_image.shape != (21, 3):
        raise ValueError(f"Expected landmarks_image shape (21, 3), got {landmarks_image.shape}")
    if height <= 0:
        raise ValueError(f"Height must be positive, got {height}")

    aspect_ratio = width / height
    corrected = landmarks_image.copy()
    corrected[:, 0] *= aspect_ratio
    return corrected.astype(np.float32)


def compute_palm_unit_image(landmarks_image_corrected: np.ndarray) -> float:
    """Computes palm unit distance ||L9 - L0|| in aspect-corrected image space."""
    wrist = landmarks_image_corrected[0, :2]
    middle_mcp = landmarks_image_corrected[9, :2]
    return float(np.linalg.norm(middle_mcp - wrist))


def mean_landmark_deviation(a: np.ndarray, b: np.ndarray) -> float:
    """Computes Mean Landmark Deviation (MLD) in palm units across 20 normalized landmarks.
    
    MLD(a, b) = mean over 20 landmarks of ||a_i - b_i||_2.
    
    Args:
        a: shape (20, 3) or (60,)
        b: shape (20, 3) or (60,)
    """
    a_arr = np.asarray(a, dtype=np.float32).reshape(20, 3)
    b_arr = np.asarray(b, dtype=np.float32).reshape(20, 3)
    
    pointwise_diff = a_arr - b_arr
    distances = np.linalg.norm(pointwise_diff, axis=1)  # shape (20,)
    return float(np.mean(distances))
