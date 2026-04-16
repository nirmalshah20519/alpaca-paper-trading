"""Phase 3 proposal approval, breakers, and portfolio allocation tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.database import build_engine, build_session_factory, create_schema
from app.core.enums import OrderStatus, PositionStatus, Side
from app.core.trading import TradeProposal
from app.risk.service import ProposalEvaluationService
from app.state.models import Fill, Order, Position
from app.state.repository import AccountRepository
from app.state.schemas import AccountSnapshot


@pytest.fixture
async def proposal_service_fixture():
    """Create an isolated proposal evaluation service."""
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    await create_schema(engine)
    session_factory = build_session_factory(engine)
    settings = Settings(enable_startup_broker_validation=False, enable_stream_worker=False)
    service = ProposalEvaluationService(settings, session_factory)
    try:
        yield service, session_factory, settings
    finally:
        await engine.dispose()


def make_proposal(**overrides: object) -> TradeProposal:
    """Build a default test proposal."""
    now = datetime.now(UTC)
    payload = {
        "proposal_id": "proposal-1",
        "strategy_id": "mean_reversion_v1",
        "strategy_version": "v1",
        "symbol": "AAPL",
        "side": Side.BUY,
        "entry_price": Decimal("100"),
        "stop_price": Decimal("98"),
        "take_profit_price": Decimal("104"),
        "requested_qty": Decimal("10"),
        "sector": "technology",
        "min_hold_minutes": 30,
        "generated_at": now,
        "bar_timestamp": now,
    }
    payload.update(overrides)
    return TradeProposal(**payload)


async def seed_account(
    session_factory,
    *,
    equity: str = "10000",
    buying_power: str = "10000",
) -> None:
    """Persist the latest account snapshot."""
    async with session_factory() as session:
        async with session.begin():
            await AccountRepository(session).upsert_account_snapshot(
                AccountSnapshot(
                    account_id="acct-1",
                    status="ACTIVE",
                    currency="USD",
                    buying_power=Decimal(buying_power),
                    equity=Decimal(equity),
                    raw_payload={},
                )
            )


@pytest.mark.asyncio
async def test_proposal_approval_adjusts_size_for_symbol_budget(proposal_service_fixture) -> None:
    service, session_factory, _ = proposal_service_fixture
    await seed_account(session_factory)

    decision = await service.evaluate_proposal(
        make_proposal(requested_qty=Decimal("50"))
    )

    assert decision.approved is True
    assert decision.approved_qty == Decimal("20")
    assert "quantity_adjusted_before_risk_validation" in decision.warnings


@pytest.mark.asyncio
async def test_kill_switch_blocks_all_approvals(proposal_service_fixture) -> None:
    service, session_factory, _ = proposal_service_fixture
    await seed_account(session_factory)
    await service.set_kill_switch(is_active=True, reason="manual_test")

    decision = await service.evaluate_proposal(make_proposal())

    assert decision.approved is False
    assert "breaker_active:manual_kill_switch" in decision.rejection_reasons


@pytest.mark.asyncio
async def test_daily_loss_breaker_blocks_approvals(proposal_service_fixture) -> None:
    service, session_factory, _ = proposal_service_fixture
    await seed_account(session_factory, equity="10000", buying_power="10000")
    await service.list_breakers()
    await seed_account(session_factory, equity="9600", buying_power="9600")

    decision = await service.evaluate_proposal(make_proposal())

    assert decision.approved is False
    assert "breaker_active:daily_loss_breaker" in decision.rejection_reasons


@pytest.mark.asyncio
async def test_recent_exit_cooldown_blocks_reopen(proposal_service_fixture) -> None:
    service, session_factory, _ = proposal_service_fixture
    await seed_account(session_factory)

    async with session_factory() as session:
        async with session.begin():
            session.add(
                Position(
                    broker_position_id="AAPL-closed",
                    symbol="AAPL",
                    side=Side.BUY,
                    status=PositionStatus.CLOSED,
                    qty=Decimal("0"),
                    avg_entry_price=Decimal("100"),
                    opened_at=datetime.now(UTC) - timedelta(hours=2),
                    closed_at=datetime.now(UTC) - timedelta(minutes=5),
                    raw_payload={},
                )
            )

    decision = await service.evaluate_proposal(make_proposal())

    assert decision.approved is False
    assert "cooldown_after_exit_active" in decision.rejection_reasons


@pytest.mark.asyncio
async def test_minimum_hold_time_blocks_immediate_side_flip(proposal_service_fixture) -> None:
    service, session_factory, _ = proposal_service_fixture
    await seed_account(session_factory)

    async with session_factory() as session:
        async with session.begin():
            session.add(
                Position(
                    broker_position_id="AAPL-open",
                    symbol="AAPL",
                    side=Side.BUY,
                    status=PositionStatus.OPEN,
                    qty=Decimal("10"),
                    avg_entry_price=Decimal("100"),
                    market_value=Decimal("1000"),
                    opened_at=datetime.now(UTC) - timedelta(minutes=10),
                    raw_payload={"min_hold_minutes": 60},
                )
            )

    decision = await service.evaluate_proposal(
        make_proposal(
            proposal_id="proposal-2",
            side=Side.SELL,
            stop_price=Decimal("102"),
            take_profit_price=Decimal("95"),
        )
    )

    assert decision.approved is False
    assert "side_flip_cooldown_active" in decision.rejection_reasons
    assert "minimum_hold_time_active" in decision.rejection_reasons


@pytest.mark.asyncio
async def test_daily_turnover_limit_rejects_new_proposal(proposal_service_fixture) -> None:
    service, session_factory, _ = proposal_service_fixture
    await seed_account(session_factory)

    async with session_factory() as session:
        async with session.begin():
            order = Order(
                id=uuid4(),
                broker_order_id="broker-order-1",
                client_order_id="client-order-1",
                symbol="AAPL",
                side=Side.BUY,
                status=OrderStatus.FILLED,
                qty=Decimal("190"),
                order_type="market",
                time_in_force="day",
                raw_payload={},
            )
            session.add(order)
            await session.flush()
            session.add(
                Fill(
                    broker_fill_id="fill-1",
                    order_id=order.id,
                    symbol="AAPL",
                    qty=Decimal("190"),
                    price=Decimal("100"),
                    side=Side.BUY,
                    filled_at=datetime.now(UTC),
                    raw_payload={},
                )
            )

    decision = await service.evaluate_proposal(make_proposal(requested_qty=Decimal("100")))

    assert decision.approved is False
    assert "max_daily_turnover_exceeded" in decision.rejection_reasons
