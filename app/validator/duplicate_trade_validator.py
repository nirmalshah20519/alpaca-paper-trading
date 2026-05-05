"""
app/validator/duplicate_trade_validator.py

DuplicateTradeValidator — ensures we don't double up on positions.
"""

from __future__ import annotations

from app.core.models import EntrySignal, ValidationResult
from app.core.state import AppState
from config.risk_limits import ALLOW_POSITION_SCALING


class DuplicateTradeValidator:
    """
    Prevents duplicate entries for the same symbol.
    """

    def __init__(self, app_state: AppState) -> None:
        self.app_state = app_state

    def validate(
        self,
        signal: EntrySignal,
        open_order_symbols: list[str] | None = None,
        position_symbols: list[str] | None = None,
    ) -> ValidationResult:
        if signal.action == "SKIP":
            return ValidationResult(validated=True)

        signal_symbol = _canonical_symbol(signal.sym)
        open_symbols = {_canonical_symbol(symbol) for symbol in (open_order_symbols or [])}
        held_symbols = {_canonical_symbol(symbol) for symbol in (position_symbols or [])}

        if signal_symbol in open_symbols:
            return ValidationResult(validated=False, reason="Open order already exists for symbol")

        if not ALLOW_POSITION_SCALING and signal_symbol in held_symbols:
            return ValidationResult(validated=False, reason="Position already exists for symbol")

        return ValidationResult(validated=True)


def _canonical_symbol(symbol: str) -> str:
    return str(symbol or "").upper().replace("/", "").replace("-", "")
