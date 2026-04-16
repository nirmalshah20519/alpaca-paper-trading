"""Phase 4 and 5 strategy and execution tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.config import Settings
from app.core.database import build_engine, build_session_factory, create_schema
from app.core.enums import OrderStatus, Side
from app.core.events import EventDispatcher
from app.core.trading import OhlcvBar, StrategyMarketContext, SymbolMarketContext
from app.execution.engine import ExecutionEngine
from app.execution.order_factory import OrderFactory
from app.execution.router import ExecutionRouter
from app.market_data.indicators import ema, rsi, volatility_pct
from app.risk.service import ProposalEvaluationService
from app.state.repository import AccountRepository, OrderRepository
from app.state.schemas import AccountSnapshot, OrderSnapshot
from app.strategies.mean_reversion import MeanReversionStrategy
from app.strategies.registry import CandidateRanker, StrategyRegistry
from app.strategies.trend_following import TrendFollowingStrategy


class FakeTradingAdapter:
    """Minimal fake trading adapter for execution tests."""

    def __init__(self) -> None:
        self.submissions: list[object] = []

    async def submit_order(self, order_request: object) -> OrderSnapshot:
        self.submissions.append(order_request)
        client_order_id = order_request.client_order_id
        limit_price = getattr(order_request, "limit_price", None)
        return OrderSnapshot(
            broker_order_id="broker-order-1",
            client_order_id=client_order_id,
            idempotency_key=client_order_id,
            symbol=order_request.symbol,
            side=Side.BUY,
            status=OrderStatus.NEW,
            qty=Decimal(str(order_request.qty)),
            filled_qty=Decimal("0"),
            order_type=str(order_request.type).lower(),
            time_in_force="day",
            limit_price=Decimal(str(limit_price)) if limit_price is not None else None,
            stop_price=Decimal(str(order_request.stop_loss.stop_price)),
            filled_avg_price=None,
            submitted_at=datetime.now(UTC),
            event_at=datetime.now(UTC),
            raw_payload={"client_order_id": client_order_id},
        )

    async def cancel_order(self, order_id: str) -> None:
        return None


async def seed_account(session_factory) -> None:
    """Seed one paper account snapshot for approval tests."""
    async with session_factory() as session:
        async with session.begin():
            await AccountRepository(session).upsert_account_snapshot(
                AccountSnapshot(
                    account_id="acct-1",
                    status="ACTIVE",
                    currency="USD",
                    buying_power=Decimal("10000"),
                    equity=Decimal("10000"),
                    raw_payload={},
                )
            )


def build_symbol_context(symbol: str, closes: list[str]) -> SymbolMarketContext:
    """Build a deterministic symbol context from close prices."""
    now = datetime.now(UTC)
    bars = [
        OhlcvBar(
            timestamp=now - timedelta(minutes=len(closes) - index),
            open=Decimal(close),
            high=Decimal(close) + Decimal("1"),
            low=Decimal(close) - Decimal("1"),
            close=Decimal(close),
            volume=Decimal("1000"),
        )
        for index, close in enumerate(closes)
    ]
    close_values = [bar.close for bar in bars]
    return SymbolMarketContext(
        symbol=symbol,
        bars=bars,
        latest_price=bars[-1].close,
        ema_fast=ema(close_values, 9),
        ema_slow=ema(close_values, 21),
        rsi=rsi(close_values, 14),
        volatility_pct=volatility_pct(close_values, 10),
    )


@pytest.mark.asyncio
async def test_strategy_output_and_ranking() -> None:
    market_ctx = StrategyMarketContext(
        symbols={
            "AAPL": build_symbol_context(
                "AAPL",
                [
                    "100", "101", "102", "103", "104", "105", "106", "107",
                    "108", "109", "110", "111", "112", "113", "114", "115",
                    "116", "117", "118", "119", "120", "121",
                ],
            ),
            "MSFT": build_symbol_context(
                "MSFT",
                [
                    "120", "119", "118", "117", "116", "115", "114", "113",
                    "112", "111", "110", "109", "108", "107", "106", "107",
                    "108", "109", "110", "111", "112", "113",
                ],
            ),
        }
    )
    from app.core.trading import StrategyPortfolioContext

    portfolio_ctx = StrategyPortfolioContext(
        equity=Decimal("10000"),
        buying_power=Decimal("10000"),
        gross_exposure=Decimal("0"),
        net_exposure=Decimal("0"),
    )

    registry = StrategyRegistry()
    registry.register(TrendFollowingStrategy())
    registry.register(MeanReversionStrategy())
    proposals = await registry.generate_candidates(market_ctx, portfolio_ctx)

    assert proposals
    assert all(proposal.symbol in {"AAPL", "MSFT"} for proposal in proposals)
    assert all(proposal.stop_price > 0 for proposal in proposals)
    assert all(proposal.invalidations for proposal in proposals)

    ranked = CandidateRanker().rank(proposals, market_ctx, limit=2)
    assert len(ranked) <= 2
    assert ranked[0].score >= ranked[-1].score


def test_order_factory_builds_protected_order() -> None:
    from app.core.trading import TradeApprovalDecision, TradeProposal

    proposal = TradeProposal(
        proposal_id="proposal-1",
        strategy_id="trend_following",
        strategy_version="v1",
        symbol="AAPL",
        side=Side.BUY,
        entry_price=Decimal("100"),
        stop_price=Decimal("98"),
        take_profit_price=Decimal("104"),
        requested_qty=Decimal("10"),
        confidence=Decimal("0.7"),
        generated_at=datetime.now(UTC),
        bar_timestamp=datetime.now(UTC),
    )
    approval = TradeApprovalDecision(
        approved=True,
        proposal_id="proposal-1",
        approved_qty=Decimal("10"),
        approved_notional=Decimal("1000"),
    )

    result = OrderFactory().build(proposal, approval, client_order_id="client-1")

    assert result.client_order_id == "client-1"
    assert result.order_request.stop_loss.stop_price == 98.0
    assert result.order_request.take_profit.limit_price == 104.0


@pytest.mark.asyncio
async def test_proposal_to_approval_to_execution_flow_is_idempotent() -> None:
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    await create_schema(engine)
    session_factory = build_session_factory(engine)
    await seed_account(session_factory)

    settings = Settings(enable_startup_broker_validation=False, enable_stream_worker=False)
    dispatcher = EventDispatcher()
    proposal_service = ProposalEvaluationService(settings, session_factory, dispatcher)
    fake_adapter = FakeTradingAdapter()
    router = ExecutionRouter(session_factory, fake_adapter, dispatcher)
    execution_engine = ExecutionEngine(settings, session_factory, router, dispatcher)

    from app.core.trading import TradeProposal

    proposal = TradeProposal(
        proposal_id="intent-1",
        strategy_id="trend_following",
        strategy_version="v1",
        symbol="AAPL",
        side=Side.BUY,
        entry_price=Decimal("100"),
        stop_price=Decimal("98"),
        take_profit_price=Decimal("104"),
        requested_qty=Decimal("10"),
        confidence=Decimal("0.7"),
        generated_at=datetime.now(UTC),
        bar_timestamp=datetime.now(UTC),
        invalidations=["close_below_slow_ema"],
    )
    approval = await proposal_service.evaluate_proposal(proposal)
    assert approval.approved is True

    execution = await execution_engine.execute(proposal, approval)
    assert execution.submitted is True
    assert len(fake_adapter.submissions) == 1

    async with session_factory() as session:
        orders = await OrderRepository(session).list_open_orders()
        assert len(orders) == 1

    duplicate = await execution_engine.execute(proposal, approval)
    assert duplicate.submitted is False
    assert duplicate.message == "duplicate_submission_deduplicated"
    assert len(fake_adapter.submissions) == 1

    await engine.dispose()
