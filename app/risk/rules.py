"""Deterministic pre-trade risk rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.config import Settings
from app.core.enums import Side
from app.core.trading import TradeProposal
from app.portfolio.engine import PortfolioSnapshot
from app.state.models import Position


@dataclass(slots=True)
class RuleResult:
    """Outcome of an individual risk rule."""

    passed: bool
    reason: str | None = None


def _ensure_aware(value: datetime) -> datetime:
    """Normalize potentially naive timestamps from SQLite tests."""
    if value.tzinfo is None:
        return value.replace(tzinfo=proposal_timezone())
    return value


def proposal_timezone() -> object:
    """Return the default timezone used for proposal evaluation timestamps."""
    return UTC


def check_max_position_size(
    proposal: TradeProposal,
    snapshot: PortfolioSnapshot,
    settings: Settings,
) -> RuleResult:
    symbol_exposure = snapshot.symbol_exposure.get(proposal.symbol, Decimal("0"))
    max_notional = min(
        Decimal(str(settings.risk_max_position_notional)),
        snapshot.equity * Decimal(str(settings.risk_max_symbol_exposure_pct)),
    )
    if symbol_exposure + proposal.requested_notional > max_notional:
        return RuleResult(False, "max_position_size_per_symbol_exceeded")
    return RuleResult(True)


def check_exposure_limits(
    proposal: TradeProposal,
    snapshot: PortfolioSnapshot,
    settings: Settings,
) -> list[RuleResult]:
    signed_notional = (
        proposal.requested_notional if proposal.side == Side.BUY else -proposal.requested_notional
    )
    gross_limit = snapshot.equity * Decimal(str(settings.risk_max_gross_exposure_pct))
    net_limit = snapshot.equity * Decimal(str(settings.risk_max_net_exposure_pct))
    results = [
        RuleResult(
            snapshot.gross_exposure + proposal.requested_notional <= gross_limit,
            "max_gross_exposure_exceeded",
        ),
        RuleResult(
            abs(snapshot.net_exposure + signed_notional) <= net_limit,
            "max_net_exposure_exceeded",
        ),
    ]
    return results


def check_open_position_limit(
    snapshot: PortfolioSnapshot,
    proposal: TradeProposal,
    settings: Settings,
) -> RuleResult:
    existing_symbol = (
        proposal.symbol in snapshot.symbol_exposure
        and snapshot.symbol_exposure[proposal.symbol] > 0
    )
    projected_positions = (
        snapshot.open_positions
        if existing_symbol
        else snapshot.open_positions + 1
    )
    if projected_positions > settings.risk_max_open_positions:
        return RuleResult(False, "max_open_positions_exceeded")
    return RuleResult(True)


def check_strategy_concentration(
    proposal: TradeProposal,
    snapshot: PortfolioSnapshot,
    settings: Settings,
) -> RuleResult:
    strategy_limit = snapshot.equity * Decimal(str(settings.risk_max_strategy_exposure_pct))
    current = snapshot.strategy_exposure.get(proposal.strategy_id, Decimal("0"))
    if current + proposal.requested_notional > strategy_limit:
        return RuleResult(False, "strategy_concentration_exceeded")
    return RuleResult(True)


def check_stop_and_reward(proposal: TradeProposal, settings: Settings) -> list[RuleResult]:
    results = [
        RuleResult(
            proposal.stop_distance_ratio >= Decimal(str(settings.risk_min_stop_distance_pct)),
            "minimum_stop_distance_not_met",
        ),
        RuleResult(
            proposal.reward_risk_ratio >= Decimal(str(settings.risk_min_reward_risk_ratio)),
            "minimum_reward_risk_not_met",
        ),
    ]
    return results


def check_daily_turnover(
    proposal: TradeProposal,
    snapshot: PortfolioSnapshot,
    settings: Settings,
) -> RuleResult:
    turnover_limit = snapshot.equity * Decimal(str(settings.risk_max_daily_turnover_pct))
    if snapshot.daily_turnover + proposal.requested_notional > turnover_limit:
        return RuleResult(False, "max_daily_turnover_exceeded")
    return RuleResult(True)


def check_cooldowns(
    proposal: TradeProposal,
    *,
    active_positions: list[Position],
    recent_closed_positions: list[Position],
    settings: Settings,
    as_of: datetime,
) -> list[RuleResult]:
    results: list[RuleResult] = []
    cooldown_window = as_of - timedelta(minutes=settings.risk_cooldown_after_exit_minutes)
    side_flip_window = as_of - timedelta(minutes=settings.risk_side_flip_cooldown_minutes)

    recent_closed_same_symbol = [
        position
        for position in recent_closed_positions
        if position.symbol == proposal.symbol and position.closed_at is not None
    ]
    if any(
        _ensure_aware(position.closed_at) >= cooldown_window
        for position in recent_closed_same_symbol
    ):
        results.append(RuleResult(False, "cooldown_after_exit_active"))
    else:
        results.append(RuleResult(True))

    opposite_active = [
        position
        for position in active_positions
        if position.symbol == proposal.symbol and position.side != proposal.side
    ]
    recent_opposite_closed = [
        position
        for position in recent_closed_same_symbol
        if (
            position.side != proposal.side
            and position.closed_at is not None
            and _ensure_aware(position.closed_at) >= side_flip_window
        )
    ]
    if (opposite_active or recent_opposite_closed) and not proposal.allow_side_flip:
        results.append(RuleResult(False, "side_flip_cooldown_active"))
    else:
        results.append(RuleResult(True))

    for position in active_positions:
        if position.symbol != proposal.symbol or position.opened_at is None:
            continue
        min_hold_minutes = int(position.raw_payload.get("min_hold_minutes", 0))
        if min_hold_minutes <= 0:
            continue
        hold_deadline = _ensure_aware(position.opened_at) + timedelta(minutes=min_hold_minutes)
        if as_of < hold_deadline and position.side != proposal.side:
            results.append(RuleResult(False, "minimum_hold_time_active"))
            break
    return results
