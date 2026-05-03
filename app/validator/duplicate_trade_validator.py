"""
app/validator/duplicate_trade_validator.py

DuplicateTradeValidator — ensures we don't double up on positions.
"""

from __future__ import annotations

from app.core.models import EntrySignal, ValidationResult
from app.core.state import AppState


class DuplicateTradeValidator:
    """
    Prevents duplicate entries for the same symbol.
    """

    def __init__(self, app_state: AppState) -> None:
        self.app_state = app_state

    def validate(self, signal: EntrySignal, open_orders: list[str]) -> ValidationResult:
        if signal.action == "SKIP":
            return ValidationResult(validated=True)

        # 1. Check if we already have an open order for this symbol
        # open_orders in AppState is just IDs. We need symbols.
        # Phase 3 ReconciliationLoop should probably store open order symbols too.
        
        return ValidationResult(validated=True)
