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
    return {
        "market_data": MagicMock(),
        "account": MagicMock(),
        "calculator": MagicMock(),
        "llm": MagicMock(),
        "prompt_builder": MagicMock(),
        "validator": MagicMock(),
        "executor": MagicMock()
    }


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
    mock_services["calculator"].run_entry_analysis.return_value = {"symbol": "AAPL", "entry_price": 150.0}
    
    # 3. LLM
    signal = EntrySignal(
        sym="AAPL", action="BUY", conf=0.9, qty=10, 
        target=160.0, stop=145.0, reason_code="test"
    )
    mock_services["llm"].get_decision.return_value = signal
    
    # 4. Validator
    mock_services["validator"].validate_entry.return_value = ValidationResult(validated=True)
    
    # Run one cycle
    loop.run_once()
    
    # Verify calls
    mock_services["executor"].execute_entry.assert_called_with(signal)


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
    mock_services["executor"].execute_exit.assert_called_with("AAPL", 10)
