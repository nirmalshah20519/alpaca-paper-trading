"""
app/dashboard/server.py

DashboardServer — provides a web-based UI to monitor the trading service.
Uses FastAPI to serve data from the CSV logs and a premium HTML interface.
"""

from __future__ import annotations

import os
import threading
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.storage.storage_manager import StorageManager
from app.core.state import AppState
from app.utils.logger import logger

app = FastAPI(title="Alpaca Trading Dashboard")

# Dependency injection for the API
_storage: StorageManager | None = None
_state: AppState | None = None
_market_data: Any = None

@app.get("/", response_class=HTMLResponse)
async def get_index():
    index_path = Path(__file__).parent / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return "<h1>Dashboard UI file not found</h1>"

@app.get("/api/status")
async def get_status():
    """Returns the current state of the service."""
    if not _state:
        return JSONResponse({"error": "State not initialized"}, status_code=500)
    
    account = _state.get_account_data()
    
    return {
        "is_paused": _state.is_paused(),
        "active_assets": _state.get_active_assets(),
        "account": account,
        "open_orders_count": len(_state.get_open_orders()),
        "uptime": _state.service_start_utc,
        "last_asset_refresh": _state.last_asset_refresh_utc
    }

@app.get("/api/history")
async def get_history():
    """Returns historical signals and results from CSV."""
    if not _storage:
        return JSONResponse({"error": "Storage not initialized"}, status_code=500)
    
    # Read last 100 signals
    signals = _storage.get_recent_signals(100)
    # Read all open orders
    open_orders = _storage.get_open_orders()
    
    # Attach current price if possible
    if _market_data:
        for order in open_orders:
            try:
                symbol = order.get("symbol")
                if symbol:
                    # Alpaca positions often use SOLUSD, but market data needs SOL/USD
                    if "/" not in symbol and any(c in symbol for c in ["BTC", "ETH", "SOL", "DOGE", "SHIB"]):
                        # Inject slash for crypto pairs
                        symbol = f"{symbol[:-3]}/{symbol[-3:]}"
                    
                    order["current_price"] = _market_data.get_latest_price(symbol)
            except Exception as e:
                logger.warning("Dashboard failed to fetch price for {}: {}", order.get("symbol"), e)
                order["current_price"] = "..."

    # Read past orders (completed)
    past_orders = _storage.get_recent_past_orders(100)
    
    # Get live positions from state
    positions = _state.get_positions()
    
    return {
        "signals": signals[::-1], # Newest first
        "open_orders": open_orders,
        "past_orders": past_orders[::-1],
        "positions": positions
    }

def run_server(storage: StorageManager, state: AppState, market_data: Any, port: int = 8000):
    """Starts the Uvicorn server in a background thread."""
    global _storage, _state, _market_data
    _storage = storage
    _state = state
    _market_data = market_data
    
    logger.info("Starting Dashboard Server on http://localhost:{}...", port)
    
    # We set log_level to 'info' so we can see request errors in the console/log file
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info", access_log=True)
    server = uvicorn.Server(config)
    
    # Run in a separate thread so it doesn't block the main process
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return thread
