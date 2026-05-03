"""
app/calculator/risk_calculator.py

RiskCalculator — computes entry risk metrics (Stop-Loss, Take-Profit, RR).

Design rules:
  - Takes latest_price and ATR (from IndicatorCalculator).
  - Uses multipliers from config/strategy_params.py.
  - Returns a dict of risk parameters.
"""

from __future__ import annotations

from app.utils.safe_number import safe_float
from config.strategy_params import STOP_LOSS_ATR_MULT, TAKE_PROFIT_ATR_MULT


class RiskCalculator:
    """
    Computes SL/TP levels and Risk-to-Reward ratios.
    """

    def compute_risk_levels(
        self, 
        side: str, 
        entry_price: float, 
        atr: float | None
    ) -> dict:
        """
        Compute SL and TP prices based on ATR.
        """
        if not entry_price or not atr or entry_price <= 0 or atr <= 0:
            return {}

        if side.upper() == "BUY":
            sl_price = entry_price - (atr * STOP_LOSS_ATR_MULT)
            tp_price = entry_price + (atr * TAKE_PROFIT_ATR_MULT)
        else:
            # Short side (if ever implemented)
            sl_price = entry_price + (atr * STOP_LOSS_ATR_MULT)
            tp_price = entry_price - (atr * TAKE_PROFIT_ATR_MULT)

        risk_amount = abs(entry_price - sl_price)
        reward_amount = abs(tp_price - entry_price)
        rr_ratio = reward_amount / risk_amount if risk_amount > 0 else 0.0

        return {
            "stop_loss": round(sl_price, 2),
            "take_profit": round(tp_price, 2),
            "risk_amount": round(risk_amount, 2),
            "reward_amount": round(reward_amount, 2),
            "rr_ratio": round(rr_ratio, 2),
        }
