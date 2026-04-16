"""Market-data wrapper used by internal services instead of direct SDK access."""

from __future__ import annotations

from typing import Any

from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from app.broker.alpaca_client import AlpacaClients, run_sync


class AlpacaMarketDataAdapter:
    """Adapter for fetching normalized equity market data."""

    def __init__(self, clients: AlpacaClients) -> None:
        self._clients = clients

    async def get_bars(
        self,
        symbols: list[str],
        timeframe: TimeFrame = TimeFrame.Minute,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Fetch recent stock bars for a watchlist."""
        request = StockBarsRequest(symbol_or_symbols=symbols, timeframe=timeframe, limit=limit)
        bars = await run_sync(self._clients.market_data.get_stock_bars, request)
        return bars.data
