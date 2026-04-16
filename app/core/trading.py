"""Broker-agnostic proposal, approval, and summary schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import Side


class TradeProposal(BaseModel):
    """Strategy-facing proposal model that contains no broker order details."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    strategy_id: str
    strategy_version: str
    symbol: str
    side: Side
    entry_price: Decimal = Field(gt=0)
    stop_price: Decimal = Field(gt=0)
    take_profit_price: Decimal = Field(gt=0)
    requested_qty: Decimal = Field(gt=0)
    confidence: Decimal | None = None
    sector: str | None = None
    expected_holding_minutes: int | None = Field(default=None, ge=0)
    min_hold_minutes: int = Field(default=0, ge=0)
    allow_side_flip: bool = False
    thesis: str | None = None
    invalidations: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    bar_timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def requested_notional(self) -> Decimal:
        """Return requested capital at the proposal entry price."""
        return self.entry_price * self.requested_qty

    @property
    def stop_distance_ratio(self) -> Decimal:
        """Return relative stop distance as a ratio."""
        return abs(self.entry_price - self.stop_price) / self.entry_price

    @property
    def reward_risk_ratio(self) -> Decimal:
        """Return expected reward to risk ratio."""
        risk = abs(self.entry_price - self.stop_price)
        if risk == Decimal("0"):
            return Decimal("0")
        return abs(self.take_profit_price - self.entry_price) / risk


class AllocationDecision(BaseModel):
    """Portfolio allocation result before risk approval."""

    approved_qty: Decimal = Field(ge=0)
    approved_notional: Decimal = Field(ge=0)
    reasons: list[str] = Field(default_factory=list)
    applied_caps: dict[str, Decimal] = Field(default_factory=dict)


class TradeApprovalDecision(BaseModel):
    """Final deterministic proposal evaluation result."""

    approved: bool
    proposal_id: str
    approved_qty: Decimal = Field(ge=0)
    approved_notional: Decimal = Field(ge=0)
    rejection_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    applied_caps: dict[str, Decimal] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    """Execution result for an approved paper trade."""

    submitted: bool
    proposal_id: str
    trade_intent_id: str | None = None
    client_order_id: str | None = None
    broker_order_id: str | None = None
    message: str | None = None


class RankedProposal(BaseModel):
    """Ranked proposal ready for approval evaluation."""

    proposal: TradeProposal
    score: Decimal
    reasons: list[str] = Field(default_factory=list)


class OhlcvBar(BaseModel):
    """Normalized OHLCV bar for strategy inputs."""

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class SymbolMarketContext(BaseModel):
    """Strategy-safe market context for a single symbol."""

    symbol: str
    bars: list[OhlcvBar]
    latest_price: Decimal
    ema_fast: Decimal | None = None
    ema_slow: Decimal | None = None
    rsi: Decimal | None = None
    volatility_pct: Decimal | None = None


class StrategyMarketContext(BaseModel):
    """Strategy-safe market context for the current watchlist."""

    symbols: dict[str, SymbolMarketContext]


class StrategyPositionView(BaseModel):
    """Strategy-safe position view."""

    symbol: str
    side: Side
    qty: Decimal
    avg_entry_price: Decimal | None = None
    strategy_id: str | None = None
    sector: str | None = None
    opened_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class StrategyPortfolioContext(BaseModel):
    """Strategy-safe portfolio context."""

    equity: Decimal = Field(ge=0)
    buying_power: Decimal = Field(ge=0)
    gross_exposure: Decimal = Field(ge=0)
    net_exposure: Decimal
    open_positions: list[StrategyPositionView] = Field(default_factory=list)


class BreakerStateView(BaseModel):
    """Readable breaker or kill-switch state."""

    control_key: str
    is_active: bool
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RiskSummaryView(BaseModel):
    """Current risk and exposure summary."""

    as_of: datetime
    equity: Decimal = Field(ge=0)
    buying_power: Decimal = Field(ge=0)
    gross_exposure: Decimal = Field(ge=0)
    net_exposure: Decimal
    open_positions: int = Field(ge=0)
    daily_turnover: Decimal = Field(ge=0)
    kill_switch_active: bool
    breakers: list[BreakerStateView] = Field(default_factory=list)


class MetricsView(BaseModel):
    """Lightweight operational metrics."""

    proposals_generated: int = 0
    approvals: int = 0
    rejections: int = 0
    orders_placed: int = 0
    open_positions: int = 0


class OrchestrationCycleResult(BaseModel):
    """Result of a single orchestration cycle."""

    proposals_generated: int
    proposals_ranked: int
    approvals: list[TradeApprovalDecision] = Field(default_factory=list)
    executions: list[ExecutionResult] = Field(default_factory=list)
