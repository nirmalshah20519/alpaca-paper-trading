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
from config.risk_limits import ALLOW_SHORT_SELLING
from config.strategy_params import MIN_CONFIDENCE_TO_EXECUTE


class SignalValidator:
    """
    Orchestrates all validation checks.
    """

    def __init__(self, app_state: AppState) -> None:
        self.app_state = app_state
        self.risk = RiskValidator()
        self.account = AccountValidator(app_state)
        self.duplicate = DuplicateTradeValidator(app_state)

    def validate_entry(
        self,
        signal: EntrySignal,
        account_data: dict | None = None,
        expected_symbol: str | None = None,
        entry_price: float | None = None,
    ) -> ValidationResult:
        """
        Run all entry validation rules.
        """
        if signal.action == "SKIP":
            return ValidationResult(validated=True)

        logger.info("Validating entry signal for {}...", signal.sym)

        # 1. Basic Schema Checks (handled by Pydantic mostly, but extra logic here)
        if expected_symbol and _canonical_symbol(signal.sym) != _canonical_symbol(expected_symbol):
            return ValidationResult(
                validated=False,
                reason=f"Signal symbol mismatch ({signal.sym} != {expected_symbol})",
            )

        if signal.action == "SELL" and not ALLOW_SHORT_SELLING:
            return ValidationResult(validated=False, reason="Short selling is disabled")

        if signal.conf < MIN_CONFIDENCE_TO_EXECUTE:
            return ValidationResult(
                validated=False,
                reason=f"Confidence too low ({signal.conf:.2f} < {MIN_CONFIDENCE_TO_EXECUTE:.2f})",
            )

        if signal.qty <= 0:
            return ValidationResult(validated=False, reason="Quantity must be > 0")

        # 2. Risk Checks
        risk_res = self.risk.validate(signal, entry_price=entry_price)
        if not risk_res.validated:
            return risk_res

        # 3. Account Checks
        account_data = account_data if account_data is not None else self.app_state.get_account_data()
        account_res = self.account.validate(signal, account_data, entry_price=entry_price)
        if not account_res.validated:
            return account_res

        # 4. Duplicate Check
        open_order_symbols = self.app_state.get_open_order_symbols()
        position_symbols = [str(pos.get("symbol", "")) for pos in self.app_state.get_positions()]
        dup_res = self.duplicate.validate(signal, open_order_symbols, position_symbols)
        if not dup_res.validated:
            return dup_res

        logger.info("Signal for {} PASSED all validations.", signal.sym)
        return ValidationResult(validated=True)


def _canonical_symbol(symbol: str) -> str:
    return str(symbol or "").upper().replace("/", "").replace("-", "")
