"""Camera feed preview widget with 21-landmark skeleton rendering."""

from __future__ import annotations

from typing import Optional, Tuple
from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget
import numpy as np

from camera.frame_types import FramePacket
from domain.models import TrackingResult

# Standard MediaPipe Hand Landmark Connections (21 points)
HAND_CONNECTIONS = (
    # Palm
    (0, 1), (1, 2), (2, 3), (3, 4),      # Thumb
    (0, 5), (5, 6), (6, 7), (7, 8),      # Index
    (5, 9), (9, 10), (10, 11), (11, 12),  # Middle
    (9, 13), (13, 14), (14, 15), (15, 16),# Ring
    (13, 17), (17, 18), (18, 19), (19, 20),# Pinky
    (0, 17),                              # Palm Base
)


class CameraView(QWidget):
    """Renders video frames and overlays hand tracking landmarks."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(480, 360)
        self.setStyleSheet("background-color: #121212; border-radius: 8px;")

        self._current_frame: Optional[QImage] = None
        self._tracking_result: Optional[TrackingResult] = None

    def update_frame(self, packet: FramePacket, tracking_result: Optional[TrackingResult] = None) -> None:
        """Updates display frame and tracking landmarks."""
        h, w = packet.frame_bgr.shape[:2]
        # Convert BGR NumPy buffer to QImage
        rgb = packet.frame_bgr
        bytes_per_line = 3 * w
        qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_BGR888).copy()

        self._current_frame = qimg
        self._tracking_result = tracking_result
        self.update()

    def clear(self) -> None:
        """Clears the video display."""
        self._current_frame = None
        self._tracking_result = None
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        if self._current_frame is None:
            painter.fillRect(0, 0, w, h, QColor("#1a1a1a"))
            painter.setPen(QColor("#666666"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Camera Feed Inactive")
            return

        # Scale frame to preserve aspect ratio
        scaled = self._current_frame.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        offset_x = (w - scaled.width()) // 2
        offset_y = (h - scaled.height()) // 2
        painter.drawImage(offset_x, offset_y, scaled)

        # Draw landmark overlay if available
        if self._tracking_result and self._tracking_result.hands:
            scale_x = float(scaled.width())
            scale_y = float(scaled.height())

            pen_line = QPen(QColor("#00e676"), 2)  # Vibrant green
            pen_joint = QPen(QColor("#ff1744"), 4) # Vibrant red point

            for hand in self._tracking_result.hands:
                lms = hand.landmarks_image  # (21, 3) normalized x, y

                # Draw skeleton connections
                painter.setPen(pen_line)
                for start_idx, end_idx in HAND_CONNECTIONS:
                    pt1 = QPointF(
                        offset_x + lms[start_idx, 0] * scale_x,
                        offset_y + lms[start_idx, 1] * scale_y,
                    )
                    pt2 = QPointF(
                        offset_x + lms[end_idx, 0] * scale_x,
                        offset_y + lms[end_idx, 1] * scale_y,
                    )
                    painter.drawLine(pt1, pt2)

                # Draw joint points
                painter.setPen(pen_joint)
                for i in range(21):
                    x = offset_x + lms[i, 0] * scale_x
                    y = offset_y + lms[i, 1] * scale_y
                    painter.drawPoint(QPointF(x, y))
