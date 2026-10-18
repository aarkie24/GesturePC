"""MediaPipe Tasks HandLandmarker backend implementation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple
import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import numpy as np

from app.constants import TRACKER_MODEL_ID
from app.paths import get_bundled_model_path
from domain.enums import TrackingStatus
from domain.models import HandObservation, TrackingResult

logger = logging.getLogger(__name__)


class MediaPipeTrackerBackend:
    """Extracts 21 3D hand landmarks per frame using MediaPipe Tasks HandLandmarker."""

    def __init__(
        self,
        model_path: Optional[Path] = None,
        num_hands: int = 1,
        min_detection_confidence: float = 0.6,
        min_presence_confidence: float = 0.6,
        min_tracking_confidence: float = 0.6,
    ) -> None:
        if model_path is None:
            model_path = get_bundled_model_path()
        if not model_path.exists():
            raise FileNotFoundError(f"MediaPipe hand landmarker task model not found at {model_path}")

        self._model_path = model_path
        self._prev_ts_ms = -1

        base_options = python.BaseOptions(model_asset_path=str(model_path))
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_hands=num_hands,
            min_hand_detection_confidence=min_detection_confidence,
            min_hand_presence_confidence=min_presence_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        logger.info("MediaPipe HandLandmarker initialized from %s", model_path)

    def process_frame(
        self,
        frame_bgr: np.ndarray,
        timestamp_ms: int,
        frame_id: int = 0,
        capture_ts_ns: int = 0,
    ) -> TrackingResult:
        """Processes a single BGR video frame and returns 3D landmarks."""
        h, w = frame_bgr.shape[:2]
        frame_size = (w, h)

        # Enforce strictly increasing millisecond timestamps required by MediaPipe VIDEO mode
        safe_ts_ms = max(self._prev_ts_ms + 1, timestamp_ms)
        self._prev_ts_ms = safe_ts_ms

        rgb_frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

        try:
            result = self._landmarker.detect_for_video(mp_image, safe_ts_ms)
        except Exception as exc:
            logger.error("MediaPipe detection error on frame %d: %s", frame_id, exc)
            return TrackingResult(
                frame_id=frame_id,
                capture_ts_ns=capture_ts_ns,
                frame_size=frame_size,
                status=TrackingStatus.TRACKER_ERROR,
                hands=(),
            )

        if not result.hand_landmarks:
            return TrackingResult(
                frame_id=frame_id,
                capture_ts_ns=capture_ts_ns,
                frame_size=frame_size,
                status=TrackingStatus.NO_HAND,
                hands=(),
            )

        observations = []
        for i, landmarks in enumerate(result.hand_landmarks):
            # Handedness category name & score
            handedness = result.handedness[i][0] if i < len(result.handedness) else None
            label = handedness.category_name if handedness else "Right"
            score = float(handedness.score) if handedness else 1.0

            # Image-relative normalized landmarks (21, 3)
            img_lm = np.array([[lm.x, lm.y, lm.z] for lm in landmarks], dtype=np.float32)

            # World metric landmarks (21, 3)
            if i < len(result.hand_world_landmarks):
                world_lm = np.array(
                    [[wlm.x, wlm.y, wlm.z] for wlm in result.hand_world_landmarks[i]],
                    dtype=np.float32,
                )
            else:
                world_lm = np.copy(img_lm)

            observations.append(
                HandObservation(
                    label=label,
                    label_score=score,
                    presence_score=score,
                    landmarks_image=img_lm,
                    landmarks_world=world_lm,
                )
            )

        return TrackingResult(
            frame_id=frame_id,
            capture_ts_ns=capture_ts_ns,
            frame_size=frame_size,
            status=TrackingStatus.OK,
            hands=tuple(observations),
        )

    def close(self) -> None:
        """Closes the underlying HandLandmarker instance."""
        if hasattr(self, "_landmarker") and self._landmarker is not None:
            try:
                self._landmarker.close()
            except Exception as exc:
                logger.warning("Error closing HandLandmarker: %s", exc)
            finally:
                self._landmarker = None
