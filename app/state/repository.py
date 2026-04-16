"""Persistence helpers and lifecycle enforcement for the trading state store."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import OrderStatus, PositionStatus, Side, TradeIntentStatus
from app.core.logging import get_logger
from app.state.models import Account, Fill, Order, Position, RiskControlState, TradeIntent
from app.state.schemas import AccountSnapshot, FillSnapshot, OrderSnapshot, PositionSnapshot

ALLOWED_POSITION_TRANSITIONS: dict[PositionStatus, set[PositionStatus]] = {
    PositionStatus.IDEA: {
        PositionStatus.APPROVED,
        PositionStatus.ERROR,
        PositionStatus.CANCELLED,
    },
    PositionStatus.APPROVED: {
        PositionStatus.ORDER_PENDING,
        PositionStatus.CANCELLED,
        PositionStatus.ERROR,
    },
    PositionStatus.ORDER_PENDING: {
        PositionStatus.PARTIALLY_FILLED,
        PositionStatus.OPEN,
        PositionStatus.CANCELLED,
        PositionStatus.ERROR,
    },
    PositionStatus.PARTIALLY_FILLED: {
        PositionStatus.OPEN,
        PositionStatus.REDUCING,
        PositionStatus.CLOSED,
        PositionStatus.ERROR,
    },
    PositionStatus.OPEN: {
        PositionStatus.REDUCING,
        PositionStatus.CLOSED,
        PositionStatus.RECONCILE_REQUIRED,
        PositionStatus.ERROR,
    },
    PositionStatus.REDUCING: {
        PositionStatus.OPEN,
        PositionStatus.CLOSED,
        PositionStatus.RECONCILE_REQUIRED,
        PositionStatus.ERROR,
    },
    PositionStatus.CLOSED: {PositionStatus.ARCHIVED, PositionStatus.RECONCILE_REQUIRED},
    PositionStatus.RECONCILE_REQUIRED: {
        PositionStatus.OPEN,
        PositionStatus.REDUCING,
        PositionStatus.CLOSED,
        PositionStatus.ERROR,
    },
    PositionStatus.CANCELLED: set(),
    PositionStatus.ERROR: set(),
    PositionStatus.ARCHIVED: set(),
    PositionStatus.REJECTED: set(),
}


def _is_zero(value: Decimal | None) -> bool:
    return value is None or value == Decimal("0")


class AccountRepository:
    """Store and query account snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_latest(self) -> Account | None:
        """Return the most recently updated account snapshot."""
        result = await self._session.execute(
            select(Account).order_by(desc(Account.updated_at)).limit(1)
        )
        return result.scalar_one_or_none()

    async def upsert_account_snapshot(self, summary: AccountSnapshot) -> Account:
        """Insert or update the latest broker account snapshot."""
        result = await self._session.execute(
            select(Account).where(Account.broker_account_id == summary.account_id)
        )
        account = result.scalar_one_or_none()
        if account is None:
            account = Account(
                broker_account_id=summary.account_id,
                status=summary.status,
                currency=summary.currency,
                buying_power=summary.buying_power,
                equity=summary.equity,
                raw_payload=summary.raw_payload,
            )
            self._session.add(account)
        else:
            account.status = summary.status
            account.currency = summary.currency
            account.buying_power = summary.buying_power
            account.equity = summary.equity
            account.raw_payload = summary.raw_payload
        await self._session.flush()
        return account


