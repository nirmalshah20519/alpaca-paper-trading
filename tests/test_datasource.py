"""
tests/test_datasource.py

Tests for Phase 3: Alpaca Datasource integration.
Uses mocking to avoid real API calls.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pandas as pd
from datetime import datetime, timezone, timedelta

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

    def test_get_latest_quote_supports_sdk_data_mapping(self, mock_gateway):
        service = AlpacaMarketDataService(mock_gateway)

        mock_quote = MagicMock()
        mock_quote.bid_price = 149.90
        mock_quote.ask_price = 150.00
        mock_response = MagicMock()
        mock_response.data = {"AAPL": mock_quote}
        mock_gateway.stock_data_client.get_stock_latest_quote.return_value = mock_response

        quote = service.get_latest_quote("AAPL")

        assert quote["bid"] == 149.90
        assert quote["ask"] == 150.00
        assert quote["spread"] == pytest.approx(0.10)
        assert quote["spread_pct"] == pytest.approx(0.10 / 150.00)

    def test_get_latest_quote_matches_crypto_data_mapping_without_slash(self, mock_gateway):
        service = AlpacaMarketDataService(mock_gateway)

        mock_response = MagicMock()
        mock_response.data = {"BTCUSD": {"bid_price": 60000.0, "ask_price": 60006.0}}
        mock_gateway.crypto_data_client.get_crypto_latest_quote.return_value = mock_response

        quote = service.get_latest_quote("BTC/USD")

        assert quote["bid"] == 60000.0
        assert quote["ask"] == 60006.0

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
        mock_gateway.crypto_data_client.get_crypto_bars.return_value.data = {}
        
        # Should return first N from default universe (Crypto + Stock)
        top_n = service.get_top_n_assets(5)
        assert len(top_n) == 5
        from config.settings import DEFAULT_STOCK_UNIVERSE, DEFAULT_CRYPTO_UNIVERSE
        combined = list(DEFAULT_CRYPTO_UNIVERSE) + list(DEFAULT_STOCK_UNIVERSE)
        assert top_n == combined[:5]

    def test_asset_selector_discovers_crypto_to_fill_top_25_when_market_closed(self, mock_gateway):
        service = AlpacaAssetSelector(mock_gateway)
        mock_gateway.trading_client.get_clock.return_value = SimpleNamespace(is_open=False)
        mock_gateway.trading_client.get_all_assets.return_value = [
            SimpleNamespace(symbol=f"TOKEN{i}/USD", asset_class="crypto", tradable=True, status="active")
            for i in range(20)
        ]

        with patch.object(service, "_compute_ranked_candidates", return_value=(pd.DataFrame(), pd.DataFrame())):
            top_n = service.get_top_n_assets(25)

        assert len(top_n) == 25
        assert "BTC/USD" in top_n
        assert "TOKEN14/USD" in top_n

    def test_asset_selector_uses_dynamic_stocks_when_market_open(self, mock_gateway):
        service = AlpacaAssetSelector(mock_gateway)
        mock_gateway.trading_client.get_clock.return_value = SimpleNamespace(is_open=True)
        mock_gateway.trading_client.get_all_assets.return_value = [
            SimpleNamespace(symbol="ZXZZ", asset_class="us_equity", tradable=True, status="active"),
            SimpleNamespace(symbol="QWQQ", asset_class="us_equity", tradable=True, status="active"),
        ]

        with patch.object(service, "_compute_ranked_candidates", return_value=(pd.DataFrame(), pd.DataFrame())):
            top_n = service.get_top_n_assets(60)

        assert "ZXZZ" in top_n
        assert "QWQQ" in top_n

    def test_asset_selector_scores_trade_opportunity_above_flat_symbol(self, mock_gateway):
        service = AlpacaAssetSelector(mock_gateway)
        moving = _daily_bars(
            closes=[
                100, 101, 100.5, 102, 101.8, 103, 102.7, 104, 103.8, 105,
                104.6, 106, 105.5, 107, 106.4, 108, 107.2, 109, 108.1, 110,
            ],
            volumes=[
                1_000_000, 1_050_000, 1_025_000, 1_100_000, 1_080_000,
                1_150_000, 1_120_000, 1_200_000, 1_180_000, 1_220_000,
                2_000_000, 2_300_000, 2_500_000, 2_700_000, 3_000_000,
                3_200_000, 3_500_000, 3_700_000, 4_000_000, 4_300_000,
            ],
        )
        flat = _daily_bars(
            closes=[
                100, 100.1, 99.9, 100.0, 100.1, 100.0, 99.9, 100.0, 100.1, 100.0,
                99.9, 100.0, 100.1, 100.0, 99.9, 100.0, 100.1, 100.0, 99.9, 100.0,
            ],
            volumes=[1_500_000] * 20,
        )

        with patch.object(service, "_fetch_stock_bars", return_value={"MOVING": moving, "FLAT": flat}), \
             patch.object(service, "_fetch_crypto_bars", return_value={}), \
             patch.object(service, "_fetch_stock_quotes", return_value=_quotes("MOVING", "FLAT")), \
             patch.object(service, "_fetch_crypto_quotes", return_value={}):
            scores = service._compute_scores(["MOVING", "FLAT"])

        assert scores.loc["MOVING", "score"] > scores.loc["FLAT", "score"]

    def test_asset_selector_filters_stock_above_effective_trade_budget(self, mock_gateway):
        service = AlpacaAssetSelector(mock_gateway)
        affordable = _daily_bars(closes=[50 + i for i in range(20)], volumes=[2_000_000] * 20)
        expensive = _daily_bars(closes=[450 + i for i in range(20)], volumes=[5_000_000] * 20)

        with patch.object(service, "_fetch_stock_bars", return_value={
            "AFFORD": affordable,
            "EXPENSIVE": expensive,
        }), patch.object(service, "_fetch_crypto_bars", return_value={}), \
             patch.object(service, "_fetch_stock_quotes", return_value=_quotes("AFFORD", "EXPENSIVE")), \
             patch.object(service, "_fetch_crypto_quotes", return_value={}):
            scores = service._compute_scores(
                ["AFFORD", "EXPENSIVE"],
                {"buying_power": 100.0, "trade_budget": 100.0},
            )

        assert "AFFORD" in scores.index
        assert "EXPENSIVE" in scores.index
        assert scores.loc["AFFORD", "tradable_qty"] > scores.loc["EXPENSIVE", "tradable_qty"]

    def test_asset_selector_allows_fractional_crypto_when_balance_supports_min_lot(self, mock_gateway):
        service = AlpacaAssetSelector(mock_gateway)
        btc = _daily_bars(closes=[50_000 + (i * 100) for i in range(20)], volumes=[100] * 20)

        with patch.object(service, "_fetch_stock_bars", return_value={}), \
             patch.object(service, "_fetch_crypto_bars", return_value={"BTC/USD": btc}), \
             patch.object(service, "_fetch_stock_quotes", return_value={}), \
             patch.object(service, "_fetch_crypto_quotes", return_value=_quotes("BTC/USD", spread_pct=0.001)):
            tradable = service._compute_scores(
                ["BTC/USD"],
                {"buying_power": 20.0, "trade_budget": 20.0},
            )
            not_tradable = service._compute_scores(
                ["BTC/USD"],
                {"buying_power": 1.0, "trade_budget": 1.0},
            )

        assert "BTC/USD" in tradable.index
        assert tradable.loc["BTC/USD", "tradable_qty"] >= 0.0001
        assert not_tradable.empty

    def test_asset_selector_filters_low_liquidity_crypto_before_ranking(self, mock_gateway):
        service = AlpacaAssetSelector(mock_gateway)
        thin = _daily_bars(closes=[10 + i for i in range(20)], volumes=[1] * 20)

        with patch.object(service, "_fetch_stock_bars", return_value={}), \
             patch.object(service, "_fetch_crypto_bars", return_value={"THIN/USD": thin}), \
             patch.object(service, "_fetch_stock_quotes", return_value={}), \
             patch.object(service, "_fetch_crypto_quotes", return_value=_quotes("THIN/USD", spread_pct=0.001)):
            scores = service._compute_scores(["THIN/USD"], {"buying_power": 200.0, "trade_budget": 200.0})

        assert scores.empty

    def test_asset_selector_filters_wide_spread_before_ranking(self, mock_gateway):
        service = AlpacaAssetSelector(mock_gateway)
        bars = _daily_bars(closes=[50_000 + (i * 100) for i in range(20)], volumes=[100] * 20)

        with patch.object(service, "_fetch_stock_bars", return_value={}), \
             patch.object(service, "_fetch_crypto_bars", return_value={"BTC/USD": bars}), \
             patch.object(service, "_fetch_stock_quotes", return_value={}), \
             patch.object(service, "_fetch_crypto_quotes", return_value=_quotes("BTC/USD", spread_pct=0.02)):
            scores = service._compute_scores(["BTC/USD"], {"buying_power": 200.0, "trade_budget": 200.0})

        assert scores.empty


def _daily_bars(closes: list[float], volumes: list[float]) -> pd.DataFrame:
    dates = [datetime(2026, 5, 1, tzinfo=timezone.utc) + timedelta(days=i) for i in range(len(closes))]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [close * 1.01 for close in closes],
            "low": [close * 0.99 for close in closes],
            "close": closes,
            "volume": volumes,
        },
        index=dates,
    )


def _quotes(*symbols: str, spread_pct: float = 0.001) -> dict[str, dict]:
    return {symbol: {"spread_pct": spread_pct} for symbol in symbols}
