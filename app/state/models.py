"""SQLAlchemy models for the MVP trading state store."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.enums import OrderStatus, PositionStatus, Side, TradeIntentStatus


class Base(DeclarativeBase):
    """Declarative base for the state models."""


class TimestampedModel:
    """Reusable created/updated columns."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class Account(Base, TimestampedModel):
    """Account snapshots mirrored from Alpaca."""

    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    broker_account_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32))
    currency: Mapped[str] = mapped_column(String(16), default="USD")
    buying_power: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    equity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    orders: Mapped[list[Order]] = relationship(back_populates="account")
    positions: Mapped[list[Position]] = relationship(back_populates="account")


class TradeIntent(Base, TimestampedModel):
    """Broker-agnostic candidate proposal persisted before any order submission."""

    __tablename__ = "trade_intents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    intent_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    strategy_id: Mapped[str] = mapped_column(String(64), index=True)
    strategy_version: Mapped[str] = mapped_column(String(32))
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[Side] = mapped_column(Enum(Side, native_enum=False))
    status: Mapped[TradeIntentStatus] = mapped_column(
        Enum(TradeIntentStatus, native_enum=False),
        default=TradeIntentStatus.IDEA,
        index=True,
    )
    thesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    requested_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    submitted_order_count: Mapped[int] = mapped_column(default=0)

    orders: Mapped[list[Order]] = relationship(back_populates="trade_intent")


class Order(Base, TimestampedModel):
    """Orders mirrored from Alpaca and linked to local trade intents."""

    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    broker_order_id: Mapped[str | None] = mapped_column(
        String(128),
        unique=True,
        nullable=True,
        index=True,
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128),
        unique=True,
        nullable=True,
        index=True,
    )
    client_order_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    trade_intent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trade_intents.id"),
        nullable=True,
    )
    strategy_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[Side] = mapped_column(Enum(Side, native_enum=False))
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus, native_enum=False), index=True)
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    order_type: Mapped[str] = mapped_column(String(32))
    time_in_force: Mapped[str] = mapped_column(String(16))
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    filled_qty: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0)
    filled_avg_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    account: Mapped[Account | None] = relationship(back_populates="orders")
    trade_intent: Mapped[TradeIntent | None] = relationship(back_populates="orders")
    fills: Mapped[list[Fill]] = relationship(back_populates="order")


class Position(Base, TimestampedModel):
    """Current or historical positions tracked locally."""

    __tablename__ = "positions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    broker_position_id: Mapped[str | None] = mapped_column(
        String(128),
        unique=True,
        nullable=True,
        index=True,
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    strategy_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[Side] = mapped_column(Enum(Side, native_enum=False))
    status: Mapped[PositionStatus] = mapped_column(
        Enum(PositionStatus, native_enum=False),
        index=True,
    )
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    avg_entry_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    market_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    unrealized_pl: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    account: Mapped[Account | None] = relationship(back_populates="positions")


class RiskControlState(Base, TimestampedModel):
    """Persistent kill switch and circuit breaker state."""

    __tablename__ = "risk_control_states"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    control_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(default=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Fill(Base, TimestampedModel):
    """Individual fill events associated with an order."""

    __tablename__ = "fills"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    broker_fill_id: Mapped[str | None] = mapped_column(
        String(128),
        unique=True,
        nullable=True,
        index=True,
    )
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    side: Mapped[Side] = mapped_column(Enum(Side, native_enum=False))
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    order: Mapped[Order] = relationship(back_populates="fills")
