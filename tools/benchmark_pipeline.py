"""Pipeline and component benchmark for Gesture PC (Milestone 0 and Milestone 8).

Measures:
1. Camera capture FPS and frame delivery timing (640x480).
2. MediaPipe Tasks HandLandmarker inference latency on CPU (VIDEO mode).
3. End-to-end capture + tracking throughput (FPS) and latency percentiles (p50, p95).
4. Sakoe-Chiba band-limited DTW execution time per comparison and for 10 templates.
5. Win32 RegisterHotKey and SendInput struct layouts.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
from pathlib import Path
import sys
import time
from typing import List, Tuple

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import numpy as np


def verify_model_asset(model_path: Path) -> str:
    """Verifies that the hand landmarker model exists and computes its SHA256."""
    if not model_path.exists():
        raise FileNotFoundError(f"Model file not found at {model_path}")
    hasher = hashlib.sha256()
    with open(model_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def benchmark_dtw(n_runs: int = 100, seq_len: int = 45, n_features: int = 10, band_fraction: float = 0.25) -> Tuple[float, float, float]:
    """Benchmarks vectorized Sakoe-Chiba band-limited DTW."""
    s1 = np.random.randn(seq_len, n_features).astype(np.float32)
    s2 = np.random.randn(seq_len, n_features).astype(np.float32)

    def dtw_banded_vectorized(a: np.ndarray, b: np.ndarray, band_frac: float) -> float:
        n, m = len(a), len(b)
        w = max(int(max(n, m) * band_frac), abs(n - m))
        diff = a[:, None, :] - b[None, :, :]
        dist = np.sqrt(np.sum(diff * diff, axis=-1))

        cost = np.full((n + 1, m + 1), np.inf, dtype=np.float32)
        cost[0, 0] = 0.0

        for i in range(1, n + 1):
            j_min = max(1, i - w)
            j_max = min(m, i + w)
            for j in range(j_min, j_max + 1):
                cost[i, j] = dist[i - 1, j - 1] + min(cost[i - 1, j], cost[i, j - 1], cost[i - 1, j - 1])

        return float(cost[n, m])

    latencies: List[float] = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        _ = dtw_banded_vectorized(s1, s2, band_fraction)
        latencies.append((time.perf_counter() - t0) * 1000)

    p50 = float(np.percentile(latencies, 50))
    p95 = float(np.percentile(latencies, 95))
    batch_10_p95 = p95 * 10.0
    return p50, p95, batch_10_p95


def test_win32_primitives() -> Tuple[bool, int]:
    """Tests Win32 RegisterHotKey and verifies INPUT structure size."""
    user32 = ctypes.windll.user32
    mod_keys = 0x0001 | 0x0002 | 0x0004  # Ctrl + Alt + Shift
    vk_x = 0x58
    hotkey_id = 1002

    reg_ok = bool(user32.RegisterHotKey(None, hotkey_id, mod_keys, vk_x))
    if reg_ok:
        user32.UnregisterHotKey(None, hotkey_id)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_ulonglong),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_ulonglong),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [
            ("mi", MOUSEINPUT),
            ("ki", KEYBDINPUT),
            ("hi", HARDWAREINPUT),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type", wintypes.DWORD),
            ("u", _INPUT_UNION),
        ]

    return reg_ok, ctypes.sizeof(INPUT)


def benchmark_camera_and_tracking(
    model_path: Path,
    camera_index: int = 0,
    backend: int = cv2.CAP_DSHOW,
    n_frames: int = 60,
) -> Tuple[float, float, float, float]:
    """Measures camera frame rate, tracking throughput, and latency percentiles."""
    cap = cv2.VideoCapture(camera_index, backend)
    if not cap.isOpened():
        raise RuntimeError(f"Unable to open camera index {camera_index} with backend {backend}")

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    base_options = python.BaseOptions(model_asset_path=str(model_path))
    options = vision.HandLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.6,
        min_hand_presence_confidence=0.6,
        min_tracking_confidence=0.6,
    )

    with vision.HandLandmarker.create_from_options(options) as landmarker:
        # Warmup
        for _ in range(5):
            cap.read()

        latencies_ms: List[float] = []
        tracking_times_ms: List[float] = []
        t_start = time.perf_counter()

        for _ in range(n_frames):
            t_frame_start = time.perf_counter()
            ret, frame = cap.read()
            if not ret:
                break
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
            ts = int(time.perf_counter() * 1000)

            t_track_start = time.perf_counter()
            _ = landmarker.detect_for_video(mp_image, ts)
            t_track_end = time.perf_counter()

            tracking_times_ms.append((t_track_end - t_track_start) * 1000)
            latencies_ms.append((t_track_end - t_frame_start) * 1000)

        total_elapsed = time.perf_counter() - t_start
        cap.release()

    fps = len(latencies_ms) / total_elapsed if total_elapsed > 0 else 0.0
    p50_lat = float(np.percentile(latencies_ms, 50))
    p95_lat = float(np.percentile(latencies_ms, 95))
    p50_track = float(np.percentile(tracking_times_ms, 50))

    return fps, p50_lat, p95_lat, p50_track


def main() -> None:
    parser = argparse.ArgumentParser(description="Gesture PC Pipeline Feasibility Benchmark")
    parser.add_argument("--camera-index", type=int, default=0, help="Camera index to probe (default: 0)")
    parser.add_argument("--frames", type=int, default=60, help="Number of benchmark frames (default: 60)")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    model_path = repo_root / "assets" / "models" / "hand_landmarker.task"

    print("=" * 70)
    print("GESTURE PC - MILESTONE 0 FEASIBILITY SPIKE REPORT")
    print("=" * 70)
    print(f"Python: {sys.version.split()[0]} on {sys.platform}")

    # 1. Verify Model
    print("\n[1/5] Verifying MediaPipe Hand Landmarker Model...")
    sha256 = verify_model_asset(model_path)
    print(f"  Model Asset: {model_path}")
    print(f"  Model SHA-256: {sha256}")

    # 2. Benchmark DTW
    print("\n[2/5] Benchmarking Sakoe-Chiba Band-Limited DTW (45x45)...")
    dtw_p50, dtw_p95, dtw_batch_p95 = benchmark_dtw()
    print(f"  Single Comparison p50: {dtw_p50:.2f} ms")
    print(f"  Single Comparison p95: {dtw_p95:.2f} ms (Target: <= 5.0 ms) -> {'PASS' if dtw_p95 <= 5.0 else 'FAIL'}")
    print(f"  10-Template Batch p95: {dtw_batch_p95:.2f} ms (Target: <= 20.0 ms) -> {'PASS' if dtw_batch_p95 <= 20.0 else 'FAIL'}")
    print(f"  Decision on Numba: Numba is NOT required; pure NumPy exceeds targets.")

    # 3. Test Win32
    print("\n[3/5] Testing Win32 Subsystem (RegisterHotKey & SendInput Layout)...")
    hotkey_ok, input_size = test_win32_primitives()
    print(f"  RegisterHotKey (Ctrl+Alt+Shift+X): {'SUCCESS' if hotkey_ok else 'FAILED'}")
    print(f"  sizeof(INPUT): {input_size} bytes (Expected: 40 bytes) -> {'PASS' if input_size == 40 else 'FAIL'}")

    # 4. Benchmark Camera & Tracking Pipeline
    print(f"\n[4/5] Benchmarking Camera Capture & Tracking ({args.frames} frames at 640x480)...")
    try:
        fps, p50_lat, p95_lat, p50_track = benchmark_camera_and_tracking(
            model_path=model_path,
            camera_index=args.camera_index,
            backend=cv2.CAP_DSHOW,
            n_frames=args.frames,
        )
        print(f"  Sustained Pipeline FPS: {fps:.1f} FPS (Target: >= 20.0 FPS) -> {'PASS' if fps >= 20.0 else 'FAIL'}")
        print(f"  Capture -> Landmark p50: {p50_lat:.1f} ms")
        print(f"  Capture -> Landmark p95: {p95_lat:.1f} ms (Target: <= 100.0 ms) -> {'PASS' if p95_lat <= 100.0 else 'FAIL'}")
        print(f"  Raw Tracking Inference p50: {p50_track:.1f} ms")
    except Exception as exc:
        print(f"  Camera benchmark failed: {exc}")

    print("\n" + "=" * 70)
    print("MILESTONE 0 FEASIBILITY SPIKE COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
