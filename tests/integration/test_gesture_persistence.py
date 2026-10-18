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