class TradeIntentRepository:
    """Manage trade intents and restart-safe idempotency keys."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_intent_key(self, intent_key: str) -> TradeIntent | None:
        """Fetch a trade intent by its deterministic key."""
        result = await self._session.execute(
            select(TradeIntent).where(TradeIntent.intent_key == intent_key)
        )
        return result.scalar_one_or_none()

    async def create_trade_intent(
        self,
        *,
        intent_key: str,
        strategy_id: str,
        strategy_version: str,
        symbol: str,
        side: Side,
        thesis: str | None = None,
        confidence: Decimal | None = None,
        requested_qty: Decimal | None = None,
        metadata: dict[str, object] | None = None,
    ) -> TradeIntent:
        """Create a trade intent if it does not already exist."""
        existing = await self.get_by_intent_key(intent_key)
        if existing is not None:
            return existing

        trade_intent = TradeIntent(
            intent_key=intent_key,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            symbol=symbol,
            side=side,
            thesis=thesis,
            confidence=confidence,
            requested_qty=requested_qty,
            status=TradeIntentStatus.APPROVED,
            metadata_json=metadata or {},
        )
        self._session.add(trade_intent)
        await self._session.flush()
        return trade_intent

    async def reserve_order_submission(self, intent_key: str, idempotency_key: str) -> TradeIntent:
        """Guard against duplicate order submission for the same intent key."""
        trade_intent = await self.get_by_intent_key(intent_key)
        if trade_intent is None:
            raise ValueError(f"Trade intent {intent_key} does not exist.")

        if trade_intent.metadata_json.get("active_idempotency_key") == idempotency_key:
            return trade_intent

        if trade_intent.submitted_order_count > 0:
            raise ValueError(f"Duplicate order submission blocked for trade intent {intent_key}.")

        metadata = dict(trade_intent.metadata_json)
        metadata["active_idempotency_key"] = idempotency_key
        trade_intent.metadata_json = metadata
        trade_intent.submitted_order_count += 1
        trade_intent.status = TradeIntentStatus.ORDER_PENDING
        await self._session.flush()
        return trade_intent


class OrderRepository:
    """Manage order persistence and state transitions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_client_order_id(self, client_order_id: str) -> Order | None:
        """Fetch an order by client order id."""
        result = await self._session.execute(
            select(Order).where(Order.client_order_id == client_order_id)
        )
        return result.scalar_one_or_none()

    async def list_open_orders(self) -> list[Order]:
        """Return currently open local orders."""
        result = await self._session.execute(
            select(Order).where(
                Order.status.in_(
                    [OrderStatus.NEW, OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED]
                )
            )
        )
        return list(result.scalars().all())

    async def list_stale_orders(
        self,
        *,
        cutoff: datetime,
    ) -> list[Order]:
        """Return open orders older than the supplied cutoff."""
        result = await self._session.execute(
            select(Order).where(
                Order.status.in_(
                    [OrderStatus.NEW, OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED]
                ),
                Order.submitted_at.is_not(None),
                Order.submitted_at < cutoff,
            )
        )
        return list(result.scalars().all())

    async def upsert_from_snapshot(
        self,
        snapshot: OrderSnapshot,
        account: Account | None = None,
        trade_intent: TradeIntent | None = None,
    ) -> Order:
        """Insert or update an order from broker state without creating duplicates."""
        order = await self.get_by_client_order_id(snapshot.client_order_id)
        if order is None and snapshot.broker_order_id is not None:
            result = await self._session.execute(
                select(Order).where(Order.broker_order_id == snapshot.broker_order_id)
            )
            order = result.scalar_one_or_none()

        if order is None:
            order = Order(
                broker_order_id=snapshot.broker_order_id,
                client_order_id=snapshot.client_order_id,
                idempotency_key=snapshot.idempotency_key,
                symbol=snapshot.symbol,
                side=snapshot.side,
                status=snapshot.status,
                qty=snapshot.qty,
                filled_qty=snapshot.filled_qty,
                order_type=snapshot.order_type,
                time_in_force=snapshot.time_in_force,
                limit_price=snapshot.limit_price,
                stop_price=snapshot.stop_price,
                filled_avg_price=snapshot.filled_avg_price,
                submitted_at=snapshot.submitted_at,
                last_event_at=snapshot.event_at,
                raw_payload=snapshot.raw_payload,
            )
            self._session.add(order)
        else:
            order.broker_order_id = snapshot.broker_order_id or order.broker_order_id
            order.idempotency_key = snapshot.idempotency_key or order.idempotency_key
            order.symbol = snapshot.symbol
            order.side = snapshot.side
            order.status = snapshot.status
            order.qty = snapshot.qty
            order.filled_qty = snapshot.filled_qty
            order.order_type = snapshot.order_type
            order.time_in_force = snapshot.time_in_force
            order.limit_price = snapshot.limit_price
            order.stop_price = snapshot.stop_price
            order.filled_avg_price = snapshot.filled_avg_price
            order.submitted_at = snapshot.submitted_at
            order.last_event_at = snapshot.event_at
            order.raw_payload = snapshot.raw_payload

        if account is not None:
            order.account = account
        if trade_intent is not None:
            order.trade_intent = trade_intent

        await self._session.flush()
        return order


