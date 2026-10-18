"""Thread-safe in-memory domain event bus."""

from __future__ import annotations

from collections import defaultdict
import logging
import threading
from typing import Any, Callable, DefaultDict, List, Type, TypeVar

from domain.events import DomainEvent

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=DomainEvent)
EventHandler = Callable[[Any], None]


class EventBus:
    """Synchronous, thread-safe in-memory event bus."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscribers: DefaultDict[Type[DomainEvent], List[EventHandler]] = defaultdict(list)
        self._global_subscribers: List[EventHandler] = []

    def subscribe(self, event_type: Type[T], handler: Callable[[T], None]) -> None:
        """Subscribes a callable handler to a specific domain event type."""
        with self._lock:
            if handler not in self._subscribers[event_type]:
                self._subscribers[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribes a callable handler to all domain events."""
        with self._lock:
            if handler not in self._global_subscribers:
                self._global_subscribers.append(handler)

    def unsubscribe(self, event_type: Type[T], handler: Callable[[T], None]) -> None:
        """Unsubscribes a handler from a specific event type."""
        with self._lock:
            if handler in self._subscribers[event_type]:
                self._subscribers[event_type].remove(handler)

    def unsubscribe_all(self, handler: EventHandler) -> None:
        """Unsubscribes a global handler."""
        with self._lock:
            if handler in self._global_subscribers:
                self._global_subscribers.remove(handler)

    def publish(self, event: DomainEvent) -> None:
        """Publishes an event to all registered matching and global subscribers."""
        with self._lock:
            direct_handlers = list(self._subscribers.get(type(event), []))
            global_handlers = list(self._global_subscribers)

        for handler in direct_handlers:
            try:
                handler(event)
            except Exception as exc:
                logger.exception("Error in event handler %r for %s: %s", handler, type(event).__name__, exc)

        for handler in global_handlers:
            try:
                handler(event)
            except Exception as exc:
                logger.exception("Error in global event handler %r for %s: %s", handler, type(event).__name__, exc)
