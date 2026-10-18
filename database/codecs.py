"""Landmark and timestamp BLOB serialization and deserialization codecs."""

from __future__ import annotations

from typing import Optional
import numpy as np

LANDMARK_COUNT = 21
COORDINATE_DIMS = 3
BYTES_PER_FLOAT32 = 4
BYTES_PER_INT32 = 4
FRAME_LANDMARKS_SIZE = LANDMARK_COUNT * COORDINATE_DIMS * BYTES_PER_FLOAT32  # 252 bytes


def encode_landmarks(landmarks: np.ndarray) -> bytes:
    """Encodes float32 landmark array of shape (frame_count, 21, 3) to bytes.
    
    Validates that:
    1. Shape is (N, 21, 3) where N >= 1.
    2. Dtype is float32.
    3. All values are finite (no NaN or Inf).
    """
    if landmarks.ndim != 3 or landmarks.shape[1] != LANDMARK_COUNT or landmarks.shape[2] != COORDINATE_DIMS:
        raise ValueError(f"Invalid landmarks shape {landmarks.shape}, expected (N, 21, 3)")
    if landmarks.shape[0] < 1:
        raise ValueError("Frame count must be at least 1")
    if landmarks.dtype != np.float32:
        landmarks = landmarks.astype(np.float32)
    if not np.all(np.isfinite(landmarks)):
        raise ValueError("Landmarks contain non-finite values (NaN or Inf)")

    # Ensure little-endian C-order
    if not landmarks.flags.c_contiguous or landmarks.dtype.byteorder not in ("=", "<"):
        landmarks = np.ascontiguousarray(landmarks, dtype="<f4")

    return landmarks.tobytes()


def decode_landmarks(blob: bytes, frame_count: int) -> np.ndarray:
    """Decodes little-endian float32 bytes into an immutable ndarray of shape (frame_count, 21, 3).
    
    Validates byte length and finite constraints.
    """
    if frame_count < 1:
        raise ValueError("frame_count must be at least 1")
    expected_bytes = frame_count * FRAME_LANDMARKS_SIZE
    if len(blob) != expected_bytes:
        raise ValueError(f"Landmark BLOB size mismatch: got {len(blob)} bytes, expected {expected_bytes}")

    arr = np.frombuffer(blob, dtype="<f4").reshape((frame_count, LANDMARK_COUNT, COORDINATE_DIMS))
    if not np.all(np.isfinite(arr)):
        raise ValueError("Decoded landmarks contain non-finite values (NaN or Inf)")

    arr.setflags(write=False)
    return arr


def encode_timestamps(timestamps: Optional[np.ndarray]) -> Optional[bytes]:
    """Encodes int32 timestamps of shape (frame_count,) into bytes. Returns None if input is None."""
    if timestamps is None:
        return None
    if timestamps.ndim != 1:
        raise ValueError(f"Timestamps must be 1-dimensional, got shape {timestamps.shape}")
    if timestamps.shape[0] < 1:
        raise ValueError("Timestamps array must have at least 1 entry")
    if timestamps.dtype != np.int32:
        timestamps = timestamps.astype(np.int32)
    # Check monotonically non-decreasing
    if np.any(np.diff(timestamps) < 0):
        raise ValueError("Timestamps must be monotonically non-decreasing")

    if not timestamps.flags.c_contiguous or timestamps.dtype.byteorder not in ("=", "<"):
        timestamps = np.ascontiguousarray(timestamps, dtype="<i4")

    return timestamps.tobytes()


def decode_timestamps(blob: Optional[bytes], frame_count: int) -> Optional[np.ndarray]:
    """Decodes little-endian int32 bytes into an immutable ndarray of shape (frame_count,)."""
    if blob is None:
        return None
    if frame_count < 1:
        raise ValueError("frame_count must be at least 1")
    expected_bytes = frame_count * BYTES_PER_INT32
    if len(blob) != expected_bytes:
        raise ValueError(f"Timestamp BLOB size mismatch: got {len(blob)} bytes, expected {expected_bytes}")

    arr = np.frombuffer(blob, dtype="<i4")
    if np.any(np.diff(arr) < 0):
        raise ValueError("Decoded timestamps are not monotonically non-decreasing")

    arr.setflags(write=False)
    return arr
