"""Market data service for strategy-safe contexts."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from alpaca.data.timeframe import TimeFrame

from app.broker.market_data_adapter import AlpacaMarketDataAdapter
from app.core.trading import OhlcvBar, StrategyMarketContext, SymbolMarketContext
from app.market_data.indicators import ema, rsi, volatility_pct


class MarketDataService:
    """Broker-isolated market data service."""

    def __init__(self, adapter: AlpacaMarketDataAdapter) -> None:
        self._adapter = adapter

    async def build_market_context(
        self,
        symbols: list[str],
        *,
        timeframe: TimeFrame = TimeFrame.Minute,
        limit: int = 50,
    ) -> StrategyMarketContext:
        """Fetch bars and return strategy-safe market context."""
        raw = await self._adapter.get_bars(symbols, timeframe=timeframe, limit=limit)
        contexts: dict[str, SymbolMarketContext] = {}
        for symbol in symbols:
            symbol_bars = [self._normalize_bar(item) for item in raw.get(symbol, [])]
            closes = [bar.close for bar in symbol_bars]
            latest_price = closes[-1] if closes else Decimal("0")
            contexts[symbol] = SymbolMarketContext(
                symbol=symbol,
                bars=symbol_bars,
                latest_price=latest_price,
                ema_fast=ema(closes, 9),
                ema_slow=ema(closes, 21),
                rsi=rsi(closes, 14),
                volatility_pct=volatility_pct(closes, 10),
            )
        return StrategyMarketContext(symbols=contexts)

    @staticmethod
    def _normalize_bar(raw_bar: Any) -> OhlcvBar:
        """Normalize Alpaca bar objects into typed bars."""
        timestamp = getattr(raw_bar, "timestamp", None) or raw_bar.get("timestamp")
        open_price = getattr(raw_bar, "open", None) or raw_bar.get("open")
        high = getattr(raw_bar, "high", None) or raw_bar.get("high")
        low = getattr(raw_bar, "low", None) or raw_bar.get("low")
        close = getattr(raw_bar, "close", None) or raw_bar.get("close")
        volume = getattr(raw_bar, "volume", None) or raw_bar.get("volume")
        return OhlcvBar(
            timestamp=timestamp,
            open=Decimal(str(open_price)),
            high=Decimal(str(high)),
            low=Decimal(str(low)),
            close=Decimal(str(close)),
            volume=Decimal(str(volume)),
        )
