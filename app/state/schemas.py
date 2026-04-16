"""Normalized state and broker event schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.enums import OrderStatus, Side


def parse_decimal(value: Any, default: str = "0") -> Decimal:
    """Convert mixed broker values into Decimal safely."""
    if value is None or value == "":
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def parse_datetime(value: Any) -> datetime | None:
    """Convert common broker timestamp shapes into aware datetimes."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None
    return None


def infer_side(value: Any, qty: Decimal | None = None) -> Side:
    """Infer a side from broker payload fields."""
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in {"buy", "long"}:
            return Side.BUY
        if lowered in {"sell", "short"}:
            return Side.SELL
    if qty is not None and qty < 0:
        return Side.SELL
    return Side.BUY


def normalize_order_status(event: str) -> OrderStatus:
    """Map Alpaca event names to internal order status values."""
    mapping = {
        "new": OrderStatus.NEW,
        "accepted": OrderStatus.ACCEPTED,
        "pending_new": OrderStatus.NEW,
        "fill": OrderStatus.FILLED,
        "filled": OrderStatus.FILLED,
        "partial_fill": OrderStatus.PARTIALLY_FILLED,
        "canceled": OrderStatus.CANCELED,
        "cancelled": OrderStatus.CANCELED,
        "replaced": OrderStatus.ACCEPTED,
        "rejected": OrderStatus.REJECTED,
        "expired": OrderStatus.EXPIRED,
    }
    return mapping.get(event.lower(), OrderStatus.ERROR)


@dataclass(slots=True)
class AccountSnapshot:
    """Normalized account state."""

    account_id: str
    status: str
    currency: str
    buying_power: Decimal
    equity: Decimal
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OrderSnapshot:
    """Normalized order state mirrored from Alpaca."""

    broker_order_id: str | None
    client_order_id: str
    idempotency_key: str | None
    symbol: str
    side: Side
    status: OrderStatus
    qty: Decimal
    filled_qty: Decimal
    order_type: str
    time_in_force: str
    limit_price: Decimal | None
    stop_price: Decimal | None
    filled_avg_price: Decimal | None
    submitted_at: datetime | None
    event_at: datetime | None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FillSnapshot:
    """Normalized fill event derived from trade updates."""

    broker_fill_id: str | None
    client_order_id: str
    symbol: str
    side: Side
    qty: Decimal
    price: Decimal
    filled_at: datetime | None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PositionSnapshot:
    """Normalized position state mirrored from Alpaca."""

    broker_position_id: str | None
    symbol: str
    side: Side
    qty: Decimal
    avg_entry_price: Decimal | None
    market_value: Decimal | None
    unrealized_pl: Decimal | None
    as_of: datetime | None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TradeUpdate:
    """Normalized trade update event from Alpaca streams."""

    event_type: str
    event_at: datetime | None
    order: OrderSnapshot
    fill: FillSnapshot | None = None
    position_qty: Decimal | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
