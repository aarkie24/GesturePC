"""Integration tests for gesture and sample database persistence."""

import numpy as np
import pytest

from app.constants import TRACKER_MODEL_ID
from database.repositories.gesture_repository import GestureRepository
from domain.enums import GestureType, Hand
from domain.exceptions import DuplicateGestureName
from domain.models import Gesture, GestureSample


def test_gesture_crud_lifecycle(temp_db_conn):
    repo = GestureRepository(temp_db_conn)

    # 1. Create Gesture with samples
    sample_img = np.random.uniform(0.0, 1.0, (1, 21, 3)).astype(np.float32)
    sample_world = np.random.uniform(-0.1, 0.1, (1, 21, 3)).astype(np.float32)

    sample1 = GestureSample(
        id=None,
        gesture_id=0,
        sample_index=0,
        frame_count=1,
        duration_ms=0,
        landmarks_image=sample_img,
        landmarks_world=sample_world,
        timestamps_ms=None,
        frame_aspect_ratio=640.0 / 480.0,
        tracker_model_id=TRACKER_MODEL_ID,
        preprocess_json="{}",
    )

    gesture = Gesture(
        id=None,
        name="Thumbs Up",
        gesture_type=GestureType.STATIC,
        hand=Hand.RIGHT,
        enabled=True,
        threshold_scale=1.0,
    )

    created = repo.create(gesture, [sample1])
    assert created.id is not None
    assert created.name == "Thumbs Up"
    assert created.template_revision == 1

    # 2. Fetch gesture by ID and Name
    fetched_by_id = repo.get_by_id(created.id)
    assert fetched_by_id is not None
    assert fetched_by_id.name == "Thumbs Up"

    fetched_by_name = repo.get_by_name("thumbs up")  # Case-insensitive
    assert fetched_by_name is not None
    assert fetched_by_name.id == created.id

    # 3. Verify samples
    samples = repo.get_samples_for_gesture(created.id)
    assert len(samples) == 1
    np.testing.assert_array_equal(samples[0].landmarks_image, sample_img)
    np.testing.assert_array_equal(samples[0].landmarks_world, sample_world)

    # 4. Enforce case-insensitive unique constraint
    duplicate = Gesture(
        id=None,
        name="THUMBS UP",
        gesture_type=GestureType.STATIC,
        hand=Hand.RIGHT,
    )
    with pytest.raises(DuplicateGestureName):
        repo.create(duplicate, [sample1])

    # 5. Re-record (replaces samples, increments revision)
    new_img = np.random.uniform(0.0, 1.0, (1, 21, 3)).astype(np.float32)
    sample2 = GestureSample(
        id=None,
        gesture_id=created.id,
        sample_index=0,
        frame_count=1,
        duration_ms=0,
        landmarks_image=new_img,
        landmarks_world=sample_world,
        timestamps_ms=None,
        frame_aspect_ratio=640.0 / 480.0,
        tracker_model_id=TRACKER_MODEL_ID,
        preprocess_json="{}",
    )
    new_rev = repo.rerecord(created.id, [sample2])
    assert new_rev == 2

    re_fetched = repo.get_by_id(created.id)
    assert re_fetched.template_revision == 2
    updated_samples = repo.get_samples_for_gesture(created.id)
    assert len(updated_samples) == 1
    np.testing.assert_array_equal(updated_samples[0].landmarks_image, new_img)

    # 6. Delete gesture (cascade)
    deleted = repo.delete(created.id)
    assert deleted is True
    assert repo.get_by_id(created.id) is None
    assert len(repo.get_samples_for_gesture(created.id)) == 0

    # Ensure foreign keys remain clean
    cursor = temp_db_conn.cursor()
    cursor.execute("PRAGMA foreign_key_check;")
    assert cursor.fetchall() == []
    cursor.close()


def test_dynamic_gesture_persistence_and_snapshot(temp_db_conn):
    from gestures.dynamic_matcher import DynamicTemplate
    from gestures.template_loader import TemplateLoader

    repo = GestureRepository(temp_db_conn)

    # 1. Create multi-frame dynamic gesture sample
    frame_count = 20
    ts_ms = np.linspace(0, 600, frame_count).astype(np.int32)
    world = np.zeros((frame_count, 21, 3), dtype=np.float32)
    img = np.zeros((frame_count, 21, 3), dtype=np.float32)

    for i in range(frame_count):
        # Middle MCP
        world[i, 9, 1] = 0.08
        img[i, 0, :2] = [0.5 + 0.01 * i, 0.5]
        img[i, 9, :2] = [0.5 + 0.01 * i, 0.35]

    sample = GestureSample(
        id=None,
        gesture_id=0,
        sample_index=0,
        frame_count=frame_count,
        duration_ms=600,
        landmarks_image=img,
        landmarks_world=world,
        timestamps_ms=ts_ms,
        frame_aspect_ratio=4.0 / 3.0,
        tracker_model_id=TRACKER_MODEL_ID,
        preprocess_json="{}",
    )

    gesture = Gesture(
        id=None,
        name="Swipe Right",
        gesture_type=GestureType.DYNAMIC,
        hand=Hand.RIGHT,
    )

    created = repo.create(gesture, [sample])
    assert created.id is not None
    assert created.gesture_type == GestureType.DYNAMIC

    # 2. Verify persistence roundtrip
    saved_samples = repo.get_samples_for_gesture(created.id)
    assert len(saved_samples) == 1
    assert saved_samples[0].frame_count == frame_count
    assert saved_samples[0].timestamps_ms is not None
    np.testing.assert_array_equal(saved_samples[0].timestamps_ms, ts_ms)
    np.testing.assert_array_equal(saved_samples[0].landmarks_image, img)
    np.testing.assert_array_equal(saved_samples[0].landmarks_world, world)

    # 3. Verify TemplateLoader compiles DynamicTemplate
    loader = TemplateLoader(repo)
    snapshot = loader.load_snapshot(revision=1)
    assert len(snapshot.templates) == 1
    tmpl = snapshot.templates[0]
    assert isinstance(tmpl, DynamicTemplate)
    assert tmpl.gesture_name == "Swipe Right"
    assert len(tmpl.samples) == 1
    assert tmpl.base_threshold > 0.0

