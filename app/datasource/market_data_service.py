"""
app/datasource/market_data_service.py

AlpacaMarketDataService — unified service for Stocks and Crypto.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
import pandas as pd
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

from alpaca.data.requests import (
    StockBarsRequest, StockLatestQuoteRequest, StockLatestTradeRequest,
    CryptoBarsRequest, CryptoLatestQuoteRequest, CryptoLatestTradeRequest
)
from alpaca.data.timeframe import TimeFrame

from app.datasource.alpaca_gateway import AlpacaGateway
from app.utils.logger import logger
from app.utils.time_utils import utc_now
from app.utils.safe_number import safe_float
from config.strategy_params import BARS_TIMEFRAME, BARS_LOOKBACK


class BaseMarketDataService(ABC):
    @abstractmethod
    def get_latest_price(self, symbol: str) -> float | None: pass
    @abstractmethod
    def get_latest_quote(self, symbol: str) -> dict: pass
    @abstractmethod
    def get_bars(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame: pass
    @abstractmethod
    def fetch_required_entry_data(self, symbol: str) -> dict: pass
    @abstractmethod
    def fetch_required_exit_data(self, symbol: str) -> dict: pass


class AlpacaMarketDataService(BaseMarketDataService):
    CRYPTO_BASES: frozenset[str] = frozenset(
        {"BTC", "ETH", "SOL", "DOGE", "SHIB", "LTC", "BCH", "LINK", "AVAX", "UNI"}
    )

    def __init__(self, gateway: AlpacaGateway) -> None:
        self._stock_client = gateway.stock_data_client
        self._crypto_client = gateway.crypto_data_client

    def _is_crypto(self, symbol: str) -> bool:
        symbol = str(symbol).upper()
        if "/" in symbol:
            return True
        if symbol.endswith("USDT"):
            return symbol[:-4] in self.CRYPTO_BASES
        if symbol.endswith("USD"):
            return symbol[:-3] in self.CRYPTO_BASES
        return False

    def _normalize_symbol(self, symbol: str) -> str:
        """Injects slash into crypto symbols if missing (e.g. BTCUSD -> BTC/USD)."""
        symbol = str(symbol).upper()
        if "/" in symbol:
            return symbol
        if symbol.endswith("USDT") and symbol[:-4] in self.CRYPTO_BASES:
            return f"{symbol[:-4]}/USDT"
        if symbol.endswith("USD") and symbol[:-3] in self.CRYPTO_BASES:
            return f"{symbol[:-3]}/USD"
        return symbol

    def get_latest_price(self, symbol: str) -> float | None:
        try:
            symbol = self._normalize_symbol(symbol)
            if self._is_crypto(symbol):
                req = CryptoLatestTradeRequest(symbol_or_symbols=symbol)
                res = self._crypto_client.get_crypto_latest_trade(req)
            else:
                req = StockLatestTradeRequest(symbol_or_symbols=symbol)
                res = self._stock_client.get_stock_latest_trade(req)
            
            # alpaca-py responses typically have a .data attribute mapping symbol to trade
            data = res.data if hasattr(res, "data") else res
            trade = data.get(symbol) if isinstance(data, dict) else data
            
            if trade and hasattr(trade, "price"):
                return safe_float(trade.price)
            return None
        except Exception as exc:
            logger.warning("get_latest_price failed for {}: {}", symbol, exc)
            return None

    def get_latest_quote(self, symbol: str) -> dict:
        try:
            symbol = self._normalize_symbol(symbol)
            if self._is_crypto(symbol):
                req = CryptoLatestQuoteRequest(symbol_or_symbols=symbol)
                res = self._crypto_client.get_crypto_latest_quote(req)
            else:
                req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
                res = self._stock_client.get_stock_latest_quote(req)
            
            quote = res.get(symbol) if isinstance(res, dict) else res
            if not quote: return {}
            
            bid = safe_float(quote.bid_price) or 0.0
            ask = safe_float(quote.ask_price) or 0.0
            spread = max(ask - bid, 0.0)
            return {"bid": bid, "ask": ask, "spread": spread, "spread_pct": (spread / ask) if ask > 0 else 0.0}
        except Exception as exc:
            logger.warning("get_latest_quote failed for {}: {}", symbol, exc)
            return {}

    def get_bars(self, symbol: str, timeframe: str = BARS_TIMEFRAME, limit: int = BARS_LOOKBACK) -> pd.DataFrame:
        try:
            symbol = self._normalize_symbol(symbol)
            tf = self._parse_timeframe(timeframe)
            start = datetime.now(tz=timezone.utc) - timedelta(days=5)
            
            if self._is_crypto(symbol):
                req = CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start)
                res = self._crypto_client.get_crypto_bars(req)
            else:
                req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start, limit=limit)
                res = self._stock_client.get_stock_bars(req)
            
            bar_list = res.data.get(symbol, []) if hasattr(res, "data") else []
            if not bar_list: return pd.DataFrame()
            
            df = pd.DataFrame([{
                "timestamp": b.timestamp, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume, "vwap": getattr(b, "vwap", None)
            } for b in bar_list]).set_index("timestamp")
            df.index = pd.to_datetime(df.index, utc=True)
            return df
        except Exception as exc:
            logger.warning("get_bars failed for {}: {}", symbol, exc)
            return pd.DataFrame()

    def fetch_required_entry_data(self, symbol: str) -> dict:
        result = {"symbol": symbol, "fetched_at": utc_now()}
        result["latest_price"] = self.get_latest_price(symbol)
        result.update(self.get_latest_quote(symbol))
        result["bars"] = self.get_bars(symbol)
        return result

    def fetch_required_exit_data(self, symbol: str) -> dict:
        return {"symbol": symbol, "latest_price": self.get_latest_price(symbol), "bars": self.get_bars(symbol, limit=60)}

    def _parse_timeframe(self, tf_str: str) -> TimeFrame:
        return {"1Min": TimeFrame.Minute, "5Min": TimeFrame(5, "Minute"), "1Hour": TimeFrame.Hour, "1Day": TimeFrame.Day}.get(tf_str, TimeFrame.Minute)
