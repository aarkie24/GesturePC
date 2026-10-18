"""QtBridge: Converts background domain events into queued PySide6 signals."""

from __future__ import annotations

from typing import Any, Optional
from PySide6.QtCore import QObject, Signal

from domain.events import (
    DomainEvent,
    PipelineErrorOccurred,
    RuntimeStatusChanged,
)
from services.event_bus import EventBus


class QtBridge(QObject):
    """Bridges threaded domain events into Qt's event loop via queued signal connections."""

    mode_changed = Signal(str, str)  # (mode, reason)
    pipeline_error = Signal(str, str)  # (code, message)
    frame_ready = Signal(object, object)  # (FramePacket, Optional[TrackingResult])
    frame_analysis_ready = Signal(object)  # (FrameAnalysis)
    trigger_recognized = Signal(object)  # (RecognitionEvent)

    def __init__(self, event_bus: EventBus) -> None:
        super().__init__()
        self._event_bus = event_bus
        self._event_bus.subscribe_all(self._handle_domain_event)

    def _handle_domain_event(self, event: DomainEvent) -> None:
        if isinstance(event, RuntimeStatusChanged):
            self.mode_changed.emit(event.mode.value, event.reason)
        elif isinstance(event, PipelineErrorOccurred):
            self.pipeline_error.emit(event.code.value, event.message)

    def emit_frame(self, frame_packet: Any, tracking_result: Optional[Any] = None) -> None:
        """Called by recognition or capture worker to post new frame to UI."""
        self.frame_ready.emit(frame_packet, tracking_result)

    def emit_frame_analysis(self, analysis: Any) -> None:
        """Called by recognition pipeline to emit per-frame diagnostics."""
        self.frame_analysis_ready.emit(analysis)

    def emit_trigger_recognized(self, event: Any) -> None:
        """Called when an accepted trigger event is produced."""
        self.trigger_recognized.emit(event)
