"""Unit tests for landmark and timestamp serialization codecs."""

import numpy as np
import pytest

from database.codecs import (
    decode_landmarks,
    decode_timestamps,
    encode_landmarks,
    encode_timestamps,
)


def test_landmarks_roundtrip():
    # 3 frames of 21 landmarks in 3D
    original = np.random.uniform(-1.0, 1.0, (3, 21, 3)).astype(np.float32)
    encoded = encode_landmarks(original)
    assert len(encoded) == 3 * 21 * 3 * 4

    decoded = decode_landmarks(encoded, frame_count=3)
    assert decoded.shape == (3, 21, 3)
    assert decoded.dtype == np.float32
    np.testing.assert_array_equal(original, decoded)
    assert not decoded.flags.writeable


def test_landmarks_rejects_nan_and_inf():
    nan_arr = np.zeros((1, 21, 3), dtype=np.float32)
    nan_arr[0, 0, 0] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        encode_landmarks(nan_arr)

    inf_arr = np.zeros((1, 21, 3), dtype=np.float32)
    inf_arr[0, 5, 2] = np.inf
    with pytest.raises(ValueError, match="non-finite"):
        encode_landmarks(inf_arr)


def test_landmarks_rejects_wrong_shape():
    wrong_shape = np.zeros((21, 3), dtype=np.float32)  # missing frame dimension
    with pytest.raises(ValueError, match="Invalid landmarks shape"):
        encode_landmarks(wrong_shape)


def test_landmarks_rejects_size_mismatch_on_decode():
    valid = np.zeros((2, 21, 3), dtype=np.float32)
    encoded = encode_landmarks(valid)
    # Asking for 3 frames instead of 2
    with pytest.raises(ValueError, match="size mismatch"):
        decode_landmarks(encoded, frame_count=3)


def test_timestamps_roundtrip():
    original = np.array([0, 33, 67, 100], dtype=np.int32)
    encoded = encode_timestamps(original)
    assert len(encoded) == 4 * 4

    decoded = decode_timestamps(encoded, frame_count=4)
    assert decoded is not None
    assert decoded.shape == (4,)
    assert decoded.dtype == np.int32
    np.testing.assert_array_equal(original, decoded)
    assert not decoded.flags.writeable


def test_timestamps_none_handling():
    assert encode_timestamps(None) is None
    assert decode_timestamps(None, frame_count=1) is None


def test_timestamps_rejects_decreasing_order():
    decreasing = np.array([0, 50, 40, 100], dtype=np.int32)
    with pytest.raises(ValueError, match="monotonically non-decreasing"):
        encode_timestamps(decreasing)
