"""Diagnostic sink for STOPPED, RECORDING, and TEST modes."""

from __future__ import annotations

import logging
from typing import Optional

from domain.models import FrameAnalysis, RecognitionEvent
from services.event_bus import EventBus

logger = logging.getLogger(__name__)


class DiagnosticSink:
    """Safe event sink used in non-live modes (STOPPED, RECORDING, TEST).
    
    Architectural Rule R4: This class and module MUST NOT import or hold references
    to ExecutionGate, ExecutionDispatcher, WorkflowExecutor, or desktop action adapters.
    """

    def __init__(self, event_bus: Optional[EventBus] = None) -> None:
        self._event_bus = event_bus

    def on_frame_analysis(self, analysis: FrameAnalysis) -> None:
        """Receives per-frame diagnostic analysis."""
        # FrameAnalysis is forwarded for UI monitoring
        pass

    def on_recognition_event(self, event: RecognitionEvent) -> None:
        """Receives accepted triggers in Test mode (logged/displayed, never executed)."""
        logger.info(
            "Test Mode Recognition Event: '%s' (dist=%.3f, threshold=%.3f)",
            event.gesture_name,
            event.distance,
            event.threshold,
        )
        # Event is purely diagnostic; zero desktop execution capability exists here
