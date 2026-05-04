"""
tests/test_dashboard.py

Dashboard API contract tests.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import app.dashboard.server as dashboard


class FakeStorage:
    def get_recent_signals(self, limit: int = 1000):
        return [
            {"timestamp": "2026-05-05T00:00:00+00:00", "symbol": "AAPL", "action": "SKIP"},
            {"timestamp": "2026-05-05T00:01:00+00:00", "symbol": "AAPL", "action": "BUY"},
            {"timestamp": "2026-05-05T00:02:00+00:00", "symbol": "BTC/USD", "action": "SELL"},
        ]


class FakeState:
    service_start_utc = "2026-05-05T00:00:00+00:00"
    last_asset_refresh_utc = "2026-05-05T00:00:00+00:00"

    def is_paused(self):
        return False

    def get_active_assets(self):
        return ["AAPL", "BTC/USD"]

    def get_account_data(self):
        return {}

    def get_positions(self):
        return []


class FakeAccountService:
    def get_account_snapshot(self):
        return {"equity": 1000.0, "portfolio_value": 1000.0, "buying_power": 500.0}

    def get_positions(self):
        return [{"symbol": "AAPL", "market_value": 250.0, "qty": 2}]

    def get_open_orders(self):
        return [{"symbol": "BTC/USD", "status": "new"}]

    def get_today_orders(self):
        return [{"symbol": "AAPL", "status": "filled"}]


def test_dashboard_endpoint_returns_latest_signal_per_symbol():
    dashboard._storage = FakeStorage()
    dashboard._state = FakeState()
    dashboard._account_service = FakeAccountService()
    dashboard._dashboard_cache = None
    dashboard._dashboard_cache_at = 0.0

    client = TestClient(dashboard.app)
    response = client.get("/api/dashboard")

    assert response.status_code == 200
    payload = response.json()
    signals = payload["signals"]

    assert len(signals) == 2
    assert signals[0]["symbol"] == "BTC/USD"
    assert signals[1]["symbol"] == "AAPL"
    assert signals[1]["action"] == "BUY"
    assert payload["positions"][0]["symbol"] == "AAPL"
    assert payload["open_orders"][0]["symbol"] == "BTC/USD"
    assert payload["order_history_today"][0]["status"] == "filled"
    assert payload["holdings"][0]["allocation_pct"] == 25.0
