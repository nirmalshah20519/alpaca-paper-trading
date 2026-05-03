"""
app/datasource/asset_selector.py

AssetSelector — scores stocks and crypto based on market status.

Logic:
  - When market is open: US_EQUITY + CRYPTO (Total Top 20).
  - When market is closed: CRYPTO only (Top 20).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

from app.datasource.alpaca_gateway import AlpacaGateway
from app.utils.logger import logger
from app.utils.safe_number import safe_float
from config.settings import (
    DEFAULT_STOCK_UNIVERSE,
    DEFAULT_CRYPTO_UNIVERSE,
    ASSET_SELECTOR_TOP_N,
    SCORE_WEIGHT_VOLUME,
    SCORE_WEIGHT_MOMENTUM,
    SCORE_WEIGHT_VOLATILITY_EXPANSION,
    SCORE_WEIGHT_DOLLAR_VOLUME,
    SCORE_WEIGHT_TREND_STRENGTH,
)


class BaseAssetSelector(ABC):
    @abstractmethod
    def get_top_n_assets(self, n: int) -> list[str]:
        pass


class AlpacaAssetSelector(BaseAssetSelector):
    """
    Unified selector for Stocks and Crypto.
    """

    def __init__(self, gateway: AlpacaGateway) -> None:
        self._stock_client = gateway.stock_data_client
        self._crypto_client = gateway.crypto_data_client
        self._trading_client = gateway.trading_client
        self._last_top_n: list[str] = []

    def get_top_n_assets(self, n: int = ASSET_SELECTOR_TOP_N) -> list[str]:
        try:
            # 1. Check if market is open
            clock = self._trading_client.get_clock()
            is_open = clock.is_open
            
            universe = list(DEFAULT_CRYPTO_UNIVERSE)
            if is_open:
                logger.info("Market is OPEN. Scoring Stocks + Crypto.")
                universe += DEFAULT_STOCK_UNIVERSE
            else:
                logger.info("Market is CLOSED. Scoring Crypto ONLY.")
            
            # 2. Compute Scores
            df_scores = self._compute_scores(universe)
            if df_scores.empty:
                return self._fallback(n, universe)

            top_n = (
                df_scores
                .sort_values("score", ascending=False)
                .head(n)
                .index.tolist()
            )
            self._last_top_n = top_n
            logger.info("AssetSelector: top {} selected: {}", n, top_n)
            return top_n

        except Exception as exc:  # noqa: BLE001
            logger.error("AssetSelector failed: {}. Using fallback.", exc)
            return self._fallback(n, DEFAULT_CRYPTO_UNIVERSE)

    def _compute_scores(self, universe: list[str]) -> pd.DataFrame:
        stocks = [s for s in universe if "/" not in s]
        cryptos = [s for s in universe if "/" in s]
        
        bars_map = {}
        if stocks:
            bars_map.update(self._fetch_stock_bars(stocks, days=10))
        if cryptos:
            bars_map.update(self._fetch_crypto_bars(cryptos, days=10))
            
        if not bars_map:
            return pd.DataFrame()

        rows = []
        for symbol, df in bars_map.items():
            if df.empty or len(df) < 2:
                continue
            row = self._compute_symbol_metrics(symbol, df)
            if row:
                rows.append(row)

        if not rows:
            return pd.DataFrame()

        metrics = pd.DataFrame(rows).set_index("symbol")
        for col in ["recent_volume", "price_momentum", "vol_expansion", "dollar_volume", "trend_strength"]:
            col_min = metrics[col].min()
            col_max = metrics[col].max()
            denom = col_max - col_min
            metrics[f"{col}_n"] = (metrics[col] - col_min) / denom if denom > 0 else 0.5

        metrics["score"] = (
            SCORE_WEIGHT_VOLUME             * metrics["recent_volume_n"]
            + SCORE_WEIGHT_MOMENTUM         * metrics["price_momentum_n"]
            + SCORE_WEIGHT_VOLATILITY_EXPANSION * metrics["vol_expansion_n"]
            + SCORE_WEIGHT_DOLLAR_VOLUME    * metrics["dollar_volume_n"]
            + SCORE_WEIGHT_TREND_STRENGTH   * metrics["trend_strength_n"]
        )
        return metrics[["score"]]

    def _compute_symbol_metrics(self, symbol: str, df: pd.DataFrame) -> dict | None:
        try:
            closes = df["close"].astype(float)
            volumes = df["volume"].astype(float)
            recent_volume = safe_float(volumes.iloc[-1], 0.0)
            
            price_momentum = (closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0] if len(closes) >= 2 else 0.0
            
            returns = closes.pct_change().dropna()
            if len(returns) >= 4:
                half = len(returns) // 2
                vol_recent = returns.iloc[half:].std()
                vol_prior  = returns.iloc[:half].std()
                vol_expansion = (vol_recent / vol_prior) if vol_prior > 0 else 1.0
            else:
                vol_expansion = 1.0

            dollar_volume = closes.iloc[-1] * volumes.iloc[-1]
            trend_strength = float((returns > 0).sum()) / len(returns) if len(returns) > 0 else 0.5

            return {
                "symbol": symbol,
                "recent_volume": recent_volume,
                "price_momentum": price_momentum,
                "vol_expansion": vol_expansion,
                "dollar_volume": dollar_volume,
                "trend_strength": trend_strength,
            }
        except: return None

    @retry(wait=wait_exponential(min=2, max=30), stop=stop_after_attempt(3), reraise=True)
    def _fetch_stock_bars(self, symbols: list[str], days: int) -> dict[str, pd.DataFrame]:
        start = datetime.now(tz=timezone.utc) - timedelta(days=days + 5)
        req = StockBarsRequest(symbol_or_symbols=symbols, timeframe=TimeFrame.Day, start=start, limit=days + 5)
        res = self._stock_client.get_stock_bars(req)
        return self._parse_barset(res, symbols)

    @retry(wait=wait_exponential(min=2, max=30), stop=stop_after_attempt(3), reraise=True)
    def _fetch_crypto_bars(self, symbols: list[str], days: int) -> dict[str, pd.DataFrame]:
        start = datetime.now(tz=timezone.utc) - timedelta(days=days + 5)
        req = CryptoBarsRequest(symbol_or_symbols=symbols, timeframe=TimeFrame.Day, start=start)
        res = self._crypto_client.get_crypto_bars(req)
        return self._parse_barset(res, symbols)

    def _parse_barset(self, bars_result, symbols: list[str]) -> dict[str, pd.DataFrame]:
        result: dict[str, pd.DataFrame] = {}
        data = bars_result.data if hasattr(bars_result, "data") else {}
        for sym in symbols:
            bar_list = data.get(sym, [])
            if not bar_list:
                continue
            records = [
                {
                    "timestamp": b.timestamp,
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": float(b.close),
                    "volume": float(b.volume),
                }
                for b in bar_list
            ]
            df = pd.DataFrame(records)
            if not df.empty:
                df.set_index("timestamp", inplace=True)
                df.index = pd.to_datetime(df.index, utc=True)
                result[sym] = df.sort_index()
        return result

    def _fallback(self, n: int, universe: list[str]) -> list[str]:
        if self._last_top_n: return self._last_top_n[:n]
        return universe[:n]
