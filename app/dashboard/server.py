"""
app/dashboard/server.py

DashboardServer — read-only web UI for monitoring the trading service.
Signals are read from local CSV logs. Account-facing dashboard tabs are
fetched directly from Alpaca through AccountService.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from app.core.state import AppState
from app.datasource.account_service import BaseAccountService
from app.storage.storage_manager import StorageManager
from app.utils.logger import logger
from app.utils.time_utils import utc_now

app = FastAPI(title="Alpaca Trading Dashboard")

_storage: StorageManager | None = None
_state: AppState | None = None
_market_data: Any = None
_account_service: BaseAccountService | None = None

_dashboard_cache: dict[str, Any] | None = None
_dashboard_cache_at: float = 0.0
_dashboard_cache_lock = threading.Lock()
_DASHBOARD_CACHE_SECONDS = 1.5


@app.get("/", response_class=HTMLResponse)
async def get_index():
    index_path = Path(__file__).parent / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return "<h1>Dashboard UI file not found</h1>"


@app.get("/api/dashboard")
async def get_dashboard():
    """Return the full dashboard payload with a tiny cache for 2s polling."""
    global _dashboard_cache, _dashboard_cache_at

    if not _storage or not _state:
        return JSONResponse({"error": "Dashboard dependencies not initialized"}, status_code=500)

    now = time.monotonic()
    with _dashboard_cache_lock:
        if _dashboard_cache and now - _dashboard_cache_at < _DASHBOARD_CACHE_SECONDS:
            return _dashboard_cache

    payload = _build_dashboard_payload()

    with _dashboard_cache_lock:
        _dashboard_cache = payload
        _dashboard_cache_at = time.monotonic()

    return payload


@app.get("/api/status")
async def get_status():
    """Compatibility endpoint for older dashboard clients."""
    payload = _build_dashboard_payload()
    return payload["service"]


@app.get("/api/history")
async def get_history():
    """Compatibility endpoint for older dashboard clients."""
    payload = _build_dashboard_payload()
    return {
        "signals": payload["signals"],
        "positions": payload["positions"],
        "open_orders": payload["open_orders"],
        "past_orders": payload["order_history_today"],
    }


def _build_dashboard_payload() -> dict[str, Any]:
    account = _fetch_account_snapshot()
    positions = _fetch_positions()
    open_orders = _fetch_open_orders()
    order_history_today = _fetch_today_orders()
    active_assets = _state.get_active_assets() if _state else []

    return {
        "service": {
            "is_paused": _state.is_paused() if _state else False,
            "active_assets": active_assets,
            "open_orders_count": len(open_orders),
            "positions_count": len(positions),
            "uptime": _state.service_start_utc if _state else "",
            "last_asset_refresh": _state.last_asset_refresh_utc if _state else None,
            "fetched_at": utc_now(),
        },
        "account": account,
        "signals": _latest_signals_by_symbol(active_assets),
        "positions": positions,
        "open_orders": open_orders,
        "order_history_today": order_history_today,
        "holdings": _build_holdings(positions, account),
    }


def _fetch_account_snapshot() -> dict[str, Any]:
    if _account_service:
        account = _account_service.get_account_snapshot()
        if account:
            return account
    return _state.get_account_data() if _state else {}


def _fetch_positions() -> list[dict[str, Any]]:
    if _account_service:
        return _account_service.get_positions()
    return _state.get_positions() if _state else []


def _fetch_open_orders() -> list[dict[str, Any]]:
    if _account_service:
        return _account_service.get_open_orders()
    return _storage.get_open_orders() if _storage else []


def _fetch_today_orders() -> list[dict[str, Any]]:
    if _account_service:
        return _account_service.get_today_orders()
    return _storage.get_recent_past_orders(100) if _storage else []


def _latest_signals_by_symbol(active_assets: list[str]) -> list[dict[str, str]]:
    if not _storage:
        return []

    rows = _storage.get_recent_signals(1000)
    active = set(active_assets)
    latest: dict[str, dict[str, str]] = {}

    for row in reversed(rows):
        symbol = row.get("symbol", "")
        if not symbol:
            continue
        if active and symbol not in active:
            continue
        if symbol not in latest:
            latest[symbol] = row

    return sorted(
        latest.values(),
        key=lambda row: _timestamp_sort_key(row.get("timestamp", "")),
        reverse=True,
    )


def _build_holdings(positions: list[dict[str, Any]], account: dict[str, Any]) -> list[dict[str, Any]]:
    portfolio_value = _safe_float(account.get("portfolio_value")) or _safe_float(account.get("equity")) or 0.0
    holdings = []

    for position in positions:
        market_value = _safe_float(position.get("market_value")) or 0.0
        allocation_pct = (abs(market_value) / portfolio_value * 100.0) if portfolio_value > 0 else 0.0
        row = dict(position)
        row["allocation_pct"] = round(allocation_pct, 2)
        holdings.append(row)

    return sorted(
        holdings,
        key=lambda row: abs(_safe_float(row.get("market_value")) or 0.0),
        reverse=True,
    )


def _timestamp_sort_key(value: str) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def run_server(
    storage: StorageManager,
    state: AppState,
    market_data: Any,
    account_service: BaseAccountService | None = None,
    port: int = 8000,
):
    """Starts the Uvicorn server in a background thread."""
    global _storage, _state, _market_data, _account_service
    _storage = storage
    _state = state
    _market_data = market_data
    _account_service = account_service

    logger.info("Starting Dashboard Server on http://localhost:{}...", port)

    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info", access_log=True)
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return thread
