"""Loads, validates, and compiles in-memory gesture templates into a TemplateSnapshot."""

from __future__ import annotations

import datetime
from typing import Dict, List, Tuple
import numpy as np

from app.constants import MODEL_VERSION
from database.repositories.gesture_repository import GestureRepository
from domain.enums import GestureType, SnapshotExclusionReason
from domain.models import SnapshotReport, TemplateSnapshot
from gestures.calibration import (
    calculate_dynamic_base_threshold,
    calculate_static_base_threshold,
)
from gestures.dynamic_matcher import DynamicTemplate
from gestures.feature_extractor import (
    extract_dynamic_step_features,
    extract_static_features,
)
from gestures.normalizer import (
    DegenerateHandError,
    aspect_correct_image_landmarks,
    compute_palm_unit_image,
)
from gestures.resampler import resample_step_vectors
from gestures.static_matcher import StaticTemplate


class TemplateLoader:
    """Compiles persistent gesture records into an immutable TemplateSnapshot."""

    def __init__(self, gesture_repo: GestureRepository) -> None:
        self._gesture_repo = gesture_repo

    def load_snapshot(self, revision: int = 1) -> TemplateSnapshot:
        """Loads enabled gestures from the database and compiles valid templates.
        
        Section 673 & Section 3.4:
        Validates versions and shapes, derives features and thresholds,
        records excluded items in SnapshotReport, and returns TemplateSnapshot.
        """
        all_gestures = self._gesture_repo.list_all(enabled_only=True)
        
        compiled_templates: List[Any] = []
        revision_map: Dict[int, int] = {}
        excluded_gestures: List[Tuple[int, str, SnapshotExclusionReason]] = []

        for gesture in all_gestures:
            assert gesture.id is not None
            samples = self._gesture_repo.get_samples_for_gesture(gesture.id)

            if not samples:
                excluded_gestures.append(
                    (gesture.id, gesture.name, SnapshotExclusionReason.NEEDS_RERECORDING)
                )
                continue

            if gesture.gesture_type == GestureType.STATIC:
                valid_features: List[np.ndarray] = []
                exclusion_reason: SnapshotExclusionReason | None = None

                for s in samples:
                    # Validate tracker model
                    if s.tracker_model_id != MODEL_VERSION:
                        exclusion_reason = SnapshotExclusionReason.UNSUPPORTED_TRACKER_MODEL
                        break

                    # Validate world landmarks shape
                    if s.landmarks_world.ndim != 3 or s.landmarks_world.shape[1:] != (21, 3):
                        exclusion_reason = SnapshotExclusionReason.INVALID_LANDMARKS
                        break

                    # Each sample might have frame_count frames (usually 1 for static)
                    for frame_idx in range(s.frame_count):
                        frame_world = s.landmarks_world[frame_idx]  # (21, 3)
                        try:
                            feat = extract_static_features(frame_world)
                            valid_features.append(feat)
                        except (DegenerateHandError, ValueError):
                            exclusion_reason = SnapshotExclusionReason.INVALID_LANDMARKS
                            break
                    if exclusion_reason:
                        break

                if exclusion_reason or not valid_features:
                    reason = exclusion_reason or SnapshotExclusionReason.INVALID_LANDMARKS
                    excluded_gestures.append((gesture.id, gesture.name, reason))
                    continue

                # Calibrate base threshold
                base_threshold = calculate_static_base_threshold(valid_features)

                template = StaticTemplate(
                    gesture_id=gesture.id,
                    gesture_name=gesture.name,
                    hand=gesture.hand,
                    samples=tuple(valid_features),
                    base_threshold=base_threshold,
                    threshold_scale=gesture.threshold_scale,
                )
                compiled_templates.append(template)
                revision_map[gesture.id] = gesture.template_revision

            elif gesture.gesture_type == GestureType.DYNAMIC:
                valid_resampled_samples: List[np.ndarray] = []
                exclusion_reason: SnapshotExclusionReason | None = None

                for s in samples:
                    if s.tracker_model_id != MODEL_VERSION:
                        exclusion_reason = SnapshotExclusionReason.UNSUPPORTED_TRACKER_MODEL
                        break

                    if (
                        s.landmarks_world.ndim != 3
                        or s.landmarks_world.shape[1:] != (21, 3)
                        or s.landmarks_image.ndim != 3
                        or s.landmarks_image.shape[1:] != (21, 3)
                        or s.timestamps_ms is None
                        or len(s.timestamps_ms) != s.frame_count
                        or s.frame_count < 2
                    ):
                        exclusion_reason = SnapshotExclusionReason.INVALID_LANDMARKS
                        break

                    # Compute aspect-corrected landmarks and median palm scale
                    aspect = s.frame_aspect_ratio if s.frame_aspect_ratio > 0 else 4.0 / 3.0
                    w_dummy = int(aspect * 1000)
                    h_dummy = 1000

                    palms: List[float] = []
                    corrected_images: List[np.ndarray] = []
                    for f_idx in range(s.frame_count):
                        corr = aspect_correct_image_landmarks(s.landmarks_image[f_idx], w_dummy, h_dummy)
                        corrected_images.append(corr)
                        p = compute_palm_unit_image(corr)
                        if p > 1e-4:
                            palms.append(p)

                    median_palm = float(np.median(palms)) if palms else 1.0
                    median_palm = max(median_palm, 1e-4)
                    ref_wrist = corrected_images[0][0, :2]

                    # Extract step vectors
                    step_list: List[np.ndarray] = []
                    step_error = False
                    for f_idx in range(s.frame_count):
                        try:
                            step_vec = extract_dynamic_step_features(
                                landmarks_world=s.landmarks_world[f_idx],
                                landmarks_image=s.landmarks_image[f_idx],
                                frame_width=w_dummy,
                                frame_height=h_dummy,
                                ref_wrist_image=ref_wrist,
                                segment_palm_scale=median_palm,
                            )
                            step_list.append(step_vec)
                        except (DegenerateHandError, ValueError):
                            step_error = True
                            break

                    if step_error:
                        exclusion_reason = SnapshotExclusionReason.INVALID_LANDMARKS
                        break

                    # Resample step vectors to 15 Hz grid
                    steps_arr = np.stack(step_list, axis=0)
                    resampled = resample_step_vectors(steps_arr, s.timestamps_ms)
                    if resampled is None:
                        exclusion_reason = SnapshotExclusionReason.INVALID_LANDMARKS
                        break

                    valid_resampled_samples.append(resampled)

                if exclusion_reason or not valid_resampled_samples:
                    reason = exclusion_reason or SnapshotExclusionReason.INVALID_LANDMARKS
                    excluded_gestures.append((gesture.id, gesture.name, reason))
                    continue

                # Calibrate dynamic base threshold
                dyn_base_threshold = calculate_dynamic_base_threshold(valid_resampled_samples)

                dyn_template = DynamicTemplate(
                    gesture_id=gesture.id,
                    gesture_name=gesture.name,
                    hand=gesture.hand,
                    samples=tuple(valid_resampled_samples),
                    base_threshold=dyn_base_threshold,
                    threshold_scale=gesture.threshold_scale,
                )
                compiled_templates.append(dyn_template)
                revision_map[gesture.id] = gesture.template_revision

        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        report = SnapshotReport(
            excluded_gestures=tuple(excluded_gestures),
            excluded_workflows=(),
        )

        return TemplateSnapshot(
            revision=revision,
            templates=tuple(compiled_templates),
            revision_map=revision_map,
            timestamp_utc=now_utc,
            report=report,
        )
