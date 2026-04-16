"""Lightweight internal event dispatcher and event models."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class InternalEventType(StrEnum):
    """Internal domain events emitted by stateful services."""

    ORDER_SUBMITTED = "order_submitted"
    ORDER_FILLED = "order_filled"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    RECONCILIATION_MISMATCH = "reconciliation_mismatch"
    ALERT = "alert"


@dataclass(slots=True)
class InternalEvent:
    """Application event payload dispatched to local subscribers."""

    event_type: InternalEventType
    occurred_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)


EventHandler = Callable[[InternalEvent], Awaitable[None]]


class EventDispatcher:
    """Small async pub/sub helper for in-process events."""

    def __init__(self) -> None:
        self._handlers: dict[InternalEventType, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: InternalEventType, handler: EventHandler) -> None:
        """Register a handler for a specific event type."""
        self._handlers[event_type].append(handler)

    async def dispatch(self, event: InternalEvent) -> None:
        """Publish an event to all subscribers."""
        for handler in self._handlers[event.event_type]:
            await handler(event)
