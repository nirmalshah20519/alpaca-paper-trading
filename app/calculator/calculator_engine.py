"""
app/calculator/calculator_engine.py

CalculatorEngine — orchestrates all calculator components.

This is the main entry point for the calculator package.
"""

from __future__ import annotations

from app.calculator.indicator_calculator import IndicatorCalculator
from app.calculator.risk_calculator import RiskCalculator
from app.calculator.liquidity_calculator import LiquidityCalculator
from app.calculator.position_sizer import PositionSizer
from app.calculator.pnl_risk_calculator import PnLRiskCalculator
from app.utils.logger import logger


class CalculatorEngine:
    """
    High-level engine that runs the calculation pipeline.
    """

    def __init__(self) -> None:
        self.indicators = IndicatorCalculator()
        self.risk = RiskCalculator()
        self.liquidity = LiquidityCalculator()
        self.sizer = PositionSizer()
        self.pnl_risk = PnLRiskCalculator()

    def run_entry_analysis(self, market_data: dict, account_snapshot: dict) -> dict:
        """
        Runs the full entry analysis for a symbol.
        
        market_data should contain:
            - symbol
            - latest_price
            - quote (bid, ask, spread_pct)
            - bars (DataFrame)
        
        Returns a dict with all computed metrics.
        """
        symbol = market_data.get("symbol")
        price = market_data.get("latest_price")
        bars = market_data.get("bars")
        
        if not symbol or not price or bars is None or bars.empty:
            return {}

        results = {"symbol": symbol, "entry_price": price}

        # 1. Indicators
        ind_results = self.indicators.compute_all(bars)
        results["indicators"] = ind_results

        # 2. Risk Levels
        atr = ind_results.get("atr_14")
        risk_results = self.risk.compute_risk_levels("BUY", price, atr)
        results["risk"] = risk_results

        # 3. Liquidity
        liq_results = self.liquidity.check_liquidity(market_data, bars)
        results["liquidity"] = liq_results

        # 4. Position Sizing
        equity = account_snapshot.get("equity", 0.0)
        sl_price = risk_results.get("stop_loss", 0.0)
        
        if equity > 0 and sl_price > 0:
            size_results = self.sizer.compute_size(equity, price, sl_price)
            results["sizing"] = size_results
        else:
            results["sizing"] = {}

        return results

    def run_exit_pnl_analysis(self, position: dict, market_data: dict) -> dict:
        """
        Compute P&L-aware risk context for an open position.

        This is intentionally separate from execution. The result is added to
        the exit LLM payload, while the existing HOLD/COMPLETE flow remains the
        same.
        """
        try:
            return self.pnl_risk.compute(position, market_data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Exit PnL risk analysis failed: {}", exc)
            return {}
