"""Simple deterministic mean-reversion strategy."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.core.enums import Side
from app.core.idempotency import generate_trade_intent_id
from app.core.trading import StrategyMarketContext, StrategyPortfolioContext, TradeProposal
from app.strategies.base import Strategy


class MeanReversionStrategy(Strategy):
    """Generate long mean-reversion proposals from RSI and EMA context."""

    id = "mean_reversion"
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
            if context.latest_price >= context.ema_fast:
                continue
            if context.rsi > Decimal("35"):
                continue
            if context.ema_fast < context.ema_slow * Decimal("0.97"):
                continue

            stop_price = min(bar.low for bar in context.bars[-5:])
            take_profit = context.ema_fast
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
                    requested_qty=Decimal("8"),
                    confidence=Decimal("0.68"),
                    sector="unknown",
                    expected_holding_minutes=120,
                    min_hold_minutes=30,
                    thesis="short-term oversold pullback near higher-timeframe support",
                    invalidations=["break_below_recent_low", "trend_structure_failure"],
                    generated_at=generated_at,
                    bar_timestamp=context.bars[-1].timestamp,
                    metadata={"entry_style": "limit_mean_reversion"},
                )
            )
        return proposals

    async def manage_open_positions(
        self,
        positions: list[object],
        market_ctx: StrategyMarketContext,
    ) -> list[TradeProposal]:
        return []
