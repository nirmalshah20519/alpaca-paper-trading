"""Trading-side Alpaca wrapper used by the execution layer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from alpaca.trading.requests import GetOrdersRequest, ReplaceOrderRequest

from app.broker.alpaca_client import AlpacaClients, run_with_retry
from app.state.schemas import (
    AccountSnapshot,
    OrderSnapshot,
    PositionSnapshot,
    infer_side,
    normalize_order_status,
    parse_datetime,
    parse_decimal,
)


@dataclass(slots=True)
class AccountSummary:
    """Normalized subset of account fields used by the MVP."""

    account_id: str
    status: str
    currency: str
    buying_power: str
    equity: str

    def to_snapshot(self) -> AccountSnapshot:
        """Convert the account summary to a normalized snapshot."""
        return AccountSnapshot(
            account_id=self.account_id,
            status=self.status,
            currency=self.currency,
            buying_power=Decimal(self.buying_power),
            equity=Decimal(self.equity),
            raw_payload={
                "account_id": self.account_id,
                "status": self.status,
                "currency": self.currency,
                "buying_power": self.buying_power,
                "equity": self.equity,
            },
        )


class AlpacaTradingAdapter:
    """Paper-only adapter around the Alpaca Trading API."""

    def __init__(self, clients: AlpacaClients) -> None:
        self._clients = clients

    async def get_account_summary(self) -> AccountSummary:
        """Fetch the remote account state."""
        account = await run_with_retry(self._clients.trading.get_account)
        return AccountSummary(
            account_id=str(account.id),
            status=str(account.status),
            currency=str(account.currency),
            buying_power=str(account.buying_power),
            equity=str(account.equity),
        )

    async def get_account_snapshot(self) -> AccountSnapshot:
        """Return a normalized account snapshot."""
        return (await self.get_account_summary()).to_snapshot()

    async def list_orders(self, status: str = "all") -> list[dict[str, Any]]:
        """Return raw order payloads for reconciliation."""
        request = GetOrdersRequest(status=status)
        orders = await run_with_retry(self._clients.trading.get_orders, filter=request)
        return [self._to_mapping(order) for order in orders]

    async def list_order_snapshots(self, status: str = "open") -> list[OrderSnapshot]:
        """Return normalized order snapshots."""
        return [self._normalize_order(order) for order in await self.list_orders(status=status)]

    async def get_all_positions(self) -> list[dict[str, Any]]:
        """Return raw position payloads for reconciliation."""
        positions = await run_with_retry(self._clients.trading.get_all_positions)
        return [self._to_mapping(position) for position in positions]

    async def get_position_snapshots(self) -> list[PositionSnapshot]:
        """Return normalized position snapshots."""
        return [self._normalize_position(position) for position in await self.get_all_positions()]

    async def submit_order(self, order_request: Any) -> OrderSnapshot:
        """Submit a paper order and normalize the result."""
        order = await run_with_retry(self._clients.trading.submit_order, order_request)
        return self._normalize_order(self._to_mapping(order))

    async def get_order_by_client_order_id(self, client_order_id: str) -> OrderSnapshot:
        """Fetch a normalized order snapshot by client order id."""
        order = await run_with_retry(
            self._clients.trading.get_order_by_client_id,
            client_order_id,
        )
        return self._normalize_order(self._to_mapping(order))

    async def cancel_order(self, order_id: str) -> None:
        """Cancel a paper order by broker order id."""
        await run_with_retry(self._clients.trading.cancel_order_by_id, order_id)

    async def replace_order(
        self,
        order_id: str,
        *,
        limit_price: Decimal | None = None,
        stop_price: Decimal | None = None,
    ) -> OrderSnapshot:
        """Replace a paper order and return the updated snapshot."""
        request = ReplaceOrderRequest(
            limit_price=float(limit_price) if limit_price is not None else None,
            stop_price=float(stop_price) if stop_price is not None else None,
        )
        order = await run_with_retry(
            self._clients.trading.replace_order_by_id,
            order_id,
            request,
        )
        return self._normalize_order(self._to_mapping(order))

    def _normalize_order(self, payload: dict[str, Any]) -> OrderSnapshot:
        """Convert Alpaca order payloads to normalized snapshots."""
        filled_qty = parse_decimal(
            payload.get("filled_qty") or payload.get("filled_quantity") or payload.get("qty_filled")
        )
        return OrderSnapshot(
            broker_order_id=self._coerce_string(payload.get("id")),
            client_order_id=self._coerce_string(payload.get("client_order_id")) or "",
            idempotency_key=self._coerce_string(payload.get("client_order_id")),
            symbol=self._coerce_string(payload.get("symbol")) or "",
            side=infer_side(payload.get("side")),
            status=normalize_order_status(str(payload.get("status", "accepted"))),
            qty=parse_decimal(payload.get("qty")),
            filled_qty=filled_qty,
            order_type=(
                self._coerce_string(payload.get("order_type") or payload.get("type")) or "limit"
            ),
            time_in_force=self._coerce_string(payload.get("time_in_force")) or "day",
            limit_price=self._optional_decimal(payload.get("limit_price")),
            stop_price=self._optional_decimal(payload.get("stop_price")),
            filled_avg_price=self._optional_decimal(payload.get("filled_avg_price")),
            submitted_at=parse_datetime(payload.get("submitted_at")),
            event_at=parse_datetime(payload.get("updated_at") or payload.get("submitted_at")),
            raw_payload=payload,
        )

    def _normalize_position(self, payload: dict[str, Any]) -> PositionSnapshot:
        """Convert Alpaca position payloads to normalized snapshots."""
        qty = parse_decimal(payload.get("qty"))
        side = infer_side(payload.get("side"), qty=qty if qty != 0 else None)
        return PositionSnapshot(
            broker_position_id=(
                self._coerce_string(payload.get("asset_id"))
                or self._coerce_string(payload.get("symbol"))
            ),
            symbol=self._coerce_string(payload.get("symbol")) or "",
            side=side,
            qty=qty,
            avg_entry_price=self._optional_decimal(payload.get("avg_entry_price")),
            market_value=self._optional_decimal(payload.get("market_value")),
            unrealized_pl=self._optional_decimal(payload.get("unrealized_pl")),
            as_of=parse_datetime(payload.get("updated_at")) or datetime.now(UTC),
            raw_payload=payload,
        )

    @staticmethod
    def _to_mapping(payload: Any) -> dict[str, Any]:
        """Convert SDK objects into dictionaries."""
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
