"""
tests/test_integration.py

Integration tests for the full EntryOpportunityLoop pipeline.
"""

import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
from app.loops.entry_opportunity_loop import EntryOpportunityLoop
from app.loops.open_order_monitor_loop import OpenOrderMonitorLoop
from app.core.state import AppState
from app.core.models import EntrySignal, ExitSignal, ValidationResult


@pytest.fixture
def mock_services():
    mocks = {
        "market_data": MagicMock(),
        "account": MagicMock(),
        "calculator": MagicMock(),
        "llm": MagicMock(),
        "prompt_builder": MagicMock(),
        "validator": MagicMock(),
        "executor": MagicMock()
    }
    # Important: prevent the loop from skipping due to "market closing"
    mocks["account"].is_market_closing_soon.return_value = False
    return mocks


def test_entry_loop_full_pipeline(mock_services):
    app_state = AppState()
    app_state.set_active_assets(["AAPL"])
    
    loop = EntryOpportunityLoop(
        app_state=app_state,
        market_data_service=mock_services["market_data"],
        account_service=mock_services["account"],
        calculator=mock_services["calculator"],
        llm=mock_services["llm"],
        prompt_builder=mock_services["prompt_builder"],
        validator=mock_services["validator"],
        executor=mock_services["executor"]
    )
    
    # 1. Market Data
    mock_services["market_data"].fetch_required_entry_data.return_value = {
        "latest_price": 150.0,
        "bars": pd.DataFrame({"close": [150.0] * 20})
    }
    
    # 2. Calculator
    mock_services["calculator"].run_entry_analysis.return_value = {
        "symbol": "AAPL", 
        "entry_price": 150.0,
        "latest_price": 150.0
    }
    
    # 3. LLM
    signal = EntrySignal(
        sym="AAPL", action="BUY", conf=0.9, qty=10, 
        target=160.0, stop=145.0, reason_code="test"
    )
    mock_services["llm"].get_decision.return_value = signal
    
    # 4. Validator
    mock_services["validator"].validate_entry.return_value = ValidationResult(validated=True)
    
    # Run one cycle
    with patch("app.loops.entry_opportunity_loop.MAX_DOLLAR_PER_TRADE", 200.0):
        loop.run_once()
    
    # Verify calls
    # qty is overridden to 1.3333 because latest_price=150, MAX_DOLLAR_PER_TRADE=200,
    # and fractional stock quantity is enabled.
    assert signal.qty == 1.3333
    mock_services["executor"].execute_entry.assert_called_with(signal)


def test_entry_loop_caps_qty_by_position_sizer_for_crypto(mock_services):
    app_state = AppState()
    app_state.set_active_assets(["BTC/USD"])

    loop = EntryOpportunityLoop(
        app_state=app_state,
        market_data_service=mock_services["market_data"],
        account_service=mock_services["account"],
        calculator=mock_services["calculator"],
        llm=mock_services["llm"],
        prompt_builder=mock_services["prompt_builder"],
        validator=mock_services["validator"],
        executor=mock_services["executor"]
    )

    mock_services["market_data"].fetch_required_entry_data.return_value = {
        "latest_price": 100.0,
        "bars": pd.DataFrame({"close": [100.0] * 20})
    }
    mock_services["calculator"].run_entry_analysis.return_value = {
        "symbol": "BTC/USD",
        "entry_price": 100.0,
        "sizing": {"qty": 0.75},
    }
    signal = EntrySignal(
        sym="BTC/USD", action="BUY", conf=0.9, qty=10,
        target=110.0, stop=95.0, reason_code="test"
    )
    mock_services["llm"].get_decision.return_value = signal
    mock_services["validator"].validate_entry.return_value = ValidationResult(validated=True)

    with patch("app.loops.entry_opportunity_loop.MAX_DOLLAR_PER_TRADE", 200.0):
        loop.run_once()

    assert signal.qty == 0.75
    mock_services["executor"].execute_entry.assert_called_with(signal)


def test_entry_loop_treats_low_volume_as_soft_liquidity_and_calls_llm(mock_services):
    app_state = AppState()
    app_state.set_active_assets(["BTC/USD"])

    loop = EntryOpportunityLoop(
        app_state=app_state,
        market_data_service=mock_services["market_data"],
        account_service=mock_services["account"],
        calculator=mock_services["calculator"],
        llm=mock_services["llm"],
        prompt_builder=mock_services["prompt_builder"],
        validator=mock_services["validator"],
        executor=mock_services["executor"]
    )

    mock_services["market_data"].fetch_required_entry_data.return_value = {
        "latest_price": 100.0,
        "bars": pd.DataFrame({"close": [100.0] * 20})
    }
    mock_services["calculator"].run_entry_analysis.return_value = {
        "symbol": "BTC/USD",
        "entry_price": 100.0,
        "liquidity": {
            "is_liquid": False,
            "reason": "Crypto dollar volume too low: 100",
            "spread_pct": 0.001,
        },
    }
    mock_services["llm"].get_decision.return_value = EntrySignal(
        sym="BTC/USD", action="SKIP", conf=0.1, qty=0.0, target=None, stop=None, reason_code="UNCERTAIN_SKIP"
    )

    loop.run_once()

    mock_services["llm"].get_decision.assert_called_once()
    mock_services["executor"].execute_entry.assert_not_called()


