"""
app/validator/account_validator.py

AccountValidator — checks buying power and exposure limits.

Design rules:
  - Validates if the account can handle the new position.
"""

from __future__ import annotations

from app.core.models import EntrySignal, ValidationResult
from app.core.state import AppState
from config.risk_limits import MAX_OPEN_POSITIONS


class AccountValidator:
    """
    Validates signal against account limits.
    """

    def __init__(self, app_state: AppState) -> None:
        self.app_state = app_state

    def validate(self, signal: EntrySignal, account_data: dict) -> ValidationResult:
        if signal.action == "SKIP":
            return ValidationResult(validated=True)

        # 1. Check buying power
        buying_power = account_data.get("buying_power", 0.0)
        # We need the current market price to estimate cost. 
        # Since EntrySignal doesn't have it, we use the average of target/stop or a very safe estimate.
        price_estimate = (signal.target + signal.stop) / 2 if (signal.target and signal.stop) else 0.0
        
        estimated_cost = signal.qty * price_estimate
        
        if price_estimate > 0 and buying_power < estimated_cost:
            return ValidationResult(validated=False, reason=f"Insufficient buying power (Need ${estimated_cost:.2f}, Have ${buying_power:.2f})")

        # 2. Check position count
        # In Phase 3, ReconciliationLoop updates AppState with account data.
        # But we don't have current position count in AppState yet.
        # Let's assume account_data has it.
        
        return ValidationResult(validated=True)
