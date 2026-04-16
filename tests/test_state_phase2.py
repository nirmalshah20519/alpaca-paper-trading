"""Phase 2 state, idempotency, and reconciliation tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.core.database import build_engine, build_session_factory, create_schema
from app.core.enums import OrderStatus, PositionStatus, Side
from app.core.events import EventDispatcher, InternalEventType
from app.core.idempotency import generate_order_idempotency_key, generate_trade_intent_id
from app.state.models import Position
from app.state.repository import OrderRepository, PositionRepository, TradeIntentRepository
from app.state.schemas import AccountSnapshot, OrderSnapshot, PositionSnapshot
from app.state.service import StateService


@pytest.fixture
async def state_service_fixture():
    """Create an isolated in-memory state service for tests."""
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    await create_schema(engine)
    session_factory = build_session_factory(engine)
    dispatcher = EventDispatcher()
    events = []

    async def capture(event):
        events.append(event)

    for event_type in InternalEventType:
        dispatcher.subscribe(event_type, capture)

    service = StateService(session_factory, dispatcher)
    try:
        yield service, session_factory, events
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reconciliation_marks_missing_stale_and_mismatched_state(
    state_service_fixture,
) -> None:
    service, session_factory, events = state_service_fixture

    async with session_factory() as session:
        async with session.begin():
            order_repo = OrderRepository(session)
            position_repo = PositionRepository(session)
            await order_repo.upsert_from_snapshot(
                OrderSnapshot(
                    broker_order_id="broker-local",
                    client_order_id="local-open-order",
                    idempotency_key="local-open-order",
                    symbol="AAPL",
                    side=Side.BUY,
                    status=OrderStatus.ACCEPTED,
                    qty=Decimal("10"),
                    filled_qty=Decimal("0"),
                    order_type="limit",
                    time_in_force="day",
                    limit_price=Decimal("100"),
                    stop_price=None,
                    filled_avg_price=None,
                    submitted_at=datetime.now(UTC),
                    event_at=datetime.now(UTC),
                    raw_payload={},
                )
            )
            await position_repo.upsert_from_snapshot(
                PositionSnapshot(
                    broker_position_id="AAPL",
                    symbol="AAPL",
                    side=Side.BUY,
                    qty=Decimal("5"),
                    avg_entry_price=Decimal("100"),
                    market_value=Decimal("500"),
                    unrealized_pl=Decimal("0"),
                    as_of=datetime.now(UTC),
                    raw_payload={},
                )
            )

    report = await service.reconcile(
        remote_account=AccountSnapshot(
            account_id="acct-1",
            status="ACTIVE",
            currency="USD",
            buying_power=Decimal("10000"),
            equity=Decimal("10000"),
            raw_payload={},
        ),
        remote_orders=[
            OrderSnapshot(
                broker_order_id="broker-remote",
                client_order_id="remote-open-order",
                idempotency_key="remote-open-order",
                symbol="MSFT",
                side=Side.BUY,
                status=OrderStatus.NEW,
                qty=Decimal("2"),
                filled_qty=Decimal("0"),
                order_type="limit",
                time_in_force="day",
                limit_price=Decimal("200"),
                stop_price=None,
                filled_avg_price=None,
                submitted_at=datetime.now(UTC),
                event_at=datetime.now(UTC),
                raw_payload={},
            )
        ],
        remote_positions=[
            PositionSnapshot(
                broker_position_id="AAPL",
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("10"),
                avg_entry_price=Decimal("100"),
                market_value=Decimal("1000"),
                unrealized_pl=Decimal("5"),
                as_of=datetime.now(UTC),
                raw_payload={},
            )
        ],
        now=datetime.now(UTC),
    )

    assert report.missing_orders == ["remote-open-order"]
    assert report.stale_orders == ["local-open-order"]
    assert report.mismatched_positions == ["AAPL"]

    mismatch_events = [
        event
        for event in events
        if event.event_type == InternalEventType.RECONCILIATION_MISMATCH
    ]
    assert len(mismatch_events) == 1
    assert mismatch_events[0].payload["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_trade_intent_idempotency_blocks_duplicate_submission(state_service_fixture) -> None:
    _, session_factory, _ = state_service_fixture
    intent_key = generate_trade_intent_id(
        strategy_id="mean_reversion_v1",
        symbol="AAPL",
        side=Side.BUY,
        bar_timestamp=datetime(2026, 4, 16, 13, 0, tzinfo=UTC),
        thesis_version="v1",
    )
    first_order_key = generate_order_idempotency_key(intent_key, attempt=1)
    second_order_key = generate_order_idempotency_key(intent_key, attempt=2)

    async with session_factory() as session:
        async with session.begin():
            repository = TradeIntentRepository(session)
            created = await repository.create_trade_intent(
                intent_key=intent_key,
                strategy_id="mean_reversion_v1",
                strategy_version="v1",
                symbol="AAPL",
                side=Side.BUY,
            )
            duplicate_create = await repository.create_trade_intent(
                intent_key=intent_key,
                strategy_id="mean_reversion_v1",
                strategy_version="v1",
                symbol="AAPL",
                side=Side.BUY,
            )
            assert created.id == duplicate_create.id

            reserved = await repository.reserve_order_submission(intent_key, first_order_key)
            assert reserved.submitted_order_count == 1

            same_reservation = await repository.reserve_order_submission(
                intent_key,
                first_order_key,
            )
            assert same_reservation.metadata_json["active_idempotency_key"] == first_order_key

            with pytest.raises(ValueError, match="Duplicate order submission blocked"):
                await repository.reserve_order_submission(intent_key, second_order_key)


@pytest.mark.asyncio
async def test_position_state_transitions_enforce_valid_lifecycle(state_service_fixture) -> None:
    _, session_factory, _ = state_service_fixture

    async with session_factory() as session:
        async with session.begin():
            repository = PositionRepository(session)
            position = Position(
                broker_position_id="AAPL",
                symbol="AAPL",
                side=Side.BUY,
                status=PositionStatus.IDEA,
                qty=Decimal("0"),
                raw_payload={},
            )
            session.add(position)
            await session.flush()

            await repository.transition(
                position,
                PositionStatus.APPROVED,
                occurred_at=datetime.now(UTC),
            )
            await repository.transition(
                position,
                PositionStatus.ORDER_PENDING,
                occurred_at=datetime.now(UTC),
            )
            position.qty = Decimal("10")
            await repository.transition(
                position,
                PositionStatus.OPEN,
                occurred_at=datetime.now(UTC),
            )
            position.qty = Decimal("5")
            await repository.transition(
                position,
                PositionStatus.REDUCING,
                occurred_at=datetime.now(UTC),
            )
            position.qty = Decimal("0")
            await repository.transition(
                position,
                PositionStatus.CLOSED,
                occurred_at=datetime.now(UTC),
            )

            assert position.status == PositionStatus.CLOSED

            with pytest.raises(ValueError, match="Invalid position transition"):
                await repository.transition(
                    position,
                    PositionStatus.APPROVED,
                    occurred_at=datetime.now(UTC),
                )
