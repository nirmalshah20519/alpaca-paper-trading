"""
app/validator/risk_validator.py

RiskValidator — enforces RR ratio and maximum risk limits.

Design rules:
  - Validates EntrySignal against config/risk_limits.py.
  - Returns ValidationResult.
"""

from __future__ import annotations

from app.core.models import EntrySignal, ValidationResult
from config.risk_limits import MIN_RISK_REWARD_RATIO


class RiskValidator:
    """
    Validates the risk parameters of an entry signal.
    """

    def validate(self, signal: EntrySignal, entry_price: float | None = None) -> ValidationResult:
        """
        Check target/stop direction and risk/reward using deterministic price.
        """
        if signal.action == "SKIP":
            return ValidationResult(validated=True)

        if signal.target is None or signal.stop is None or not signal.qty:
            return ValidationResult(validated=False, reason="Missing target/stop/qty")

        if entry_price is None or entry_price <= 0:
            return ValidationResult(validated=False, reason="Missing entry price for risk validation")

        if signal.action == "BUY":
            risk = entry_price - signal.stop
            reward = signal.target - entry_price
            if not (signal.stop < entry_price < signal.target):
                return ValidationResult(validated=False, reason="Invalid BUY target/stop direction")
        else:
            risk = signal.stop - entry_price
            reward = entry_price - signal.target
            if not (signal.target < entry_price < signal.stop):
                return ValidationResult(validated=False, reason="Invalid SELL target/stop direction")

        if risk <= 0 or reward <= 0:
            return ValidationResult(validated=False, reason="Invalid risk/reward distances")

        rr_ratio = reward / risk
        if rr_ratio < MIN_RISK_REWARD_RATIO:
            return ValidationResult(
                validated=False,
                reason=f"Risk/reward too low ({rr_ratio:.2f} < {MIN_RISK_REWARD_RATIO:.2f})",
            )

        return ValidationResult(validated=True)
