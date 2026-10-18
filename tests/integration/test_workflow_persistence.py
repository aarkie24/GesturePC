"""Integration tests for workflow and action persistence."""

import numpy as np
import pytest

from app.constants import TRACKER_MODEL_ID
from database.repositories.gesture_repository import GestureRepository
from database.repositories.workflow_repository import WorkflowRepository
from domain.enums import GestureType, Hand
from domain.exceptions import InvalidWorkflow
from domain.models import Gesture, GestureSample, Workflow, WorkflowAction


def test_workflow_lifecycle_and_constraints(temp_db_conn):
    gesture_repo = GestureRepository(temp_db_conn)
    workflow_repo = WorkflowRepository(temp_db_conn)

    # 1. Create a parent gesture
    sample_img = np.zeros((1, 21, 3), dtype=np.float32)
    sample = GestureSample(
        id=None,
        gesture_id=0,
        sample_index=0,
        frame_count=1,
        duration_ms=0,
        landmarks_image=sample_img,
        landmarks_world=sample_img,
        timestamps_ms=None,
        frame_aspect_ratio=1.33,
        tracker_model_id=TRACKER_MODEL_ID,
        preprocess_json="{}",
    )
    gesture = gesture_repo.create(
        Gesture(id=None, name="Swipe Left", gesture_type=GestureType.DYNAMIC, hand=Hand.RIGHT),
        [sample],
    )

    # 2. Create Default Workflow with 2 actions
    act1 = WorkflowAction(id=None, workflow_id=None, position=0, action_type="KEYBOARD_HOTKEY", parameters_json='{"keys": ["Alt", "Tab"]}')
    act2 = WorkflowAction(id=None, workflow_id=None, position=1, action_type="DELAY", parameters_json='{"delay_ms": 100}')

    wf = Workflow(
        id=None,
        gesture_id=gesture.id,
        name="Switch Window",
        context_app_id=None,  # Default workflow
        enabled=True,
    )
    created_wf = workflow_repo.create(wf, [act1, act2])
    assert created_wf.id is not None
    assert len(created_wf.actions) == 2
    assert created_wf.actions[0].action_type == "KEYBOARD_HOTKEY"
    assert created_wf.actions[1].action_type == "DELAY"

    # 3. Constraint: Only one default workflow per gesture
    duplicate_default = Workflow(
        id=None,
        gesture_id=gesture.id,
        name="Another Default",
        context_app_id=None,
    )
    with pytest.raises(InvalidWorkflow, match="already exists"):
        workflow_repo.create(duplicate_default, [act1])

    # 4. App-specific workflow is allowed
    app_wf = Workflow(
        id=None,
        gesture_id=gesture.id,
        name="Browser Back",
        context_app_id="chrome.exe",
    )
    created_app_wf = workflow_repo.create(app_wf, [act1])
    assert created_app_wf.id is not None
    assert created_app_wf.context_app_id == "chrome.exe"

    # 5. Atomically replace actions
    new_act = WorkflowAction(id=None, workflow_id=None, position=0, action_type="MOUSE_CLICK", parameters_json='{"button": "left"}')
    workflow_repo.update(created_wf, actions=[new_act])
    updated = workflow_repo.get_by_id(created_wf.id)
    assert len(updated.actions) == 1
    assert updated.actions[0].action_type == "MOUSE_CLICK"

    # 6. Cascade delete: Deleting parent gesture removes workflows and actions
    gesture_repo.delete(gesture.id)
    assert workflow_repo.get_by_id(created_wf.id) is None
    assert workflow_repo.get_by_id(created_app_wf.id) is None

    # Check foreign keys
    cursor = temp_db_conn.cursor()
    cursor.execute("PRAGMA foreign_key_check;")
    assert cursor.fetchall() == []
    cursor.close()