class FillRepository:
    """Persist fill events idempotently."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_fill(self, snapshot: FillSnapshot, order: Order) -> Fill:
        """Insert or update a fill event for an order."""
        fill: Fill | None = None
        if snapshot.broker_fill_id is not None:
            result = await self._session.execute(
                select(Fill).where(Fill.broker_fill_id == snapshot.broker_fill_id)
            )
            fill = result.scalar_one_or_none()

        if fill is None:
            fill = Fill(
                broker_fill_id=snapshot.broker_fill_id,
                order=order,
                symbol=snapshot.symbol,
                qty=snapshot.qty,
                price=snapshot.price,
                side=snapshot.side,
                filled_at=snapshot.filled_at,
                raw_payload=snapshot.raw_payload,
            )
            self._session.add(fill)
        else:
            fill.qty = snapshot.qty
            fill.price = snapshot.price
            fill.side = snapshot.side
            fill.filled_at = snapshot.filled_at
            fill.raw_payload = snapshot.raw_payload
        await self._session.flush()
        return fill


class PositionRepository:
    """Manage positions and enforce lifecycle transitions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._logger = get_logger(__name__)

    async def get_by_symbol(self, symbol: str) -> Position | None:
        """Fetch a position by symbol."""
        result = await self._session.execute(select(Position).where(Position.symbol == symbol))
        return result.scalar_one_or_none()

    async def list_positions(self) -> list[Position]:
        """Return all local positions."""
        result = await self._session.execute(select(Position))
        return list(result.scalars().all())

    async def list_active_positions(self) -> list[Position]:
        """Return positions that still contribute to current exposure."""
        result = await self._session.execute(
            select(Position).where(
                Position.status.in_(
                    [
                        PositionStatus.ORDER_PENDING,
                        PositionStatus.PARTIALLY_FILLED,
                        PositionStatus.OPEN,
                        PositionStatus.REDUCING,
                        PositionStatus.RECONCILE_REQUIRED,
                    ]
                )
            )
        )
        return list(result.scalars().all())

    async def list_recent_closed_positions(
        self,
        *,
        symbol: str | None = None,
        limit: int = 20,
    ) -> list[Position]:
        """Return the most recent closed positions, optionally filtered by symbol."""
        query = select(Position).where(Position.closed_at.is_not(None))
        if symbol is not None:
            query = query.where(Position.symbol == symbol)
        query = query.order_by(desc(Position.closed_at)).limit(limit)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def ensure_pending_position(
        self,
        *,
        symbol: str,
        side: Side,
        occurred_at: datetime | None,
    ) -> Position:
        """Create or transition a placeholder position into ORDER_PENDING."""
        position = await self.get_by_symbol(symbol)
        if position is None:
            position = Position(
                broker_position_id=symbol,
                symbol=symbol,
                side=side,
                status=PositionStatus.ORDER_PENDING,
                qty=Decimal("0"),
                opened_at=None,
                last_synced_at=occurred_at,
                raw_payload={},
            )
            self._session.add(position)
            await self._session.flush()
            return position

        if position.status == PositionStatus.APPROVED:
            await self.transition(position, PositionStatus.ORDER_PENDING, occurred_at=occurred_at)
        elif position.status == PositionStatus.IDEA:
            await self.transition(position, PositionStatus.APPROVED, occurred_at=occurred_at)
            await self.transition(position, PositionStatus.ORDER_PENDING, occurred_at=occurred_at)
        return position

    async def upsert_from_snapshot(
        self,
        snapshot: PositionSnapshot,
        account: Account | None = None,
    ) -> Position:
        """Insert or update a position from broker state."""
        position = None
        if snapshot.broker_position_id is not None:
            result = await self._session.execute(
                select(Position).where(Position.broker_position_id == snapshot.broker_position_id)
            )
            position = result.scalar_one_or_none()
        if position is None:
            position = await self.get_by_symbol(snapshot.symbol)

        target_status = infer_position_status(snapshot.qty, existing=position)

        if position is None:
            position = Position(
                broker_position_id=snapshot.broker_position_id,
                symbol=snapshot.symbol,
                side=snapshot.side,
                status=target_status,
                qty=abs(snapshot.qty),
                avg_entry_price=snapshot.avg_entry_price,
                market_value=snapshot.market_value,
                unrealized_pl=snapshot.unrealized_pl,
                opened_at=snapshot.as_of if not _is_zero(snapshot.qty) else None,
                closed_at=snapshot.as_of if _is_zero(snapshot.qty) else None,
                last_synced_at=snapshot.as_of,
                raw_payload=snapshot.raw_payload,
            )
            if account is not None:
                position.account = account
            self._session.add(position)
        else:
            if account is not None:
                position.account = account
            position.broker_position_id = snapshot.broker_position_id or position.broker_position_id
            position.symbol = snapshot.symbol
            position.side = snapshot.side
            position.qty = abs(snapshot.qty)
            position.avg_entry_price = snapshot.avg_entry_price
            position.market_value = snapshot.market_value
            position.unrealized_pl = snapshot.unrealized_pl
            position.last_synced_at = snapshot.as_of
            position.raw_payload = snapshot.raw_payload
            await self.transition(position, target_status, occurred_at=snapshot.as_of)

        await self._session.flush()
        return position

    async def transition(
        self,
        position: Position,
        new_status: PositionStatus,
        *,
        occurred_at: datetime | None = None,
    ) -> Position:
        """Enforce position lifecycle transitions."""
        if position.status == new_status:
            return position

        allowed = ALLOWED_POSITION_TRANSITIONS.get(position.status, set())
        if new_status not in allowed:
            raise ValueError(f"Invalid position transition: {position.status} -> {new_status}")

        self._logger.info(
            "position_transition",
            symbol=position.symbol,
            previous_status=position.status.value,
            new_status=new_status.value,
        )
        position.status = new_status
        if (
            new_status in {PositionStatus.OPEN, PositionStatus.REDUCING}
            and position.opened_at is None
        ):
            position.opened_at = occurred_at
        if new_status == PositionStatus.CLOSED:
            position.closed_at = occurred_at
        await self._session.flush()
        return position


