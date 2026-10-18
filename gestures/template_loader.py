"""Loads, validates, and compiles in-memory gesture templates into a TemplateSnapshot."""

from __future__ import annotations

import datetime
from typing import Dict, List, Tuple
import numpy as np

from app.constants import MODEL_VERSION
from database.repositories.gesture_repository import GestureRepository
from domain.enums import GestureType, SnapshotExclusionReason
from domain.models import SnapshotReport, TemplateSnapshot
from gestures.calibration import calculate_static_base_threshold
from gestures.feature_extractor import extract_static_features
from gestures.normalizer import DegenerateHandError
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
        
        compiled_templates: List[StaticTemplate] = []
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
