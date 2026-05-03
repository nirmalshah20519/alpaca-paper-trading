"""
app/calculator/position_sizer.py

PositionSizer — computes how many shares to buy based on risk limits.

Design rules:
  - Takes account equity (from AppState/AccountService).
  - Uses MAX_RISK_PER_TRADE_PCT from config/risk_limits.py.
  - Returns {qty, dollar_amount}.
"""

from __future__ import annotations

from config.risk_limits import MAX_RISK_PER_TRADE_PCT, MAX_POSITION_PCT_OF_EQUITY


class PositionSizer:
    """
    Computes position size based on account equity and risk parameters.
    """

    def compute_size(
        self, 
        equity: float, 
        entry_price: float, 
        stop_loss_price: float
    ) -> dict:
        """
        Risk-based sizing:
        risk_per_trade = equity * MAX_RISK_PER_TRADE_PCT
        risk_per_share = |entry_price - stop_loss_price|
        qty = risk_per_trade / risk_per_share
        
        Also capped by MAX_POSITION_PCT_OF_EQUITY (e.g. 5% of equity).
        """
        if equity <= 0 or entry_price <= 0 or stop_loss_price <= 0:
            return {"qty": 0.0, "dollar_amount": 0.0}

        risk_per_share = abs(entry_price - stop_loss_price)
        if risk_per_share <= 0:
            return {"qty": 0.0, "dollar_amount": 0.0}

        # 1. Size based on risk (Stop Loss distance)
        risk_budget = equity * MAX_RISK_PER_TRADE_PCT
        qty_by_risk = risk_budget / risk_per_share

        # 2. Size based on total capital cap (e.g. don't put 50% equity in one trade)
        max_capital_budget = equity * MAX_POSITION_PCT_OF_EQUITY
        qty_by_capital = max_capital_budget / entry_price

        # Take the smaller of the two
        qty = min(qty_by_risk, qty_by_capital)
        
        # Round down to 2 decimals for fractional shares (or integer if preferred)
        qty = round(qty, 2)
        dollar_amount = round(qty * entry_price, 2)

        return {
            "qty": qty,
            "dollar_amount": dollar_amount,
            "risk_budget": round(risk_budget, 2),
            "capital_budget": round(max_capital_budget, 2)
        }
