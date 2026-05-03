"""
tests/test_datasource.py

Tests for Phase 3: Alpaca Datasource integration.
Uses mocking to avoid real API calls.
"""

import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
from datetime import datetime, timezone

from app.datasource.alpaca_gateway import AlpacaGateway
from app.datasource.market_data_service import AlpacaMarketDataService
from app.datasource.account_service import AlpacaAccountService
from app.datasource.asset_selector import AlpacaAssetSelector


@pytest.fixture
def mock_gateway():
    """Provides a gateway with mocked Alpaca clients."""
    with patch("app.datasource.alpaca_gateway.TradingClient"), \
         patch("app.datasource.alpaca_gateway.StockHistoricalDataClient"), \
         patch("app.datasource.alpaca_gateway.CryptoHistoricalDataClient"):
        
        gateway = AlpacaGateway("key", "secret", "PAPER")
        return gateway


class TestAlpacaMarketDataService:
    def test_get_latest_price_success(self, mock_gateway):
        service = AlpacaMarketDataService(mock_gateway)
        
        # Mock the SDK response
        mock_trade = MagicMock()
        mock_trade.price = 150.25
        mock_gateway.stock_data_client.get_stock_latest_trade.return_value = {
            "AAPL": mock_trade
        }
        
        price = service.get_latest_price("AAPL")
        assert price == 150.25
        mock_gateway.stock_data_client.get_stock_latest_trade.assert_called_once()

    def test_get_bars_success(self, mock_gateway):
        service = AlpacaMarketDataService(mock_gateway)
        
        # Mock Bar data
        mock_bar = MagicMock()
        mock_bar.timestamp = datetime(2023, 1, 1, tzinfo=timezone.utc)
        mock_bar.open = 100.0
        mock_bar.high = 110.0
        mock_bar.low = 90.0
        mock_bar.close = 105.0
        mock_bar.volume = 1000
        mock_bar.vwap = 102.0
        
        mock_gateway.stock_data_client.get_stock_bars.return_value.data = {
            "AAPL": [mock_bar]
        }
        
        df = service.get_bars("AAPL", "1Day", 1)
        assert not df.empty
        assert df.iloc[0]["close"] == 105.0
        assert df.index[0] == mock_bar.timestamp


class TestAlpacaAccountService:
    def test_get_account_snapshot(self, mock_gateway):
        service = AlpacaAccountService(mock_gateway)
        
        mock_acc = MagicMock()
        mock_acc.equity = "100000.0"
        mock_acc.cash = "50000.0"
        mock_acc.buying_power = "200000.0"
        mock_acc.portfolio_value = "100000.0"
        mock_acc.trading_blocked = False
        mock_acc.account_blocked = False
        mock_acc.status = MagicMock()
        mock_acc.status.value = "ACTIVE"
        
        mock_gateway.trading_client.get_account.return_value = mock_acc
        
        snapshot = service.get_account_snapshot()
        assert snapshot["equity"] == 100000.0
        assert snapshot["status"] == "ACTIVE"


class TestAlpacaAssetSelector:
    def test_get_top_n_assets_fallback_on_empty(self, mock_gateway):
        service = AlpacaAssetSelector(mock_gateway)
        
        # Mock empty bars response
        mock_gateway.stock_data_client.get_stock_bars.return_value.data = {}
        
        # Should return first N from default universe (Crypto + Stock)
        top_n = service.get_top_n_assets(5)
        assert len(top_n) == 5
        from config.settings import DEFAULT_STOCK_UNIVERSE, DEFAULT_CRYPTO_UNIVERSE
        combined = list(DEFAULT_CRYPTO_UNIVERSE) + list(DEFAULT_STOCK_UNIVERSE)
        assert top_n == combined[:5]
