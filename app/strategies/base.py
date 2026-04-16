"""Base strategy interfaces and shared types."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.trading import StrategyMarketContext, StrategyPortfolioContext, TradeProposal


class Strategy(ABC):
    """Broker-agnostic strategy interface from the architecture plan."""

    id: str
    version: str

    def __init__(self) -> None:
        self._market_ctx: StrategyMarketContext | None = None
        self._portfolio_ctx: StrategyPortfolioContext | None = None

    @abstractmethod
    async def prepare(
        self,
        market_ctx: StrategyMarketContext,
        portfolio_ctx: StrategyPortfolioContext,
    ) -> None:
        """Prepare the strategy with current runtime context."""

    @abstractmethod
    async def generate_candidates(self) -> list[TradeProposal]:
        """Generate broker-agnostic trade proposals."""

    @abstractmethod
    async def manage_open_positions(
        self,
        positions: list[object],
        market_ctx: StrategyMarketContext,
    ) -> list[TradeProposal]:
        """Generate proposal updates for open positions without calling the broker."""
