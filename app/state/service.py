"""Transactional state-management service for sync, streams, and reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.enums import OrderStatus, PositionStatus
from app.core.events import EventDispatcher, InternalEvent, InternalEventType
from app.core.logging import get_logger
from app.state.models import Position
from app.state.repository import (
    AccountRepository,
    FillRepository,
    OrderRepository,
    PositionRepository,
    TradeIntentRepository,
)
from app.state.schemas import AccountSnapshot, OrderSnapshot, PositionSnapshot, TradeUpdate


@dataclass(slots=True)
class ReconciliationReport:
    """Result of a reconciliation cycle."""

    missing_orders: list[str] = field(default_factory=list)
    mismatched_positions: list[str] = field(default_factory=list)
    stale_orders: list[str] = field(default_factory=list)


class StateService:
    """Owns transactional state updates and internal event emission."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        dispatcher: EventDispatcher,
    ) -> None:
        self._session_factory = session_factory
        self._dispatcher = dispatcher
        self._logger = get_logger(__name__)

    async def sync_account(self, snapshot: AccountSnapshot) -> None:
        """Upsert the remote account snapshot."""
        async with self._session_factory() as session:
            async with session.begin():
                await AccountRepository(session).upsert_account_snapshot(snapshot)

    async def sync_orders(self, snapshots: list[OrderSnapshot]) -> None:
        """Upsert remote orders idempotently."""
        async with self._session_factory() as session:
            async with session.begin():
                repository = OrderRepository(session)
                for snapshot in snapshots:
                    await repository.upsert_from_snapshot(snapshot)

    async def sync_positions(self, snapshots: list[PositionSnapshot]) -> None:
        """Upsert remote positions idempotently."""
        async with self._session_factory() as session:
            async with session.begin():
                repository = PositionRepository(session)
                for snapshot in snapshots:
                    position = await repository.upsert_from_snapshot(snapshot)
                    await self._emit_position_events(position)

    async def apply_trade_update(self, update: TradeUpdate) -> None:
        """Persist a trade update atomically and emit internal events."""
        self._logger.info(
            "trade_update_received",
            event_type=update.event_type,
            client_order_id=update.order.client_order_id,
            symbol=update.order.symbol,
        )
        async with self._session_factory() as session:
            async with session.begin():
                order_repo = OrderRepository(session)
                fill_repo = FillRepository(session)
                position_repo = PositionRepository(session)
                trade_intent_repo = TradeIntentRepository(session)

                trade_intent = None
                if update.order.idempotency_key is not None:
                    trade_intent = await trade_intent_repo.get_by_intent_key(
                        update.order.idempotency_key
                    )

                order = await order_repo.upsert_from_snapshot(
                    update.order,
                    trade_intent=trade_intent,
                )
                await self._dispatcher.dispatch(
                    InternalEvent(
                        event_type=InternalEventType.ORDER_SUBMITTED,
                        occurred_at=update.event_at or datetime.now(UTC),
                        payload={
                            "client_order_id": order.client_order_id,
                            "symbol": order.symbol,
                            "status": order.status.value,
                        },
                    )
                )

                if update.fill is not None:
                    await fill_repo.upsert_fill(update.fill, order)

                if (
                    update.order.status in {OrderStatus.NEW, OrderStatus.ACCEPTED}
                    and update.fill is None
                ):
                    position = await position_repo.ensure_pending_position(
                        symbol=update.order.symbol,
                        side=update.order.side,
                        occurred_at=update.event_at,
                    )
                elif update.order.status == OrderStatus.CANCELED and update.fill is None:
                    position = await position_repo.ensure_pending_position(
                        symbol=update.order.symbol,
                        side=update.order.side,
                        occurred_at=update.event_at,
                    )
                    await position_repo.transition(
                        position,
                        PositionStatus.CANCELLED,
                        occurred_at=update.event_at,
                    )
                elif update.order.status == OrderStatus.REJECTED and update.fill is None:
                    position = await position_repo.ensure_pending_position(
                        symbol=update.order.symbol,
                        side=update.order.side,
                        occurred_at=update.event_at,
                    )
                    await position_repo.transition(
                        position,
                        PositionStatus.ERROR,
                        occurred_at=update.event_at,
                    )
                else:
                    position_snapshot = PositionSnapshot(
                        broker_position_id=update.raw_payload.get("position_id"),
                        symbol=update.order.symbol,
                        side=update.order.side,
                        qty=update.position_qty or update.order.filled_qty,
                        avg_entry_price=(
                            update.fill.price
                            if update.fill is not None
                            else update.order.filled_avg_price
                        ),
                        market_value=None,
                        unrealized_pl=None,
                        as_of=update.event_at,
                        raw_payload=update.raw_payload,
                    )
                    position = await position_repo.upsert_from_snapshot(position_snapshot)
                await self._emit_order_events(update)
                await self._emit_position_events(position)

    async def reconcile(
        self,
        *,
        remote_account: AccountSnapshot,
        remote_orders: list[OrderSnapshot],
        remote_positions: list[PositionSnapshot],
        now: datetime,
    ) -> ReconciliationReport:
        """Compare broker truth with local state and heal what can be healed safely."""
        report = ReconciliationReport()
        async with self._session_factory() as session:
            async with session.begin():
                account_repo = AccountRepository(session)
                order_repo = OrderRepository(session)
                position_repo = PositionRepository(session)

                account = await account_repo.upsert_account_snapshot(remote_account)
                local_open_orders = {
                    order.client_order_id: order for order in await order_repo.list_open_orders()
                }
                remote_by_client_id = {
                    snapshot.client_order_id: snapshot for snapshot in remote_orders
                }

                for client_order_id, snapshot in remote_by_client_id.items():
                    if client_order_id not in local_open_orders:
                        report.missing_orders.append(client_order_id)
                    await order_repo.upsert_from_snapshot(snapshot, account=account)

                for client_order_id, local_order in local_open_orders.items():
                    remote_snapshot = remote_by_client_id.get(client_order_id)
                    if remote_snapshot is None:
                        report.stale_orders.append(client_order_id)
                        local_order.status = OrderStatus.CANCELED
                        local_order.last_event_at = now

                local_positions = {
                    position.symbol: position for position in await position_repo.list_positions()
                }
                remote_by_symbol = {snapshot.symbol: snapshot for snapshot in remote_positions}

                for symbol, snapshot in remote_by_symbol.items():
                    local_position = local_positions.get(symbol)
                    if local_position is not None and local_position.qty != abs(snapshot.qty):
                        report.mismatched_positions.append(symbol)
                    position = await position_repo.upsert_from_snapshot(snapshot, account=account)
                    await self._emit_position_events(position)

                for symbol, local_position in local_positions.items():
                    if symbol not in remote_by_symbol and local_position.qty > 0:
                        report.mismatched_positions.append(symbol)
                        await position_repo.transition(
                            local_position,
                            PositionStatus.RECONCILE_REQUIRED,
                            occurred_at=now,
                        )

            for symbol in report.mismatched_positions:
                await self._dispatcher.dispatch(
                    InternalEvent(
                        event_type=InternalEventType.RECONCILIATION_MISMATCH,
                        occurred_at=now,
                        payload={"symbol": symbol},
                    )
                )
        return report

    async def _emit_order_events(self, update: TradeUpdate) -> None:
        """Emit order-level internal events."""
        if update.order.status == OrderStatus.FILLED:
            await self._dispatcher.dispatch(
                InternalEvent(
                    event_type=InternalEventType.ORDER_FILLED,
                    occurred_at=update.event_at or datetime.now(UTC),
                    payload={
                        "client_order_id": update.order.client_order_id,
                        "symbol": update.order.symbol,
                    },
                )
            )

    async def _emit_position_events(self, position: Position) -> None:
        """Emit position open/close events."""
        if position.status == PositionStatus.OPEN:
            await self._dispatcher.dispatch(
                InternalEvent(
                    event_type=InternalEventType.POSITION_OPENED,
                    occurred_at=position.opened_at or datetime.now(UTC),
                    payload={"symbol": position.symbol, "qty": str(position.qty)},
                )
            )
        if position.status == PositionStatus.CLOSED:
            await self._dispatcher.dispatch(
                InternalEvent(
                    event_type=InternalEventType.POSITION_CLOSED,
                    occurred_at=position.closed_at or datetime.now(UTC),
                    payload={"symbol": position.symbol},
                )
            )
