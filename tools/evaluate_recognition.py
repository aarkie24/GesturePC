"""Evaluation tool for gesture recognition pipelines using synthetic or recorded landmarks."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys
from typing import Dict, List, Tuple
import numpy as np

# Add repo root to sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from domain.enums import GestureType, Hand, TrackingStatus
from domain.models import HandObservation, TemplateSnapshot, TrackingResult
from domain.ports import Clock
from gestures.calibration import (
    calculate_dynamic_base_threshold,
    calculate_static_base_threshold,
)
from gestures.dynamic_matcher import DynamicTemplate
from gestures.feature_extractor import (
    extract_dynamic_step_features,
    extract_static_features,
)
from gestures.normalizer import aspect_correct_image_landmarks
from gestures.recognition_engine import RecognitionEngine
from gestures.resampler import resample_step_vectors
from gestures.static_matcher import StaticTemplate
from gestures.trigger_validator import TriggerValidator
from tests.fixtures.generate import generate_fixture_sequence, generate_pose_landmarks


class ReplayClock:
    """Deterministic replay clock following sequence timestamps."""

    def __init__(self) -> None:
        self._current_ns = 0

    def set_ns(self, ts_ns: int) -> None:
        self._current_ns = ts_ns

    def time(self) -> float:
        return self._current_ns / 1e9

    def monotonic(self) -> float:
        return self._current_ns / 1e9

    def monotonic_ns(self) -> int:
        return self._current_ns

    def sleep(self, seconds: float) -> None:
        self._current_ns += int(seconds * 1e9)


def wilson_score_interval(successes: int, total: int, confidence: float = 0.95) -> Tuple[float, float]:
    """Computes Wilson score 95% confidence interval for binomial proportions."""
    if total == 0:
        return 0.0, 0.0
    z = 1.95996  # 95% confidence z-score
    p = successes / float(total)
    denominator = 1.0 + (z**2) / total
    center = (p + (z**2) / (2 * total)) / denominator
    margin = (z * math.sqrt((p * (1.0 - p) + (z**2) / (4 * total)) / total)) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def generate_dynamic_motion_sequence(
    direction: str,
    n_motion_frames: int = 18,
    fps: float = 30.0,
    noise_sigma: float = 0.003,
    seed: int = 42,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Generates synthetic dynamic sequence: pre-motion rest -> motion -> post-motion rest."""
    rng = np.random.default_rng(seed)
    total_frames = 10 + n_motion_frames + 20  # 10 rest + motion + 20 rest
    dt_ns = int(1e9 / fps)

    world_seq = np.zeros((total_frames, 21, 3), dtype=np.float32)
    img_seq = np.zeros((total_frames, 21, 3), dtype=np.float32)
    ts_seq = np.array([i * dt_ns for i in range(total_frames)], dtype=np.int64)

    # Base pose: open hand
    base_world = generate_pose_landmarks("open_palm", noise_sigma=0.0, seed=0)

    # Start wrist at center (0.5, 0.5)
    start_x, start_y = 0.5, 0.5
    dx, dy = 0.0, 0.0
    if direction == "swipe_right":
        dx, dy = 0.30, 0.0
    elif direction == "swipe_left":
        dx, dy = -0.30, 0.0
    elif direction == "swipe_up":
        dx, dy = 0.0, -0.30

    curr_x, curr_y = start_x, start_y

    for i in range(total_frames):
        if i < 10:
            # Pre-motion rest
            pass
        elif i < 10 + n_motion_frames:
            # Active movement
            progress = (i - 9) / float(n_motion_frames)
            curr_x = start_x + dx * progress
            curr_y = start_y + dy * progress
        else:
            # Post-motion rest
            curr_x = start_x + dx
            curr_y = start_y + dy

        w_frame = base_world.copy()
        if noise_sigma > 0:
            # Add noise only to non-wrist fingers
            w_frame[1:] += rng.normal(0, noise_sigma, w_frame[1:].shape).astype(np.float32)
        world_seq[i] = w_frame

        # Image landmarks
        img_frame = np.zeros((21, 3), dtype=np.float32)
        img_frame[0, :2] = [curr_x, curr_y]
        img_frame[9, :2] = [curr_x, curr_y - 0.16]
        for lm_idx in range(1, 21):
            if lm_idx != 9:
                img_frame[lm_idx, :2] = [curr_x + w_frame[lm_idx, 0] * 2.0, curr_y + w_frame[lm_idx, 1] * 2.0]
        img_frame[:, 2] = w_frame[:, 2]
        img_seq[i] = img_frame

    return world_seq, img_seq, ts_seq


