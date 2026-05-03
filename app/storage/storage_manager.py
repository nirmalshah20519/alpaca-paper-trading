"""
app/storage/storage_manager.py

StorageManager — initialises all CSV files with correct headers and
exposes typed store accessors.

Call `StorageManager.init_all()` once at service startup.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from config.settings import (
    OPEN_ORDERS_CSV,
    PAST_ORDERS_CSV,
    SIGNAL_LOGS_CSV,
    REJECTED_SIGNALS_CSV,
)
from app.storage.csv_store import CsvStore
from app.utils.logger import logger
from app.core.models import ExecutionResult


# ---------------------------------------------------------------------------
# CSV Headers  (from plan §15)
# ---------------------------------------------------------------------------

OPEN_ORDERS_HEADERS: list[str] = [
    "local_trade_id", "alpaca_order_id", "client_order_id", "symbol",
    "asset_class", "entry_side", "qty", "entry_order_type", "entry_status",
    "entry_price_estimate", "target_price", "stop_loss_price",
    "max_loss_amount", "confidence", "reason_code",
    "opened_at", "last_checked_at", "status",
]

PAST_ORDERS_HEADERS: list[str] = [
    "local_trade_id", "entry_alpaca_order_id", "exit_alpaca_order_id",
    "symbol", "asset_class", "entry_side", "exit_side", "qty",
    "entry_price", "exit_price", "target_price", "stop_loss_price",
    "gross_pnl", "pnl_pct", "opened_at", "closed_at", "holding_minutes",
    "entry_reason_code", "exit_reason_code", "status",
]

SIGNAL_LOGS_HEADERS: list[str] = [
    "timestamp", "flow", "symbol", "action", "confidence", "qty",
    "target", "stop", "reason_code", "validator_status", "validator_reason",
]

REJECTED_SIGNALS_HEADERS: list[str] = [
    "timestamp", "flow", "symbol", "raw_action",
    "reason_code", "rejection_reason", "payload_hash",
]


# ---------------------------------------------------------------------------
# StorageManager
# ---------------------------------------------------------------------------

class StorageManager:
    """
    Owns all CSV stores and initialises files on startup.

    Usage
    -----
        storage = StorageManager()
        storage.init_all()
        storage.csv.append_row(storage.open_orders_path, row)
    """

    def __init__(self) -> None:
        self.csv = CsvStore()
        self.open_orders_path = Path(OPEN_ORDERS_CSV)
        self.past_orders_path = Path(PAST_ORDERS_CSV)
        self.signal_logs_path = Path(SIGNAL_LOGS_CSV)
        self.rejected_signals_path = Path(REJECTED_SIGNALS_CSV)

    def init_all(self) -> None:
        """Create all CSV files with headers if they don't exist yet."""
        logger.info("Initialising CSV storage files…")
        self.csv.init_file(self.open_orders_path, OPEN_ORDERS_HEADERS)
        self.csv.init_file(self.past_orders_path, PAST_ORDERS_HEADERS)
        self.csv.init_file(self.signal_logs_path, SIGNAL_LOGS_HEADERS)
        self.csv.init_file(self.rejected_signals_path, REJECTED_SIGNALS_HEADERS)
        logger.info("CSV storage ready.")

    # ------------------------------------------------------------------
    # Typed helpers (expanded in later phases)
    # ------------------------------------------------------------------

    def get_open_orders(self) -> list[dict[str, str]]:
        """Return all rows from open_orders.csv."""
        return self.csv.read_rows(self.open_orders_path)

    def record_open_order(self, result: ExecutionResult) -> None:
        """Append a new open order to the CSV."""
        row = {
            "local_trade_id": result.local_trade_id,
            "alpaca_order_id": result.alpaca_order_id,
            "client_order_id": result.client_order_id,
            "symbol": result.symbol,
            "entry_side": result.side,
            "qty": result.qty,
            "entry_status": result.status,
            "opened_at": result.submitted_at,
            "status": "OPEN",
        }
        self.csv.append_row(self.open_orders_path, row)

    def record_signal(self, timestamp: str, flow: str, symbol: str, signal: Any, validation: Any) -> None:
        """Log a signal decision (approved or skipped)."""
        row = {
            "timestamp": timestamp,
            "flow": flow,
            "symbol": symbol,
            "action": getattr(signal, "action", "SKIP"),
            "confidence": getattr(signal, "conf", 0.0),
            "qty": getattr(signal, "qty", 0),
            "target": getattr(signal, "target", None),
            "stop": getattr(signal, "stop", None),
            "reason_code": getattr(signal, "reason_code", "N/A"),
            "validator_status": "APPROVED" if getattr(validation, "validated", False) else "REJECTED",
            "validator_reason": getattr(validation, "reason", ""),
        }
        self.csv.append_row(self.signal_logs_path, row)