def infer_position_status(qty: Decimal, existing: Position | None) -> PositionStatus:
    """Infer the lifecycle status from quantity and current state."""
    absolute_qty = abs(qty)
    if absolute_qty == Decimal("0"):
        return PositionStatus.CLOSED
    if existing is None:
        return PositionStatus.OPEN
    if existing.status in {
        PositionStatus.IDEA,
        PositionStatus.APPROVED,
        PositionStatus.ORDER_PENDING,
    }:
        if existing.qty == Decimal("0") or absolute_qty >= existing.qty:
            return PositionStatus.OPEN
        return PositionStatus.PARTIALLY_FILLED
    if existing.status == PositionStatus.OPEN and absolute_qty < existing.qty:
        return PositionStatus.REDUCING
    if existing.status == PositionStatus.REDUCING and absolute_qty > 0:
        return PositionStatus.OPEN
    return PositionStatus.OPEN


class RiskControlRepository:
    """Manage persistent kill-switch and circuit breaker state."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(self, control_key: str) -> RiskControlState:
        """Return a control state row, creating it when missing."""
        result = await self._session.execute(
            select(RiskControlState).where(RiskControlState.control_key == control_key)
        )
        state = result.scalar_one_or_none()
        if state is None:
            state = RiskControlState(control_key=control_key, is_active=False, metadata_json={})
            self._session.add(state)
            await self._session.flush()
        return state

    async def set_state(
        self,
        control_key: str,
        *,
        is_active: bool,
        reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> RiskControlState:
        """Persist a breaker or kill-switch state."""
        state = await self.get_or_create(control_key)
        state.is_active = is_active
        state.reason = reason
        state.metadata_json = metadata or {}
        await self._session.flush()
        return state

    async def list_states(self) -> list[RiskControlState]:
        """Return all control states."""
        result = await self._session.execute(select(RiskControlState))
        return list(result.scalars().all())