def evaluate_static_gestures() -> bool:
    poses = ["open_palm", "fist", "peace", "thumbs_up"]

    print("=" * 70)
    print("Static Gesture Evaluation Benchmark (§7.4 / AC-04)")
    print("=" * 70)

    templates: List[StaticTemplate] = []
    for idx, p_name in enumerate(poses, start=1):
        samples = []
        for s_idx in range(10):
            wf = generate_pose_landmarks(p_name, noise_sigma=0.003, seed=100 + s_idx)
            feat = extract_static_features(wf)
            samples.append(feat)

        thresh = calculate_static_base_threshold(samples)
        tmpl = StaticTemplate(
            gesture_id=idx,
            gesture_name=p_name.replace("_", " ").title(),
            hand=Hand.RIGHT,
            samples=tuple(samples),
            base_threshold=thresh,
            threshold_scale=1.0,
        )
        templates.append(tmpl)

    snapshot = TemplateSnapshot(
        revision=1,
        templates=tuple(templates),
        revision_map={t.gesture_id: 1 for t in templates},
        timestamp_utc="",
    )

    results: Dict[str, Dict[str, int]] = {p: {"attempts": 0, "accepted": 0, "confused": 0, "missed": 0} for p in poses}
    latencies: Dict[str, List[float]] = {p: [] for p in poses}
    clock = ReplayClock()

    for p_name in poses:
        p_title = p_name.replace("_", " ").title()
        expected_id = next(t.gesture_id for t in templates if t.gesture_name == p_title)

        num_trials = 25
        for trial in range(num_trials):
            results[p_name]["attempts"] += 1
            engine = RecognitionEngine(clock=clock)

            w_seq, img_seq, ts_seq = generate_fixture_sequence(
                pose_name=p_name,
                num_frames=45,
                noise_sigma=0.005,
                fps=30.0,
                seed=500 + trial,
            )

            fired_event = None
            first_frame_ts = ts_seq[0]

            for f_idx in range(len(ts_seq)):
                clock.set_ns(int(ts_seq[f_idx]))
                obs = HandObservation(
                    label="Right",
                    label_score=0.99,
                    presence_score=0.99,
                    landmarks_image=img_seq[f_idx],
                    landmarks_world=w_seq[f_idx],
                )
                tr = TrackingResult(
                    frame_id=f_idx,
                    capture_ts_ns=int(ts_seq[f_idx]),
                    frame_size=(640, 480),
                    status=TrackingStatus.OK,
                    hands=(obs,),
                )
                analysis, event = engine.process(tr, snapshot, tracked_hand=Hand.RIGHT)
                if event is not None and fired_event is None:
                    fired_event = event
                    latencies[p_name].append((event.capture_ts_ns - first_frame_ts) / 1e6)

            if fired_event is not None:
                if fired_event.gesture_id == expected_id:
                    results[p_name]["accepted"] += 1
                else:
                    results[p_name]["confused"] += 1
            else:
                results[p_name]["missed"] += 1

    print(f"{'Pose':<15} | {'Attempts':<8} | {'True Acc':<10} | {'Wilson 95% CI':<18} | {'Latency (ms)':<12}")
    print("-" * 70)

    all_passed = True
    for p_name, res in results.items():
        p_title = p_name.replace("_", " ").title()
        att = res["attempts"]
        acc = res["accepted"]
        rate = (acc / float(att)) * 100.0 if att > 0 else 0.0
        ci_low, ci_high = wilson_score_interval(acc, att)
        avg_lat = np.mean(latencies[p_name]) if latencies[p_name] else 0.0
        ci_str = f"[{ci_low*100.0:.1f}%, {ci_high*100.0:.1f}%]"
        print(f"{p_title:<15} | {att:<8} | {rate:>6.1f}%    | {ci_str:<18} | {avg_lat:>6.1f} ms")
        if rate < 90.0:
            all_passed = False

    return all_passed


