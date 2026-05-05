"""
Regression tests for entry signal guardrails.
"""

from __future__ import annotations

from app.core.models import EntrySignal
from app.core.state import AppState
from app.validator.signal_validator import SignalValidator


def _buy_signal(symbol: str = "AAPL") -> EntrySignal:
    return EntrySignal(
        sym=symbol,
        action="BUY",
        conf=0.85,
        qty=1,
        target=160.0,
        stop=145.0,
        reason_code="TREND_MOMENTUM_RISK_OK",
    )


def test_validator_uses_fresh_account_data_instead_of_empty_state():
    state = AppState()
    validator = SignalValidator(state)

    result = validator.validate_entry(
        _buy_signal(),
        account_data={"buying_power": 10_000.0},
        expected_symbol="AAPL",
        entry_price=150.0,
    )

    assert result.validated is True


def test_validator_rejects_symbol_mismatch():
    validator = SignalValidator(AppState())

    result = validator.validate_entry(
        _buy_signal("MSFT"),
        account_data={"buying_power": 10_000.0},
        expected_symbol="AAPL",
        entry_price=150.0,
    )

    assert result.validated is False
    assert "symbol mismatch" in result.reason


def test_validator_rejects_duplicate_open_order_symbol():
    state = AppState()
    state.set_open_orders(["order-1"], ["AAPL"])
    validator = SignalValidator(state)

    result = validator.validate_entry(
        _buy_signal(),
        account_data={"buying_power": 10_000.0},
        expected_symbol="AAPL",
        entry_price=150.0,
    )

    assert result.validated is False
    assert "Open order already exists" in result.reason


def test_validator_rejects_low_confidence_signal():
    validator = SignalValidator(AppState())
    signal = _buy_signal()
    signal.conf = 0.2

    result = validator.validate_entry(
        signal,
        account_data={"buying_power": 10_000.0},
        expected_symbol="AAPL",
        entry_price=150.0,
    )

    assert result.validated is False
    assert "Confidence too low" in result.reason


def test_validator_rejects_bad_risk_reward_direction():
    validator = SignalValidator(AppState())
    signal = _buy_signal()
    signal.stop = 155.0

    result = validator.validate_entry(
        signal,
        account_data={"buying_power": 10_000.0},
        expected_symbol="AAPL",
        entry_price=150.0,
    )

    assert result.validated is False
    assert "target/stop direction" in result.reason
