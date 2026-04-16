"""Enumerations shared across trading state and services."""

from enum import StrEnum


class OrderStatus(StrEnum):
    """Normalized order lifecycle states."""

    NEW = "new"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    ERROR = "error"


class PositionStatus(StrEnum):
    """Position lifecycle states."""

    IDEA = "idea"
    APPROVED = "approved"
    ORDER_PENDING = "order_pending"
    PARTIALLY_FILLED = "partially_filled"
    OPEN = "open"
    REDUCING = "reducing"
    CLOSED = "closed"
    ARCHIVED = "archived"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    ERROR = "error"
    RECONCILE_REQUIRED = "reconcile_required"


class TradeIntentStatus(StrEnum):
    """Intent states before execution."""

    IDEA = "idea"
    APPROVED = "approved"
    REJECTED = "rejected"
    ORDER_PENDING = "order_pending"
    EXECUTED = "executed"
    CANCELLED = "cancelled"
    ERROR = "error"


class Side(StrEnum):
    """Trading side."""

    BUY = "buy"
    SELL = "sell"
