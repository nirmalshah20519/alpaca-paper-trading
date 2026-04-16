"""Trade-update stream skeleton for later event-driven order handling."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.broker.alpaca_client import AlpacaClients
from app.core.enums import Side
from app.core.logging import get_logger
from app.state.schemas import (
    FillSnapshot,
    OrderSnapshot,
    TradeUpdate,
    infer_side,
    normalize_order_status,
    parse_datetime,
    parse_decimal,
)

TradeUpdateHandler = Callable[[TradeUpdate], Awaitable[None]]


class AlpacaStreamAdapter:
    """Manage Alpaca trade update subscriptions behind an internal interface."""

    def __init__(self, clients: AlpacaClients) -> None:
        self._clients = clients
        self._logger = get_logger(__name__)
        self._handlers: list[TradeUpdateHandler] = []
        self._running = False
        self._task: asyncio.Task[None] | None = None

    def subscribe_trade_updates(self, handler: TradeUpdateHandler) -> None:
        """Register an internal handler for trade update events."""
        self._handlers.append(handler)

    async def start_in_background(self) -> None:
        """Start the reconnecting stream loop in the background."""
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self.start())

    async def start(self) -> None:
        """Start the Alpaca trade update stream with reconnects and backoff."""
        self._running = True
        backoff_seconds = 1.0
        while self._running:
            try:
                async def _dispatch(data: Any) -> None:
                    update = self._normalize_trade_update(data)
                    for handler in self._handlers:
                        await handler(update)

                self._clients.stream.subscribe_trade_updates(_dispatch)
                self._logger.info("trade_update_stream_starting")
                await asyncio.to_thread(self._clients.stream.run)
                backoff_seconds = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - depends on network/runtime
                self._logger.warning(
                    "trade_update_stream_error",
                    error=str(exc),
                    retry_in_seconds=backoff_seconds,
                )
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 30.0)

    async def stop(self) -> None:
        """Stop the Alpaca stream client."""
        self._running = False
        self._logger.info("trade_update_stream_stopping")
        await self._clients.stream.stop_ws()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def _normalize_trade_update(self, payload: Any) -> TradeUpdate:
        """Convert Alpaca trade update payloads into a normalized internal model."""
        raw = self._to_mapping(payload)
        order_payload = self._to_mapping(raw.get("order", {}))
        event_type = str(raw.get("event", "unknown")).lower()
        side = infer_side(order_payload.get("side"))
        event_at = parse_datetime(raw.get("timestamp") or raw.get("at")) or datetime.now(UTC)

        order_snapshot = OrderSnapshot(
            broker_order_id=self._coerce_string(order_payload.get("id")),
            client_order_id=self._coerce_string(order_payload.get("client_order_id")) or "",
            idempotency_key=self._coerce_string(order_payload.get("client_order_id")),
            symbol=self._coerce_string(order_payload.get("symbol")) or "",
            side=side,
            status=normalize_order_status(event_type),
            qty=parse_decimal(order_payload.get("qty")),
            filled_qty=parse_decimal(
                raw.get("qty")
                or raw.get("cum_qty")
                or order_payload.get("filled_qty")
                or order_payload.get("filled_quantity")
            ),
            order_type=(
                self._coerce_string(order_payload.get("order_type") or order_payload.get("type"))
                or "limit"
            ),
            time_in_force=self._coerce_string(order_payload.get("time_in_force")) or "day",
            limit_price=self._optional_decimal(order_payload.get("limit_price")),
            stop_price=self._optional_decimal(order_payload.get("stop_price")),
            filled_avg_price=self._optional_decimal(
                order_payload.get("filled_avg_price") or raw.get("price")
            ),
            submitted_at=parse_datetime(order_payload.get("submitted_at")),
            event_at=event_at,
            raw_payload=order_payload,
        )

        fill = self._build_fill_snapshot(
            raw,
            side,
            event_at,
            order_snapshot.client_order_id,
            order_snapshot.symbol,
        )
        position_qty = self._derive_position_qty(raw, side)

        return TradeUpdate(
            event_type=event_type,
            event_at=event_at,
            order=order_snapshot,
            fill=fill,
            position_qty=position_qty,
            raw_payload=raw,
        )

    def _build_fill_snapshot(
        self,
        payload: dict[str, Any],
        side: Side,
        event_at: datetime,
        client_order_id: str,
        symbol: str,
    ) -> FillSnapshot | None:
        """Create a fill snapshot for fill-related events."""
        qty = parse_decimal(payload.get("qty"))
        price = self._optional_decimal(payload.get("price"))
        if qty == Decimal("0") or price is None:
            return None
        return FillSnapshot(
            broker_fill_id=self._coerce_string(payload.get("execution_id")),
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            filled_at=event_at,
            raw_payload=payload,
        )

    def _derive_position_qty(self, payload: dict[str, Any], side: Side) -> Decimal | None:
        """Infer current position quantity when Alpaca includes it in the event."""
        if payload.get("position_qty") is None:
            return None
        qty = parse_decimal(payload.get("position_qty"))
        return qty if side == Side.BUY else qty.copy_negate()

    @staticmethod
    def _to_mapping(payload: Any) -> dict[str, Any]:
        """Convert SDK event objects into dictionaries."""
        if isinstance(payload, dict):
            return payload
        if hasattr(payload, "model_dump"):
            return payload.model_dump()
        if hasattr(payload, "__dict__"):
            return dict(payload.__dict__)
        raise TypeError(f"Unsupported Alpaca payload type: {type(payload)!r}")

    @staticmethod
    def _coerce_string(value: Any) -> str | None:
        """Convert values to strings when present."""
        if value is None:
            return None
        return str(value)

    @staticmethod
    def _optional_decimal(value: Any) -> Decimal | None:
        """Convert optional values to Decimal."""
        if value is None or value == "":
            return None
        return parse_decimal(value)
