"""SQLite repository for gestures and gesture landmark samples."""

from __future__ import annotations

import datetime
import sqlite3
from typing import List, Optional, Sequence

from database.codecs import (
    decode_landmarks,
    decode_timestamps,
    encode_landmarks,
    encode_timestamps,
)
from domain.enums import GestureType, Hand
from domain.exceptions import DuplicateGestureName
from domain.models import Gesture, GestureSample


class GestureRepository:
    """Provides transactional persistence for gestures and raw landmark observation samples."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, gesture: Gesture, samples: Sequence[GestureSample]) -> Gesture:
        """Saves a new gesture and its associated landmark samples in a single transaction."""
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cursor = self._conn.cursor()

        try:
            cursor.execute("BEGIN IMMEDIATE;")
            cursor.execute(
                """
                INSERT INTO gestures (
                    name, gesture_type, hand, enabled, threshold_scale,
                    template_revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    gesture.name.strip(),
                    gesture.gesture_type.value,
                    gesture.hand.value,
                    1 if gesture.enabled else 0,
                    gesture.threshold_scale,
                    gesture.template_revision,
                    now_utc,
                    now_utc,
                ),
            )
            gesture_id = cursor.lastrowid
            if gesture_id is None:
                raise RuntimeError("Failed to obtain lastrowid for new gesture")

            for idx, sample in enumerate(samples):
                img_blob = encode_landmarks(sample.landmarks_image)
                world_blob = encode_landmarks(sample.landmarks_world)
                ts_blob = encode_timestamps(sample.timestamps_ms)

                cursor.execute(
                    """
                    INSERT INTO gesture_samples (
                        gesture_id, sample_index, frame_count, duration_ms,
                        landmarks_image, landmarks_world, timestamps_ms,
                        frame_aspect_ratio, tracker_model_id, preprocess_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        gesture_id,
                        sample.sample_index if sample.sample_index >= 0 else idx,
                        sample.frame_count,
                        sample.duration_ms,
                        img_blob,
                        world_blob,
                        ts_blob,
                        sample.frame_aspect_ratio,
                        sample.tracker_model_id,
                        sample.preprocess_json,
                        now_utc,
                    ),
                )

            cursor.execute("COMMIT;")
        except sqlite3.IntegrityError as exc:
            cursor.execute("ROLLBACK;")
            cursor.close()
            if "UNIQUE constraint failed: gestures.name" in str(exc) or "gestures.name" in str(exc):
                raise DuplicateGestureName(f"Gesture with name '{gesture.name}' already exists.") from exc
            raise
        except Exception:
            cursor.execute("ROLLBACK;")
            cursor.close()
            raise

        cursor.close()
        return Gesture(
            id=gesture_id,
            name=gesture.name.strip(),
            gesture_type=gesture.gesture_type,
            hand=gesture.hand,
            enabled=gesture.enabled,
            threshold_scale=gesture.threshold_scale,
            template_revision=gesture.template_revision,
            created_at=now_utc,
            updated_at=now_utc,
        )

    def update(self, gesture: Gesture) -> None:
        """Updates gesture metadata (name, enabled status, threshold scale)."""
        if gesture.id is None:
            raise ValueError("Gesture ID must be set for update")

        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE gestures SET
                    name = ?,
                    enabled = ?,
                    threshold_scale = ?,
                    updated_at = ?
                WHERE id = ?;
                """,
                (
                    gesture.name.strip(),
                    1 if gesture.enabled else 0,
                    gesture.threshold_scale,
                    now_utc,
                    gesture.id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            cursor.close()
            if "UNIQUE constraint failed: gestures.name" in str(exc):
                raise DuplicateGestureName(f"Gesture with name '{gesture.name}' already exists.") from exc
            raise
        cursor.close()

    def rerecord(self, gesture_id: int, samples: Sequence[GestureSample]) -> int:
        """Replaces all samples for an existing gesture and increments its template_revision."""
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cursor = self._conn.cursor()

        try:
            cursor.execute("BEGIN IMMEDIATE;")
            # Delete old samples
            cursor.execute("DELETE FROM gesture_samples WHERE gesture_id = ?;", (gesture_id,))

            # Insert new samples
            for idx, sample in enumerate(samples):
                img_blob = encode_landmarks(sample.landmarks_image)
                world_blob = encode_landmarks(sample.landmarks_world)
                ts_blob = encode_timestamps(sample.timestamps_ms)

                cursor.execute(
                    """
                    INSERT INTO gesture_samples (
                        gesture_id, sample_index, frame_count, duration_ms,
                        landmarks_image, landmarks_world, timestamps_ms,
                        frame_aspect_ratio, tracker_model_id, preprocess_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        gesture_id,
                        sample.sample_index if sample.sample_index >= 0 else idx,
                        sample.frame_count,
                        sample.duration_ms,
                        img_blob,
                        world_blob,
                        ts_blob,
                        sample.frame_aspect_ratio,
                        sample.tracker_model_id,
                        sample.preprocess_json,
                        now_utc,
                    ),
                )

            # Increment template_revision
            cursor.execute(
                """
                UPDATE gestures SET
                    template_revision = template_revision + 1,
                    updated_at = ?
                WHERE id = ?;
                """,
                (now_utc, gesture_id),
            )

            cursor.execute("SELECT template_revision FROM gestures WHERE id = ?;", (gesture_id,))
            row = cursor.fetchone()
            new_rev = int(row[0]) if row else 1
            cursor.execute("COMMIT;")
        except Exception:
            cursor.execute("ROLLBACK;")
            cursor.close()
            raise

        cursor.close()
        return new_rev

    def delete(self, gesture_id: int) -> bool:
        """Deletes a gesture (cascades automatically to samples, workflows, and actions)."""
        cursor = self._conn.cursor()
        cursor.execute("DELETE FROM gestures WHERE id = ?;", (gesture_id,))
        deleted = cursor.rowcount > 0
        cursor.close()
        return deleted

    def get_by_id(self, gesture_id: int) -> Optional[Gesture]:
        """Retrieves a gesture record by primary key."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT id, name, gesture_type, hand, enabled, threshold_scale,
                   template_revision, created_at, updated_at
            FROM gestures WHERE id = ?;
            """,
            (gesture_id,),
        )
        row = cursor.fetchone()
        cursor.close()
        if not row:
            return None

        return Gesture(
            id=row["id"],
            name=row["name"],
            gesture_type=GestureType(row["gesture_type"]),
            hand=Hand(row["hand"]),
            enabled=bool(row["enabled"]),
            threshold_scale=float(row["threshold_scale"]),
            template_revision=int(row["template_revision"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_by_name(self, name: str) -> Optional[Gesture]:
        """Retrieves a gesture record by name (case-insensitive via column NOCASE)."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT id, name, gesture_type, hand, enabled, threshold_scale,
                   template_revision, created_at, updated_at
            FROM gestures WHERE name = ?;
            """,
            (name.strip(),),
        )
        row = cursor.fetchone()
        cursor.close()
        if not row:
            return None

        return Gesture(
            id=row["id"],
            name=row["name"],
            gesture_type=GestureType(row["gesture_type"]),
            hand=Hand(row["hand"]),
            enabled=bool(row["enabled"]),
            threshold_scale=float(row["threshold_scale"]),
            template_revision=int(row["template_revision"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_all(self, enabled_only: bool = False) -> List[Gesture]:
        """Lists all stored gestures ordered by name."""
        cursor = self._conn.cursor()
        if enabled_only:
            cursor.execute(
                """
                SELECT id, name, gesture_type, hand, enabled, threshold_scale,
                       template_revision, created_at, updated_at
                FROM gestures WHERE enabled = 1 ORDER BY name ASC;
                """
            )
        else:
            cursor.execute(
                """
                SELECT id, name, gesture_type, hand, enabled, threshold_scale,
                       template_revision, created_at, updated_at
                FROM gestures ORDER BY name ASC;
                """
            )
        rows = cursor.fetchall()
        cursor.close()

        return [
            Gesture(
                id=r["id"],
                name=r["name"],
                gesture_type=GestureType(r["gesture_type"]),
                hand=Hand(r["hand"]),
                enabled=bool(r["enabled"]),
                threshold_scale=float(r["threshold_scale"]),
                template_revision=int(r["template_revision"]),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    def get_samples_for_gesture(self, gesture_id: int) -> List[GestureSample]:
        """Retrieves and decodes all landmark samples for a gesture."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT id, gesture_id, sample_index, frame_count, duration_ms,
                   landmarks_image, landmarks_world, timestamps_ms,
                   frame_aspect_ratio, tracker_model_id, preprocess_json, created_at
            FROM gesture_samples
            WHERE gesture_id = ?
            ORDER BY sample_index ASC;
            """,
            (gesture_id,),
        )
        rows = cursor.fetchall()
        cursor.close()

        samples: List[GestureSample] = []
        for r in rows:
            frame_count = int(r["frame_count"])
            img_arr = decode_landmarks(r["landmarks_image"], frame_count)
            world_arr = decode_landmarks(r["landmarks_world"], frame_count)
            ts_arr = decode_timestamps(r["timestamps_ms"], frame_count)

            samples.append(
                GestureSample(
                    id=r["id"],
                    gesture_id=r["gesture_id"],
                    sample_index=r["sample_index"],
                    frame_count=frame_count,
                    duration_ms=r["duration_ms"],
                    landmarks_image=img_arr,
                    landmarks_world=world_arr,
                    timestamps_ms=ts_arr,
                    frame_aspect_ratio=float(r["frame_aspect_ratio"]),
                    tracker_model_id=r["tracker_model_id"],
                    preprocess_json=r["preprocess_json"],
                    created_at=r["created_at"],
                )
            )

        return samples
