"""Application service for gesture lifecycle management, collision checking, and persistence."""

from __future__ import annotations

import logging
from typing import List, Optional, Sequence, Tuple
import numpy as np

from database.repositories.gesture_repository import GestureRepository
from domain.enums import GestureType, Hand
from domain.events import GestureDeleted, GestureRegistered, GestureUpdated
from domain.exceptions import DuplicateGestureName
from domain.models import Gesture, GestureSample
from gestures.calibration import (
    calculate_static_base_threshold,
    check_static_collisions,
)
from gestures.feature_extractor import extract_static_features
from gestures.normalizer import DegenerateHandError
from services.event_bus import EventBus
from services.snapshot_service import SnapshotService

logger = logging.getLogger(__name__)


class GestureService:
    """Manages gesture registration, modification, collision validation, and deletion."""

    def __init__(
        self,
        gesture_repo: GestureRepository,
        snapshot_service: SnapshotService,
        event_bus: EventBus,
    ) -> None:
        self._gesture_repo = gesture_repo
        self._snapshot_service = snapshot_service
        self._event_bus = event_bus

    def list_gestures(self, enabled_only: bool = False) -> List[Gesture]:
        """Returns all registered gestures ordered by name."""
        return self._gesture_repo.list_all(enabled_only=enabled_only)

    def get_gesture(self, gesture_id: int) -> Optional[Gesture]:
        """Retrieves a gesture by ID."""
        return self._gesture_repo.get_by_id(gesture_id)

    def get_samples(self, gesture_id: int) -> List[GestureSample]:
        """Retrieves all landmark observation samples for a gesture."""
        return self._gesture_repo.get_samples_for_gesture(gesture_id)

    def check_static_collisions(
        self,
        samples: Sequence[GestureSample],
        hand: Hand,
        exclude_gesture_id: Optional[int] = None,
    ) -> List[Tuple[str, float]]:
        """Checks for collisions between new static samples and existing enabled static gestures of same hand.
        
        Returns:
            List of (existing_gesture_name, collision_distance_palm_units)
        """
        # Extract features for new samples
        new_feats: List[np.ndarray] = []
        for s in samples:
            for f_idx in range(s.frame_count):
                try:
                    feat = extract_static_features(s.landmarks_world[f_idx])
                    new_feats.append(feat)
                except (DegenerateHandError, ValueError):
                    pass

        if not new_feats:
            return []

        new_base_threshold = calculate_static_base_threshold(new_feats)

        # Retrieve existing enabled static gestures
        existing_gestures = self._gesture_repo.list_all(enabled_only=True)
        existing_tuples: List[Tuple[str, Sequence[np.ndarray], float]] = []

        for eg in existing_gestures:
            if eg.id == exclude_gesture_id or eg.gesture_type != GestureType.STATIC:
                continue
            if eg.hand != hand and eg.hand != Hand.EITHER and hand != Hand.EITHER:
                continue

            assert eg.id is not None
            eg_samples = self._gesture_repo.get_samples_for_gesture(eg.id)
            eg_feats: List[np.ndarray] = []
            for s in eg_samples:
                for f_idx in range(s.frame_count):
                    try:
                        feat = extract_static_features(s.landmarks_world[f_idx])
                        eg_feats.append(feat)
                    except (DegenerateHandError, ValueError):
                        pass

            if eg_feats:
                eg_thresh = calculate_static_base_threshold(eg_feats) * eg.threshold_scale
                existing_tuples.append((eg.name, eg_feats, eg_thresh))

        return check_static_collisions(
            new_sample_features=new_feats,
            new_threshold=new_base_threshold,
            existing_gestures=existing_tuples,
        )

    def create_gesture(
        self,
        name: str,
        gesture_type: GestureType,
        hand: Hand,
        samples: Sequence[GestureSample],
        threshold_scale: float = 1.0,
        allow_collision: bool = False,
    ) -> Tuple[Optional[Gesture], List[Tuple[str, float]]]:
        """Creates and saves a new gesture entity and its samples.
        
        Section 7.4: Collision check before saving.
        If collisions are detected and allow_collision is False, save is blocked.
        
        Returns:
            (created_gesture, collisions_list)
        """
        collisions: List[Tuple[str, float]] = []
        if gesture_type == GestureType.STATIC:
            collisions = self.check_static_collisions(samples, hand)
            if collisions and not allow_collision:
                return None, collisions

        new_gesture = Gesture(
            id=None,
            name=name.strip(),
            gesture_type=gesture_type,
            hand=hand,
            enabled=True,
            threshold_scale=threshold_scale,
            template_revision=1,
        )

        persisted = self._gesture_repo.create(new_gesture, samples)
        assert persisted.id is not None

        logger.info("Created gesture '%s' (id=%d, type=%s)", persisted.name, persisted.id, persisted.gesture_type.value)
        self._event_bus.publish(GestureRegistered(gesture_id=persisted.id, name=persisted.name))
        self._snapshot_service.request_rebuild()

        return persisted, collisions

    def update_gesture(
        self,
        gesture_id: int,
        name: Optional[str] = None,
        enabled: Optional[bool] = None,
        threshold_scale: Optional[float] = None,
    ) -> Gesture:
        """Updates gesture metadata (name, enabled state, sensitivity scale)."""
        existing = self._gesture_repo.get_by_id(gesture_id)
        if existing is None:
            raise ValueError(f"Gesture with ID {gesture_id} does not exist.")

        updated = Gesture(
            id=existing.id,
            name=name.strip() if name is not None else existing.name,
            gesture_type=existing.gesture_type,
            hand=existing.hand,
            enabled=enabled if enabled is not None else existing.enabled,
            threshold_scale=threshold_scale if threshold_scale is not None else existing.threshold_scale,
            template_revision=existing.template_revision,
            created_at=existing.created_at,
            updated_at=existing.updated_at,
        )

        self._gesture_repo.update(updated)
        logger.info("Updated gesture id=%d ('%s')", gesture_id, updated.name)
        self._event_bus.publish(GestureUpdated(gesture_id=gesture_id, name=updated.name))
        self._snapshot_service.request_rebuild()
        return updated

    def rerecord_samples(
        self,
        gesture_id: int,
        samples: Sequence[GestureSample],
        allow_collision: bool = False,
    ) -> Tuple[Optional[Gesture], List[Tuple[str, float]]]:
        """Re-records samples for an existing gesture and increments template revision."""
        existing = self._gesture_repo.get_by_id(gesture_id)
        if existing is None:
            raise ValueError(f"Gesture with ID {gesture_id} does not exist.")

        collisions: List[Tuple[str, float]] = []
        if existing.gesture_type == GestureType.STATIC:
            collisions = self.check_static_collisions(samples, existing.hand, exclude_gesture_id=gesture_id)
            if collisions and not allow_collision:
                return None, collisions

        new_rev = self._gesture_repo.rerecord(gesture_id, samples)
        updated = self._gesture_repo.get_by_id(gesture_id)
        assert updated is not None

        logger.info("Re-recorded samples for gesture id=%d (new revision=%d)", gesture_id, new_rev)
        self._event_bus.publish(GestureUpdated(gesture_id=gesture_id, name=updated.name))
        self._snapshot_service.request_rebuild()
        return updated, collisions

    def delete_gesture(self, gesture_id: int) -> bool:
        """Deletes a gesture (cascading to samples and workflows)."""
        existing = self._gesture_repo.get_by_id(gesture_id)
        name = existing.name if existing else str(gesture_id)

        deleted = self._gesture_repo.delete(gesture_id)
        if deleted:
            logger.info("Deleted gesture id=%d ('%s')", gesture_id, name)
            self._event_bus.publish(GestureDeleted(gesture_id=gesture_id, name=name))
            self._snapshot_service.request_rebuild()
        return deleted
