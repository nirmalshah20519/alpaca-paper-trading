"""
app/datasource/alpaca_gateway.py

AlpacaGateway — single object responsible for creating all Alpaca clients.

Design rules (plan §11.1):
  - Selects paper or live trading client based on trading_mode.
  - Creates stock and crypto data clients.
  - Never exposes API keys in logs or repr.
  - Provides clients to datasource services (dependency injection).
"""

from __future__ import annotations

from alpaca.trading.client import TradingClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.historical.crypto import CryptoHistoricalDataClient

from app.utils.logger import logger


class AlpacaGateway:
    """
    Creates and owns the Alpaca SDK client instances.

    Parameters
    ----------
    api_key : str
        Alpaca API key. Never logged.
    api_secret : str
        Alpaca API secret. Never logged.
    trading_mode : str
        'PAPER' or 'REAL'. Determines whether a paper or live TradingClient
        is created.
    """

    def __init__(self, api_key: str, api_secret: str, trading_mode: str) -> None:
        self._api_key = api_key        # NEVER log
        self._api_secret = api_secret  # NEVER log
        self.trading_mode = trading_mode
        self.is_paper = trading_mode == "PAPER"

        # -----------------------------------------------------------------
        # Trading client (for account, orders, positions)
        # -----------------------------------------------------------------
        self.trading_client = TradingClient(
            api_key=api_key,
            secret_key=api_secret,
            paper=self.is_paper,
        )

        # -----------------------------------------------------------------
        # Market data clients
        # -----------------------------------------------------------------
        self.stock_data_client = StockHistoricalDataClient(
            api_key=api_key,
            secret_key=api_secret,
        )

        self.crypto_data_client = CryptoHistoricalDataClient(
            api_key=api_key,
            secret_key=api_secret,
        )

        logger.info(
            "AlpacaGateway initialised — mode={} paper={}",
            self.trading_mode,
            self.is_paper,
        )

    def __repr__(self) -> str:
        return f"AlpacaGateway(mode={self.trading_mode!r}, paper={self.is_paper})"
