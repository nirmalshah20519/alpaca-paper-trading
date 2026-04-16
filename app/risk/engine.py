"""Deterministic risk validation engine for proposal approval."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.core.config import Settings
from app.core.trading import TradeApprovalDecision, TradeProposal
from app.portfolio.engine import PortfolioSnapshot
from app.risk.breakers import BreakerStateView
from app.risk.rules import (
    RuleResult,
    check_cooldowns,
    check_daily_turnover,
    check_exposure_limits,
    check_max_position_size,
    check_open_position_limit,
    check_stop_and_reward,
    check_strategy_concentration,
)
from app.state.models import Position


class RiskEngine:
    """Apply deterministic pre-trade validation after portfolio sizing."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(
        self,
        *,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        breaker_states: list[BreakerStateView],
        active_positions: list[Position],
        recent_closed_positions: list[Position],
        approved_qty: Decimal,
        applied_caps: dict[str, Decimal],
        allocation_reasons: list[str],
    ) -> TradeApprovalDecision:
        """Validate a proposal with deterministic rules and breaker overrides."""
        adjusted_proposal = proposal.model_copy(update={"requested_qty": approved_qty})
        reasons: list[str] = []
        warnings: list[str] = []

        active_breakers = [state for state in breaker_states if state.is_active]
        if active_breakers:
            reasons.extend([f"breaker_active:{state.control_key}" for state in active_breakers])

        for reason in allocation_reasons:
            if reason in {"no_remaining_budget"} or reason.startswith(
                "sector_bucket_limit_exceeded"
            ):
                reasons.append(reason)
            elif reason not in warnings:
                warnings.append(reason)

        if adjusted_proposal.requested_qty <= 0:
            reasons.append("proposal_size_zero_after_allocation")

        rule_results: list[RuleResult] = []
        rule_results.append(check_max_position_size(adjusted_proposal, snapshot, self._settings))
        rule_results.extend(check_exposure_limits(adjusted_proposal, snapshot, self._settings))
        rule_results.append(check_open_position_limit(snapshot, adjusted_proposal, self._settings))
        rule_results.append(
            check_strategy_concentration(adjusted_proposal, snapshot, self._settings)
        )
        rule_results.append(check_daily_turnover(adjusted_proposal, snapshot, self._settings))
        rule_results.extend(check_stop_and_reward(adjusted_proposal, self._settings))
        rule_results.extend(
            check_cooldowns(
                adjusted_proposal,
                active_positions=active_positions,
                recent_closed_positions=recent_closed_positions,
                settings=self._settings,
                as_of=datetime.now(UTC),
            )
        )

        for result in rule_results:
            if not result.passed and result.reason is not None:
                reasons.append(result.reason)

        if adjusted_proposal.requested_qty < proposal.requested_qty:
            warnings.append("quantity_adjusted_before_risk_validation")

        approved = not reasons
        approved_notional = adjusted_proposal.requested_notional

        return TradeApprovalDecision(
            approved=approved,
            proposal_id=proposal.proposal_id,
            approved_qty=adjusted_proposal.requested_qty,
            approved_notional=approved_notional,
            rejection_reasons=reasons,
            warnings=warnings,
            applied_caps=applied_caps,
        )
