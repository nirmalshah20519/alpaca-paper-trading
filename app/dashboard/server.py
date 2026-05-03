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
    
    return {
        "is_paused": _state.is_paused(),
        "active_assets": _state.get_active_assets(),
        "account": _state.get_account_data(),
        "open_orders_count": len(_state.get_open_orders()),
        "uptime": _state.service_start_utc
    }

@app.get("/api/history")
async def get_history():
    """Returns historical signals and results from CSV."""
    if not _storage:
        return JSONResponse({"error": "Storage not initialized"}, status_code=500)
    
    # Read last 50 signals
    signals = _storage.csv.read_rows(_storage.signal_logs_path)[-50:]
    # Read all open orders
    open_orders = _storage.get_open_orders()
    # Read past orders (completed)
    past_orders = _storage.csv.read_rows(_storage.past_orders_path)[-50:]
    
    return {
        "signals": signals[::-1], # Newest first
        "open_orders": open_orders,
        "past_orders": past_orders[::-1]
    }

def run_server(storage: StorageManager, state: AppState, port: int = 8000):
    """Starts the Uvicorn server in a background thread."""
    global _storage, _state
    _storage = storage
    _state = state
    
    logger.info("Starting Dashboard Server on http://localhost:{}...", port)
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    
    # Run in a separate thread so it doesn't block the main process
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return thread
