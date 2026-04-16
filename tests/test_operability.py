"""Operator-facing usability and safety tests."""

from __future__ import annotations

from datetime import UTC
from decimal import Decimal

import pytest

from app.core.config import Settings
from app.core.trading import TradeProposal
from app.orchestration.service import OrchestrationService


def test_trade_proposal_defaults_timestamps() -> None:
    proposal = TradeProposal(
        proposal_id="proposal-1",
        strategy_id="mean_reversion",
        strategy_version="v1",
        symbol="AAPL",
        side="buy",
        entry_price=Decimal("100"),
        stop_price=Decimal("98"),
        take_profit_price=Decimal("104"),
        requested_qty=Decimal("5"),
    )
    assert proposal.generated_at.tzinfo == UTC
    assert proposal.bar_timestamp.tzinfo == UTC


def test_broker_account_endpoint_requires_credentials(client) -> None:
    response = client.get("/internal/broker/account")
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_orchestration_refuses_execution_when_disabled() -> None:
    class DummyMarketDataService:
        async def build_market_context(self, symbols, limit=50):  # noqa: ANN001, ANN201
            return object()

    class DummyStrategyRegistry:
        async def generate_candidates(self, market_ctx, portfolio_ctx):  # noqa: ANN001, ANN201
            return []

    class DummyProposalService:
        async def get_strategy_portfolio_context(self):  # noqa: ANN201
            return object()

        async def get_risk_summary(self):  # noqa: ANN201
            class Summary:
                open_positions = 0

            return Summary()

    class DummyMetricsService:
        def increment(self, key, amount=1):  # noqa: ANN001, ANN201
            return None

        def set_open_positions(self, count):  # noqa: ANN001, ANN201
            return None

        def snapshot(self):  # noqa: ANN201
            return None

    service = OrchestrationService(
        Settings(
            enable_startup_broker_validation=False,
            enable_stream_worker=False,
            enable_paper_execution=False,
        ),
        DummyMarketDataService(),
        DummyStrategyRegistry(),
        DummyProposalService(),
        execution_engine=None,
        metrics_service=DummyMetricsService(),
    )

    with pytest.raises(ValueError, match="Paper execution is disabled"):
        await service.run_cycle(dry_run=False)
