"""Unit tests for TemplateLoader and SnapshotService."""

import numpy as np
import pytest

from app.constants import MODEL_VERSION
from database.repositories.gesture_repository import GestureRepository
from domain.enums import GestureType, Hand, SnapshotExclusionReason
from domain.models import Gesture, GestureSample
from gestures.template_loader import TemplateLoader
from services.event_bus import EventBus
from services.snapshot_service import SnapshotHolder, SnapshotService
from tests.fixtures.generate import generate_pose_landmarks


def test_snapshot_compilation_and_exclusions(temp_db_conn):
    """TemplateLoader loads valid gestures and excludes invalid/empty ones with SnapshotReport."""
    repo = GestureRepository(temp_db_conn)
    bus = EventBus()
    loader = TemplateLoader(repo)
    service = SnapshotService(loader, bus)

    # 1. Gesture with valid samples
    wf = generate_pose_landmarks("open_palm", noise_sigma=0.0)
    img_wf = np.full((1, 21, 3), 0.5, dtype=np.float32)
    world_wf = np.expand_dims(wf, axis=0)

    g1 = Gesture(None, "Valid Palm", GestureType.STATIC, Hand.RIGHT, enabled=True)
    sample1 = GestureSample(
        id=None,
        gesture_id=0,
        sample_index=0,
        frame_count=1,
        duration_ms=0,
        landmarks_image=img_wf,
        landmarks_world=world_wf,
        timestamps_ms=None,
        frame_aspect_ratio=1.333,
        tracker_model_id=MODEL_VERSION,
        preprocess_json="{}",
    )
    repo.create(g1, [sample1])

    # 2. Gesture with no samples -> excluded with NEEDS_RERECORDING
    g2 = Gesture(None, "Empty Gesture", GestureType.STATIC, Hand.RIGHT, enabled=True)
    repo.create(g2, [])

    # Rebuild snapshot
    snapshot = service.rebuild_now()

    assert len(snapshot.templates) == 1
    assert snapshot.templates[0].gesture_name == "Valid Palm"
    assert len(snapshot.report.excluded_gestures) == 1
    excluded_id, name, reason = snapshot.report.excluded_gestures[0]
    assert name == "Empty Gesture"
    assert reason == SnapshotExclusionReason.NEEDS_RERECORDING


def test_snapshot_holder_atomic_swap():
    """SnapshotHolder provides safe atomic swap."""
    from domain.models import SnapshotReport, TemplateSnapshot

    holder = SnapshotHolder()
    s1 = TemplateSnapshot(1, (), {}, "2026-10-18T00:00:00Z", SnapshotReport())
    s2 = TemplateSnapshot(2, (), {}, "2026-10-18T01:00:00Z", SnapshotReport())

    holder.set_template_snapshot(s1)
    assert holder.get_template_snapshot().revision == 1

    holder.set_template_snapshot(s2)
    assert holder.get_template_snapshot().revision == 2
