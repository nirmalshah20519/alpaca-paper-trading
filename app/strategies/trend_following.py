"""Simple deterministic trend-following strategy."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.core.enums import Side
from app.core.idempotency import generate_trade_intent_id
from app.core.trading import StrategyMarketContext, StrategyPortfolioContext, TradeProposal
from app.strategies.base import Strategy


class TrendFollowingStrategy(Strategy):
    """Generate long trend-following proposals from EMA alignment."""

    id = "trend_following"
    version = "v1"

    async def prepare(
        self,
        market_ctx: StrategyMarketContext,
        portfolio_ctx: StrategyPortfolioContext,
    ) -> None:
        self._market_ctx = market_ctx
        self._portfolio_ctx = portfolio_ctx

    async def generate_candidates(self) -> list[TradeProposal]:
        assert self._market_ctx is not None
        proposals: list[TradeProposal] = []
        for symbol, context in self._market_ctx.symbols.items():
            if context.ema_fast is None or context.ema_slow is None or context.rsi is None:
                continue
            if context.latest_price <= context.ema_fast or context.ema_fast <= context.ema_slow:
                continue
            if context.rsi < Decimal("55"):
                continue

            stop_price = context.ema_slow
            take_profit = context.latest_price + (
                (context.latest_price - stop_price) * Decimal("2")
            )
            generated_at = datetime.now(UTC)
            proposal_id = generate_trade_intent_id(
                self.id,
                symbol,
                Side.BUY,
                context.bars[-1].timestamp,
                self.version,
            )
            proposals.append(
                TradeProposal(
                    proposal_id=proposal_id,
                    strategy_id=self.id,
                    strategy_version=self.version,
                    symbol=symbol,
                    side=Side.BUY,
                    entry_price=context.latest_price,
                    stop_price=stop_price,
                    take_profit_price=take_profit,
                    requested_qty=Decimal("10"),
                    confidence=Decimal("0.72"),
                    sector="unknown",
                    expected_holding_minutes=240,
                    min_hold_minutes=60,
                    thesis="price above fast EMA with aligned trend structure",
                    invalidations=["close_below_slow_ema", "rsi_breakdown"],
                    generated_at=generated_at,
                    bar_timestamp=context.bars[-1].timestamp,
                    metadata={"entry_style": "limit_pullback"},
                )
            )
        return proposals

    async def manage_open_positions(
        self,
        positions: list[object],
        market_ctx: StrategyMarketContext,
    ) -> list[TradeProposal]:
        return []