def test_entry_loop_still_hard_skips_wide_spread_before_llm(mock_services):
    app_state = AppState()
    app_state.set_active_assets(["BTC/USD"])

    loop = EntryOpportunityLoop(
        app_state=app_state,
        market_data_service=mock_services["market_data"],
        account_service=mock_services["account"],
        calculator=mock_services["calculator"],
        llm=mock_services["llm"],
        prompt_builder=mock_services["prompt_builder"],
        validator=mock_services["validator"],
        executor=mock_services["executor"]
    )

    mock_services["market_data"].fetch_required_entry_data.return_value = {
        "latest_price": 100.0,
        "bars": pd.DataFrame({"close": [100.0] * 20})
    }
    mock_services["calculator"].run_entry_analysis.return_value = {
        "symbol": "BTC/USD",
        "entry_price": 100.0,
        "liquidity": {
            "is_liquid": False,
            "reason": "spread_too_wide:0.0200>0.0050",
            "spread_pct": 0.02,
        },
    }

    loop.run_once()

    mock_services["llm"].get_decision.assert_not_called()
    mock_services["executor"].execute_entry.assert_not_called()
    logged_signal = mock_services["executor"].storage.record_signal.call_args.kwargs["signal"]
    validation = mock_services["executor"].storage.record_signal.call_args.kwargs["validation"]
    assert logged_signal.reason_code == "LIQUIDITY_GATE_SKIP"
    assert "spread_too_wide" in validation.reason


def test_exit_loop_full_pipeline(mock_services):
    app_state = AppState()
    
    loop = OpenOrderMonitorLoop(
        app_state=app_state,
        account_service=mock_services["account"],
        market_data_service=mock_services["market_data"],
        llm=mock_services["llm"],
        prompt_builder=mock_services["prompt_builder"],
        executor=mock_services["executor"]
    )
    
    # 1. Account / Positions
    mock_services["account"].get_open_orders.return_value = []
    mock_services["account"].get_positions.return_value = [
        {"symbol": "AAPL", "qty": 10, "avg_entry_price": 140.0, "unrealized_pl": 100.0, "unrealized_plpc": 0.07}
    ]
    
    # 2. Market Data
    mock_services["market_data"].fetch_required_exit_data.return_value = {"latest_price": 150.0}
    
    # 3. LLM
    signal = ExitSignal(sym="AAPL", action="COMPLETE", conf=0.9, reason_code="target_hit")
    mock_services["llm"].get_decision.return_value = signal
    
    # Run one cycle
    loop.run_once()
    
    # Verify
    mock_services["executor"].execute_exit.assert_called_with(
        "AAPL",
        10.0,
        side="SELL",
        reason_code="target_hit",
    )


def test_exit_loop_buys_to_cover_short_position(mock_services):
    app_state = AppState()

    loop = OpenOrderMonitorLoop(
        app_state=app_state,
        account_service=mock_services["account"],
        market_data_service=mock_services["market_data"],
        llm=mock_services["llm"],
        prompt_builder=mock_services["prompt_builder"],
        executor=mock_services["executor"]
    )

    mock_services["account"].get_open_orders.return_value = []
    mock_services["account"].get_positions.return_value = [
        {"symbol": "AAPL", "qty": 10, "side": "short", "avg_entry_price": 140.0}
    ]
    mock_services["market_data"].fetch_required_exit_data.return_value = {"latest_price": 130.0}
    mock_services["llm"].get_decision.return_value = ExitSignal(
        sym="AAPL", action="COMPLETE", conf=0.9, reason_code="target_hit"
    )

    loop.run_once()

    mock_services["executor"].execute_exit.assert_called_with(
        "AAPL",
        10.0,
        side="BUY",
        reason_code="target_hit",
    )


def test_exit_loop_hard_exits_on_stored_target_before_llm(mock_services):
    app_state = AppState()

    loop = OpenOrderMonitorLoop(
        app_state=app_state,
        account_service=mock_services["account"],
        market_data_service=mock_services["market_data"],
        llm=mock_services["llm"],
        prompt_builder=mock_services["prompt_builder"],
        executor=mock_services["executor"]
    )

    mock_services["account"].get_open_orders.return_value = []
    mock_services["account"].get_positions.return_value = [
        {"symbol": "AAPL", "qty": 10, "side": "long", "avg_entry_price": 140.0}
    ]
    mock_services["market_data"].fetch_required_exit_data.return_value = {"latest_price": 151.0}
    mock_services["executor"].storage.get_open_order_for_symbol.return_value = {
        "symbol": "AAPL",
        "entry_side": "BUY",
        "target_price": "150",
        "stop_loss_price": "135",
    }

    loop.run_once()

    mock_services["llm"].get_decision.assert_not_called()
    mock_services["executor"].execute_exit.assert_called_with(
        "AAPL",
        10.0,
        side="SELL",
        reason_code="TARGET_REACHED",
    )
