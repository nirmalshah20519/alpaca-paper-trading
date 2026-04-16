"""Strategy registry and candidate ranking."""

from __future__ import annotations

from decimal import Decimal

from app.core.trading import (
    RankedProposal,
    StrategyMarketContext,
    StrategyPortfolioContext,
    TradeProposal,
)
from app.strategies.base import Strategy


class StrategyRegistry:
    """Register strategies and run them against strategy-safe contexts."""

    def __init__(self) -> None:
        self._strategies: dict[str, Strategy] = {}

    def register(self, strategy: Strategy) -> None:
        """Register a strategy instance."""
        self._strategies[strategy.id] = strategy

    def list_strategies(self) -> list[Strategy]:
        """Return registered strategies."""
        return list(self._strategies.values())

    async def generate_candidates(
        self,
        market_ctx: StrategyMarketContext,
        portfolio_ctx: StrategyPortfolioContext,
    ) -> list[TradeProposal]:
        """Run all registered strategies and collect proposals."""
        proposals: list[TradeProposal] = []
        for strategy in self._strategies.values():
            await strategy.prepare(market_ctx, portfolio_ctx)
            proposals.extend(await strategy.generate_candidates())
        return proposals


class CandidateRanker:
    """Apply simple confidence and volatility-based ranking."""

    def rank(
        self,
        proposals: list[TradeProposal],
        market_ctx: StrategyMarketContext,
        *,
        limit: int = 10,
    ) -> list[RankedProposal]:
        """Rank and limit proposals for the next approval stage."""
        ranked: list[RankedProposal] = []
        for proposal in proposals:
            symbol_ctx = market_ctx.symbols.get(proposal.symbol)
            volatility = symbol_ctx.volatility_pct if symbol_ctx is not None else None
            confidence = proposal.confidence or Decimal("0.5")
            volatility_score = Decimal("0")
            reasons = [f"confidence:{confidence}"]
            if volatility is not None:
                if volatility < Decimal("0.005"):
                    volatility_score = Decimal("-0.2")
                    reasons.append("volatility_too_low")
                elif volatility <= Decimal("0.05"):
                    volatility_score = Decimal("0.2")
                    reasons.append("volatility_in_range")
                else:
                    volatility_score = Decimal("-0.1")
                    reasons.append("volatility_elevated")
            score = confidence + volatility_score
            ranked.append(RankedProposal(proposal=proposal, score=score, reasons=reasons))

        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:limit]
