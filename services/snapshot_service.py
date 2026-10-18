"""Snapshot compilation and thread-safe atomic swap service."""

from __future__ import annotations

import logging
import threading
from typing import Optional

from domain.events import SnapshotRebuilt
from domain.models import SnapshotReport, TemplateSnapshot
from gestures.template_loader import TemplateLoader
from services.event_bus import EventBus

logger = logging.getLogger(__name__)


class SnapshotHolder:
    """Thread-safe holder providing atomic reference swap for compiled snapshots."""

    def __init__(self, initial_template_snapshot: Optional[TemplateSnapshot] = None) -> None:
        self._lock = threading.RLock()
        self._template_snapshot: TemplateSnapshot = (
            initial_template_snapshot
            or TemplateSnapshot(
                revision=0,
                templates=(),
                revision_map={},
                timestamp_utc="",
                report=SnapshotReport(),
            )
        )

    def get_template_snapshot(self) -> TemplateSnapshot:
        """Returns the current immutable TemplateSnapshot."""
        with self._lock:
            return self._template_snapshot

    def set_template_snapshot(self, snapshot: TemplateSnapshot) -> None:
        """Atomically swaps the current TemplateSnapshot."""
        with self._lock:
            self._template_snapshot = snapshot


class SnapshotService:
    """Compiles and publishes snapshots with debouncing and thread safety (Section 3.4)."""

    def __init__(
        self,
        template_loader: TemplateLoader,
        event_bus: EventBus,
        holder: Optional[SnapshotHolder] = None,
        debounce_ms: int = 100,
    ) -> None:
        self._template_loader = template_loader
        self._event_bus = event_bus
        self._holder = holder or SnapshotHolder()
        self._debounce_ms = debounce_ms

        self._lock = threading.Lock()
        self._template_revision = 0
        self._debounce_timer: Optional[threading.Timer] = None

    @property
    def holder(self) -> SnapshotHolder:
        return self._holder

    def get_template_snapshot(self) -> TemplateSnapshot:
        """Gets the active immutable TemplateSnapshot."""
        return self._holder.get_template_snapshot()

    def rebuild_now(self) -> TemplateSnapshot:
        """Synchronously rebuilds and publishes the template snapshot."""
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None

            self._template_revision += 1
            current_rev = self._template_revision

        new_snapshot = self._template_loader.load_snapshot(revision=current_rev)
        self._holder.set_template_snapshot(new_snapshot)

        logger.info(
            "Compiled TemplateSnapshot rev=%d with %d templates, excluded=%d",
            new_snapshot.revision,
            len(new_snapshot.templates),
            len(new_snapshot.report.excluded_gestures),
        )

        self._event_bus.publish(
            SnapshotRebuilt(
                template_revision=new_snapshot.revision,
                workflow_revision=0,
                report=new_snapshot.report,
            )
        )
        return new_snapshot

    def request_rebuild(self) -> None:
        """Requests a debounced rebuild in the background (default 100 ms)."""
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()

            delay_s = self._debounce_ms / 1000.0
            self._debounce_timer = threading.Timer(delay_s, self._on_debounce_timer)
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _on_debounce_timer(self) -> None:
        try:
            self.rebuild_now()
        except Exception as exc:
            logger.exception("Error during debounced snapshot rebuild: %s", exc)
