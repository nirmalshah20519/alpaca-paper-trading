"""
tests/test_calculators.py

Tests for Phase 4: Calculator engine and components.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone

from app.calculator.indicator_calculator import IndicatorCalculator
from app.calculator.liquidity_calculator import LiquidityCalculator
from app.calculator.risk_calculator import RiskCalculator
from app.calculator.position_sizer import PositionSizer
from app.calculator.pnl_risk_calculator import PnLRiskCalculator
from app.calculator.calculator_engine import CalculatorEngine


@pytest.fixture
def sample_bars():
    """Create 50 days of dummy bar data."""
    dates = [datetime.now(timezone.utc) - timedelta(days=i) for i in range(50)]
    dates.reverse()
    
    data = {
        "open": np.linspace(100, 150, 50),
        "high": np.linspace(105, 155, 50),
        "low": np.linspace(95, 145, 50),
        "close": np.linspace(100, 150, 50),
        "volume": [1000000] * 50
    }
    return pd.DataFrame(data, index=dates)


def test_indicator_calculator(sample_bars):
    calc = IndicatorCalculator()
    results = calc.compute_all(sample_bars)
    
    assert "sma_20" in results
    assert "rsi_14" in results
    assert "atr_14" in results
    assert results["sma_20"] > 100
    assert 0 <= results["rsi_14"] <= 100


def test_risk_calculator():
    calc = RiskCalculator()
    # entry=100, ATR=2, SL_mult=2 -> SL=96, TP_mult=4 -> TP=108
    results = calc.compute_risk_levels("BUY", 100.0, 2.0)
    
    assert results["stop_loss"] == 96.0
    assert results["take_profit"] == 108.0
    # Reward = 4*ATR=8, Risk = 2*ATR=4 -> RR = 8/4 = 2.0
    assert results["rr_ratio"] == 2.0


def test_position_sizer():
    sizer = PositionSizer()
    # equity=100k, entry=100, sl=98 -> risk=2.
    # risk_budget = 100k * 0.01 (def) = 1000.
    # qty_by_risk = 1000 / 2 = 500.
    # But MAX_POSITION_PCT_OF_EQUITY = 0.05 -> capital_budget = 5000.
    # qty_by_capital = 5000 / 100 = 50.
    # Min(500, 50) = 50.
    results = sizer.compute_size(100000.0, 100.0, 98.0)
    
    assert results["qty"] == 50.0
    assert results["dollar_amount"] == 5000.0


def test_calculator_engine(sample_bars):
    engine = CalculatorEngine()
    
    market_data = {
        "symbol": "AAPL",
        "latest_price": 150.0,
        "spread_pct": 0.001,
        "bars": sample_bars
    }
    account_snapshot = {"equity": 100000.0}
    
    results = engine.run_entry_analysis(market_data, account_snapshot)
    
    assert results["symbol"] == "AAPL"
    assert "indicators" in results
    assert "risk" in results
    assert "sizing" in results
    assert results["liquidity"]["is_liquid"] is True
    assert "buy" in results["risk"]


def test_liquidity_uses_daily_volume_not_last_bar_average():
    dates = [datetime(2026, 5, 5, 13, 30, tzinfo=timezone.utc) + timedelta(minutes=i) for i in range(10)]
    bars = pd.DataFrame(
        {
            "close": [100.0] * 10,
            "volume": [100_000] * 10,
        },
        index=dates,
    )

    result = LiquidityCalculator().check_liquidity({"spread_pct": 0.001}, bars)

    assert result["avg_daily_volume"] == 1_000_000.0
    assert result["is_liquid"] is True


def test_crypto_liquidity_uses_daily_dollar_volume():
    dates = [datetime(2026, 5, 5, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=i) for i in range(10)]
    bars = pd.DataFrame(
        {
            "close": [50_000.0] * 10,
            "volume": [3.0] * 10,
        },
        index=dates,
    )

    result = LiquidityCalculator().check_liquidity(
        {"symbol": "BTC/USD", "spread_pct": 0.001},
        bars,
    )

    assert result["avg_daily_volume"] == 30.0
    assert result["avg_daily_dollar_volume"] == 1_500_000.0
    assert result["is_liquid"] is True


def test_pnl_risk_calculator_detects_profit_giveback():
    dates = [datetime.now(timezone.utc) - timedelta(minutes=i) for i in range(30)]
    dates.reverse()
    bars = pd.DataFrame(
        {
            "open": np.linspace(100, 109, 30),
            "high": [101.0] * 10 + [120.0] * 20,
            "low": [99.0] * 30,
            "close": np.linspace(100, 109, 30),
            "volume": [1000000] * 30,
        },
        index=dates,
    )
    position = {
        "symbol": "AAPL",
        "qty": 10,
        "side": "long",
        "avg_entry_price": 100.0,
        "unrealized_pl": 90.0,
        "unrealized_plpc": 0.09,
    }
    market_data = {"symbol": "AAPL", "latest_price": 109.0, "bars": bars}

    result = PnLRiskCalculator().compute(position, market_data)

    assert result["pnl_pct"] == 0.09
    assert result["mfe_pct"] == 0.2
    assert result["giveback_ratio"] > 0.45
    assert result["risk_state"] in {"PROFIT_GIVEBACK", "TRAIL_BREACH"}
    assert result["exit_pressure"] == "high"
