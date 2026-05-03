"""
app/validator/signal_validator.py

SignalValidator — the final safety gate before order execution.

Design rules:
  - Orchestrates multiple sub-validators.
  - Returns a single ValidationResult.
  - Fail-fast: the first rejection stops the process.
"""

from __future__ import annotations

from app.core.models import EntrySignal, ValidationResult
from app.core.state import AppState
from app.validator.risk_validator import RiskValidator
from app.validator.account_validator import AccountValidator
from app.validator.duplicate_trade_validator import DuplicateTradeValidator
from app.utils.logger import logger


class SignalValidator:
    """
    Orchestrates all validation checks.
    """

    def __init__(self, app_state: AppState) -> None:
        self.app_state = app_state
        self.risk = RiskValidator()
        self.account = AccountValidator(app_state)
        self.duplicate = DuplicateTradeValidator(app_state)

    def validate_entry(self, signal: EntrySignal) -> ValidationResult:
        """
        Run all entry validation rules.
        """
        if signal.action == "SKIP":
            return ValidationResult(validated=True)

        logger.info("Validating entry signal for {}...", signal.sym)

        # 1. Basic Schema Checks (handled by Pydantic mostly, but extra logic here)
        if signal.qty <= 0:
            return ValidationResult(validated=False, reason="Quantity must be > 0")

        # 2. Risk Checks
        risk_res = self.risk.validate(signal)
        if not risk_res.validated:
            return risk_res

        # 3. Account Checks
        # Get latest account data from AppState (updated by ReconciliationLoop)
        account_data = self.app_state.get_account_data()
        account_res = self.account.validate(signal, account_data)
        if not account_res.validated:
            return account_res

        # 4. Duplicate Check
        open_orders = self.app_state.get_open_orders()
        dup_res = self.duplicate.validate(signal, open_orders)
        if not dup_res.validated:
            return dup_res

        logger.info("Signal for {} PASSED all validations.", signal.sym)
        return ValidationResult(validated=True)
