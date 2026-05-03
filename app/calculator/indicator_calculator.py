"""
app/calculator/indicator_calculator.py

IndicatorCalculator — computes technical indicators from OHLCV bars.

Design rules:
  - Takes a pandas DataFrame (from MarketDataService).
  - Returns a dict of scalar values (the most recent indicator values).
  - Handles empty or short DataFrames gracefully (returns None or default).
  - Never raises — logs and returns partial results.
"""

from __future__ import annotations

import pandas as pd
from app.utils.logger import logger
from app.utils.safe_number import safe_float


class IndicatorCalculator:
    """
    Computes technical indicators for a single symbol.
    """

    def compute_all(self, df: pd.DataFrame) -> dict:
        """
        Compute all indicators and return the latest values.
        """
        if df is None or df.empty or len(df) < 20:
            return {}

        try:
            # Ensure index is sorted
            df = df.sort_index()
            
            results = {
                "sma_20": self._compute_sma(df, 20),
                "sma_50": self._compute_sma(df, 50),
                "rsi_14": self._compute_rsi(df, 14),
                "atr_14": self._compute_atr(df, 14),
                "volatility_20": self._compute_volatility(df, 20),
            }
            return results
        except Exception as exc:  # noqa: BLE001
            logger.error("Indicator computation failed: {}", exc)
            return {}

    def _compute_sma(self, df: pd.DataFrame, period: int) -> float | None:
        if len(df) < period:
            return None
        sma = df["close"].rolling(window=period).mean().iloc[-1]
        return safe_float(sma)

    def _compute_rsi(self, df: pd.DataFrame, period: int) -> float | None:
        if len(df) < period + 1:
            return None
        
        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return safe_float(rsi.iloc[-1])

    def _compute_atr(self, df: pd.DataFrame, period: int) -> float | None:
        """Average True Range."""
        if len(df) < period + 1:
            return None
            
        prev_close = df["close"].shift(1)
        tr1 = df["high"] - df["low"]
        tr2 = (df["high"] - prev_close).abs()
        tr3 = (df["low"] - prev_close).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return safe_float(atr.iloc[-1])

    def _compute_volatility(self, df: pd.DataFrame, period: int) -> float | None:
        """Standard deviation of returns."""
        if len(df) < period:
            return None
        returns = df["close"].pct_change()
        vol = returns.rolling(window=period).std().iloc[-1]
        return safe_float(vol)
