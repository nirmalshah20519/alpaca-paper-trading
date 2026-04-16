"""Thin service wrappers around Alpaca paper trading clients."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.trading.client import TradingClient
from alpaca.trading.stream import TradingStream

from app.core.config import Settings


@dataclass(slots=True)
class AlpacaClients:
    """Container for the Alpaca SDK clients used by the application."""

    trading: TradingClient
    market_data: StockHistoricalDataClient
    stream: TradingStream


class AlpacaClientFactory:
    """Build paper-only Alpaca SDK clients from typed settings."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create(self) -> AlpacaClients:
        """Instantiate paper-safe Alpaca SDK clients."""
        self._settings.validate_trading_safety()
        api_key = self._settings.alpaca_api_key
        api_secret = self._settings.alpaca_api_secret
        if api_key is None or api_secret is None:
            raise ValueError("Alpaca credentials are required.")

        key = api_key.get_secret_value()
        secret = api_secret.get_secret_value()
        return AlpacaClients(
            trading=TradingClient(api_key=key, secret_key=secret, paper=True),
            market_data=StockHistoricalDataClient(api_key=key, secret_key=secret),
            stream=TradingStream(api_key=key, secret_key=secret, paper=True),
        )


async def run_sync(callable_obj: Any, /, *args: Any, **kwargs: Any) -> Any:
    """Execute a blocking Alpaca SDK call in a worker thread."""
    return await asyncio.to_thread(callable_obj, *args, **kwargs)


async def run_with_retry(
    callable_obj: Any,
    /,
    *args: Any,
    attempts: int = 3,
    timeout_seconds: float = 10.0,
    base_delay_seconds: float = 1.0,
    **kwargs: Any,
) -> Any:
    """Execute a blocking call with timeout and simple exponential backoff."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            async with asyncio.timeout(timeout_seconds):
                return await run_sync(callable_obj, *args, **kwargs)
        except Exception as exc:  # pragma: no cover - exercised indirectly
            last_error = exc
            if attempt == attempts:
                break
            await asyncio.sleep(base_delay_seconds * (2 ** (attempt - 1)))
    assert last_error is not None
    raise last_error
