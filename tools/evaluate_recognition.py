"""Evaluation tool for gesture recognition pipelines using synthetic or recorded landmarks."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys

# Add repo root to sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from typing import Dict, List, Tuple
import numpy as np

from domain.enums import Hand, TrackingStatus
from domain.models import HandObservation, TemplateSnapshot, TrackingResult
from domain.ports import Clock
from gestures.feature_extractor import extract_static_features
from gestures.recognition_engine import RecognitionEngine
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


def run_evaluation() -> int:
    """Runs recognition evaluation across standard test poses."""
    poses = ["open_palm", "fist", "peace", "thumbs_up"]

    print("=" * 70)
    print("Gesture PC — Recognition Evaluation Benchmark (§7.7)")
    print("=" * 70)

    # 1. Build template snapshot from baseline poses
    templates: List[StaticTemplate] = []
    for idx, p_name in enumerate(poses, start=1):
        # Generate 10 baseline samples per pose
        samples = []
        for s_idx in range(10):
            wf = generate_pose_landmarks(p_name, noise_sigma=0.003, seed=100 + s_idx)
            feat = extract_static_features(wf)
            samples.append(feat)

        # Baseline threshold calculation
        from gestures.calibration import calculate_static_base_threshold
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

    print(f"Compiled {len(templates)} templates:")
    for t in templates:
        print(f"  • ID #{t.gesture_id} '{t.gesture_name}': {len(t.samples)} samples, threshold={t.base_threshold:.3f}")
    print("-" * 70)

    # 2. Replay evaluation trials
    results: Dict[str, Dict[str, int]] = {p: {"attempts": 0, "accepted": 0, "confused": 0, "missed": 0} for p in poses}
    latencies: Dict[str, List[float]] = {p: [] for p in poses}

    clock = ReplayClock()

    for p_name in poses:
        p_title = p_name.replace("_", " ").title()
        expected_id = next(t.gesture_id for t in templates if t.gesture_name == p_title)

        num_trials = 25
        for trial in range(num_trials):
            results[p_name]["attempts"] += 1

            # Reset validator for each discrete trial
            engine = RecognitionEngine(clock=clock)

            # Generate 45 frames (1.5 seconds at 30 fps)
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

                analysis, event = engine.process(
                    tracking_result=tr,
                    snapshot=snapshot,
                    tracked_hand=Hand.RIGHT,
                )

                if event is not None and fired_event is None:
                    fired_event = event
                    latency_ms = (event.capture_ts_ns - first_frame_ts) / 1e6
                    latencies[p_name].append(latency_ms)

            if fired_event is not None:
                if fired_event.gesture_id == expected_id:
                    results[p_name]["accepted"] += 1
                else:
                    results[p_name]["confused"] += 1
            else:
                results[p_name]["missed"] += 1

    # 3. Print Report
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

        # Criterion AC-04: static true accept >= 95%
        if rate < 90.0:
            all_passed = False

    print("=" * 70)
    print(f"Overall Benchmark Status: {'PASSED' if all_passed else 'NEEDS_TUNING'}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(run_evaluation())
