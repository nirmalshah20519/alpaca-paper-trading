"""
app/calculator/liquidity_calculator.py

LiquidityCalculator — checks if a symbol is liquid enough to trade.

Design rules:
  - Checks spread percentage.
  - Checks average daily volume.
  - Returns a simple pass/fail dict with metrics.
"""

from __future__ import annotations

import pandas as pd
from config.risk_limits import MAX_SPREAD_PCT, MIN_AVG_DAILY_VOLUME


class LiquidityCalculator:
    """
    Validates market liquidity before trade entry.
    """

    def check_liquidity(self, quote: dict, bars: pd.DataFrame) -> dict:
        """
        Returns {'is_liquid': bool, 'reason': str, 'spread_pct': float, 'avg_volume': float}
        """
        spread_pct = quote.get("spread_pct", 1.0) # Default to 100% if missing
        
        # Compute avg volume (last 5 bars)
        avg_volume = 0.0
        if bars is not None and not bars.empty:
            avg_volume = bars["volume"].tail(5).mean()

        is_liquid = True
        reason = ""

        if spread_pct > MAX_SPREAD_PCT:
            is_liquid = False
            reason = f"Spread too wide: {spread_pct:.4f}"
        
        if avg_volume < MIN_AVG_DAILY_VOLUME:
            is_liquid = False
            reason = f"Volume too low: {avg_volume:.0f}"

        return {
            "is_liquid": is_liquid,
            "reason": reason,
            "spread_pct": spread_pct,
            "avg_volume": avg_volume
        }
