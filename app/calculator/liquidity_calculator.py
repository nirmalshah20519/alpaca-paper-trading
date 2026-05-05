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
from config.risk_limits import (
    MAX_SPREAD_PCT,
    MAX_CRYPTO_SPREAD_PCT,
    MIN_AVG_DAILY_VOLUME,
    MIN_CRYPTO_DAILY_DOLLAR_VOLUME,
)
from app.core.dynamic_risk import dynamic_crypto_liquidity_floor, dynamic_stock_liquidity_floor
from app.utils.safe_number import safe_float


class LiquidityCalculator:
    """
    Validates market liquidity before trade entry.
    """

    def check_liquidity(self, quote: dict, bars: pd.DataFrame, account_data: dict | None = None) -> dict:
        """
        Returns {'is_liquid': bool, 'reason': str, 'spread_pct': float, 'avg_daily_volume': float}
        """
        spread_pct = safe_float(quote.get("spread_pct"))
        avg_daily_volume = self._avg_daily_volume(bars)
        avg_daily_dollar_volume = self._avg_daily_dollar_volume(bars)
        is_crypto = self._is_crypto_symbol(str(quote.get("symbol") or ""))
        max_spread_pct = MAX_CRYPTO_SPREAD_PCT if is_crypto else MAX_SPREAD_PCT

        is_liquid = True
        reason = ""

        if spread_pct is None:
            is_liquid = False
            reason = "Quote unavailable"
            spread_pct = 1.0
        elif spread_pct > max_spread_pct:
            is_liquid = False
            reason = f"Spread too wide: {spread_pct:.4f} > {max_spread_pct:.4f}"
        
        dynamic_crypto_floor = max(
            dynamic_crypto_liquidity_floor(account_data),
            MIN_CRYPTO_DAILY_DOLLAR_VOLUME * 0.05,
        )
        dynamic_stock_floor = max(
            dynamic_stock_liquidity_floor(account_data),
            MIN_AVG_DAILY_VOLUME * 0.2,
        )

        if is_crypto and avg_daily_dollar_volume < dynamic_crypto_floor:
            is_liquid = False
            reason = f"Crypto dollar volume too low: {avg_daily_dollar_volume:.0f} < {dynamic_crypto_floor:.0f}"
        elif not is_crypto and avg_daily_volume < dynamic_stock_floor:
            is_liquid = False
            reason = f"Daily volume too low: {avg_daily_volume:.0f} < {dynamic_stock_floor:.0f}"

        return {
            "is_liquid": is_liquid,
            "reason": reason,
            "spread_pct": spread_pct,
            "avg_daily_volume": avg_daily_volume,
            "avg_daily_dollar_volume": avg_daily_dollar_volume,
            "avg_volume": avg_daily_volume,
        }

    def _avg_daily_volume(self, bars: pd.DataFrame | None) -> float:
        if bars is None or bars.empty or "volume" not in bars:
            return 0.0

        volumes = pd.to_numeric(bars["volume"], errors="coerce").dropna()
        if volumes.empty:
            return 0.0

        if isinstance(bars.index, pd.DatetimeIndex):
            daily = volumes.groupby(bars.index.date).sum()
            return safe_float(daily.mean(), 0.0) or 0.0

        return safe_float(volumes.sum(), 0.0) or 0.0

    def _avg_daily_dollar_volume(self, bars: pd.DataFrame | None) -> float:
        if bars is None or bars.empty or "volume" not in bars or "close" not in bars:
            return 0.0

        volumes = pd.to_numeric(bars["volume"], errors="coerce")
        closes = pd.to_numeric(bars["close"], errors="coerce")
        dollar_volume = (volumes * closes).dropna()
        if dollar_volume.empty:
            return 0.0

        if isinstance(bars.index, pd.DatetimeIndex):
            daily = dollar_volume.groupby(bars.index.date).sum()
            return safe_float(daily.mean(), 0.0) or 0.0

        return safe_float(dollar_volume.sum(), 0.0) or 0.0

    def _is_crypto_symbol(self, symbol: str) -> bool:
        symbol = symbol.upper()
        return "/" in symbol or symbol.endswith("USD") or symbol.endswith("USDT")
