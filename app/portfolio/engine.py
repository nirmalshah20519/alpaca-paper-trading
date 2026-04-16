"""Portfolio allocation engine for deterministic proposal sizing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.core.config import Settings
from app.core.trading import AllocationDecision, TradeProposal
from app.portfolio.correlation import CorrelationEngine
from app.portfolio.sizing import quantity_for_budget


@dataclass(slots=True)
class PortfolioSnapshot:
    """Current allocation and exposure view used by the approval pipeline."""

    as_of: datetime
    equity: Decimal
    buying_power: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal
    daily_turnover: Decimal
    open_positions: int
    symbol_exposure: dict[str, Decimal]
    strategy_exposure: dict[str, Decimal]
    sector_exposure: dict[str, Decimal]


class PortfolioEngine:
    """Apply capital budgets before the risk engine validates a proposal."""

    def __init__(
        self,
        settings: Settings,
        correlation_engine: CorrelationEngine | None = None,
    ) -> None:
        self._settings = settings
        self._correlation_engine = correlation_engine or CorrelationEngine()

    def allocate(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        active_positions: list[object],
    ) -> AllocationDecision:
        """Apply deterministic portfolio caps and return an adjusted quantity."""
        total_budget = snapshot.equity * Decimal(str(self._settings.portfolio_total_budget_pct))
        symbol_budget = snapshot.equity * Decimal(str(self._settings.portfolio_symbol_budget_pct))
        strategy_budget = snapshot.equity * Decimal(
            str(self._settings.portfolio_strategy_budget_pct)
        )

        remaining_total = max(total_budget - snapshot.gross_exposure, Decimal("0"))
        remaining_symbol = max(
            symbol_budget - snapshot.symbol_exposure.get(proposal.symbol, Decimal("0")),
            Decimal("0"),
        )
        remaining_strategy = max(
            strategy_budget - snapshot.strategy_exposure.get(proposal.strategy_id, Decimal("0")),
            Decimal("0"),
        )
        remaining_buying_power = max(snapshot.buying_power, Decimal("0"))

        budgets = {
            "total_budget_remaining": remaining_total,
            "symbol_budget_remaining": remaining_symbol,
            "strategy_budget_remaining": remaining_strategy,
            "buying_power_remaining": remaining_buying_power,
        }
        smallest_budget = min(budgets.values(), default=Decimal("0"))
        approved_qty = min(
            proposal.requested_qty,
            quantity_for_budget(proposal.entry_price, smallest_budget),
        )
        approved_notional = approved_qty * proposal.entry_price

        reasons: list[str] = []
        if approved_qty < proposal.requested_qty:
            reasons.append("size_adjusted_by_portfolio_budget")
        if approved_qty <= 0:
            reasons.append("no_remaining_budget")

        bucket_result = self._correlation_engine.check_buckets(
            proposal,
            active_positions,
            sector_bucket_limit=self._settings.portfolio_sector_bucket_limit,
        )
        reasons.extend(bucket_result.reasons)
        if not bucket_result.allowed:
            approved_qty = Decimal("0")
            approved_notional = Decimal("0")

        return AllocationDecision(
            approved_qty=approved_qty,
            approved_notional=approved_notional,
            reasons=reasons,
            applied_caps=budgets,
        )