def evaluate_dynamic_gestures() -> bool:
    from gestures.segmenter import MotionSegmenter

    dynamic_gestures = ["swipe_right", "swipe_left", "swipe_up"]

    print("\n" + "=" * 70)
    print("Dynamic Gesture Evaluation Benchmark (§7.5 / AC-05 / Speed Robustness)")
    print("=" * 70)

    # 1. Compile dynamic templates using MotionSegmenter
    templates: List[DynamicTemplate] = []
    w, h = 640, 480

    for idx, d_name in enumerate(dynamic_gestures, start=10):
        samples = []
        for s_idx in range(3):
            world_seq, img_seq, ts_seq = generate_dynamic_motion_sequence(
                d_name, n_motion_frames=18, noise_sigma=0.002, seed=200 + s_idx
            )
            # Run through MotionSegmenter
            segm = MotionSegmenter()
            for f in range(len(ts_seq)):
                st = segm.update(world_seq[f], img_seq[f], w, h, int(ts_seq[f]))
                if st.name == "ENDED":
                    seg = segm.pop_segment()
                    if seg is not None:
                        ref_wrist = seg.frames[0].wrist_corrected
                        steps = [
                            extract_dynamic_step_features(
                                sf.landmarks_world, sf.landmarks_image, w, h, ref_wrist, seg.segment_palm_scale
                            )
                            for sf in seg.frames
                        ]
                        resampled = resample_step_vectors(np.stack(steps), seg.timestamps_ms)
                        if resampled is not None:
                            samples.append(resampled)
                    break

        thresh = calculate_dynamic_base_threshold(samples)
        tmpl = DynamicTemplate(
            gesture_id=idx,
            gesture_name=d_name.replace("_", " ").title(),
            hand=Hand.RIGHT,
            samples=tuple(samples),
            base_threshold=max(thresh, 0.30),
        )
        templates.append(tmpl)

    snapshot = TemplateSnapshot(
        revision=1,
        templates=tuple(templates),
        revision_map={t.gesture_id: 1 for t in templates},
        timestamp_utc="",
    )

    results: Dict[str, Dict[str, int]] = {d: {"attempts": 0, "accepted": 0, "confused": 0, "missed": 0} for d in dynamic_gestures}
    latencies: Dict[str, List[float]] = {d: [] for d in dynamic_gestures}
    clock = ReplayClock()

    # Replay trials with speed variations: 15 frames (fast), 18 frames (normal), 24 frames (slow)
    variations = [15, 18, 24]

    for d_name in dynamic_gestures:
        p_title = d_name.replace("_", " ").title()
        expected_id = next(t.gesture_id for t in templates if t.gesture_name == p_title)

        for n_frames in variations:
            for rep in range(10):  # 30 trials per gesture
                results[d_name]["attempts"] += 1
                engine = RecognitionEngine(clock=clock)

                w_seq, img_seq, ts_seq = generate_dynamic_motion_sequence(
                    direction=d_name,
                    n_motion_frames=n_frames,
                    noise_sigma=0.004,
                    seed=700 + rep * 10 + n_frames,
                )

                fired_event = None
                motion_start_ts = ts_seq[8]

                for f_idx in range(len(ts_seq)):
                    clock.set_ns(int(ts_seq[f_idx]))
                    obs = HandObservation(
                        label="Right",
                        label_score=0.99,
                        presence_score=0.99,
                        landmarks_image=img_seq[f_idx],
                        landmarks_world=w_seq[f_idx],
                    )
                    tr = TrackingResult(
                        frame_id=f_idx,
                        capture_ts_ns=int(ts_seq[f_idx]),
                        frame_size=(w, h),
                        status=TrackingStatus.OK,
                        hands=(obs,),
                    )
                    analysis, event = engine.process(tr, snapshot, tracked_hand=Hand.RIGHT)
                    if event is not None and fired_event is None:
                        fired_event = event
                        latencies[d_name].append((event.capture_ts_ns - motion_start_ts) / 1e6)

                if fired_event is not None:
                    if fired_event.gesture_id == expected_id:
                        results[d_name]["accepted"] += 1
                    else:
                        results[d_name]["confused"] += 1
                else:
                    results[d_name]["missed"] += 1

    print(f"{'Dynamic Gesture':<16} | {'Attempts':<8} | {'True Acc':<10} | {'Wilson 95% CI':<18} | {'Latency (ms)':<12}")
    print("-" * 70)

    all_passed = True
    for d_name, res in results.items():
        p_title = d_name.replace("_", " ").title()
        att = res["attempts"]
        acc = res["accepted"]
        rate = (acc / float(att)) * 100.0 if att > 0 else 0.0
        ci_low, ci_high = wilson_score_interval(acc, att)
        avg_lat = np.mean(latencies[d_name]) if latencies[d_name] else 0.0
        ci_str = f"[{ci_low*100.0:.1f}%, {ci_high*100.0:.1f}%]"
        print(f"{p_title:<16} | {att:<8} | {rate:>6.1f}%    | {ci_str:<18} | {avg_lat:>6.1f} ms")
        # Criterion AC-05: dynamic true accept >= 90%
        if rate < 90.0:
            all_passed = False

    return all_passed


def run_evaluation() -> int:
    static_ok = evaluate_static_gestures()
    dynamic_ok = evaluate_dynamic_gestures()
    all_ok = static_ok and dynamic_ok

    print("\n" + "=" * 70)
    print(f"Overall Benchmark Status: {'PASSED' if all_ok else 'NEEDS_TUNING'}")
    print("=" * 70)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(run_evaluation())
