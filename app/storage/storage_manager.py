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
            "target_price": result.target_price,
            "stop_loss_price": result.stop_loss_price,
            "opened_at": result.submitted_at,
            "status": "OPEN",
        }
        self.csv.append_row(self.open_orders_path, row)

    def sync_open_orders(self, alpaca_orders: list[Any]) -> None:
        """
        Synchronise the open_orders.csv with the actual list from Alpaca.
        Existing orders in CSV are preserved (keeping TP/SL), missing ones are added.
        Orders no longer in Alpaca are removed from open_orders.csv.
        """
        import uuid
        from app.utils.time_utils import utc_now
        
        current_rows = self.get_open_orders()
        # Map alpaca_id -> row_dict
        row_map = {r["alpaca_order_id"]: r for r in current_rows if r.get("alpaca_order_id")}
        
        new_rows = []
        for ao in alpaca_orders:
            aid = str(ao.id)
            if aid in row_map:
                # Update status if needed, but keep the rest
                row = row_map[aid]
                row["status"] = str(ao.status).upper()
                new_rows.append(row)
            else:
                # New order found on Alpaca not in CSV
                new_rows.append({
                    "local_trade_id": str(uuid.uuid4())[:8],
                    "alpaca_order_id": aid,
                    "client_order_id": str(ao.client_order_id),
                    "symbol": ao.symbol,
                    "entry_side": str(ao.side).upper(),
                    "qty": str(ao.qty),
                    "entry_status": str(ao.status).upper(),
                    "opened_at": str(ao.created_at or utc_now()),
                    "status": "OPEN",
                })
        
        logger.info("Syncing open orders: {} from Alpaca -> CSV", len(new_rows))
        self.csv.rewrite_rows_atomic(self.open_orders_path, OPEN_ORDERS_HEADERS, new_rows)

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
            "validator_status": "APPROVED" if (validation and getattr(validation, "validated", False)) else "REJECTED",
            "validator_reason": getattr(validation, "reason", "") if validation else "LLM_SKIP",
        }
        self.csv.append_row(self.signal_logs_path, row)

    def get_recent_signals(self, limit: int = 100) -> list[dict[str, str]]:
        rows = self.csv.read_rows(self.signal_logs_path)
        return rows[-limit:] if rows else []

    def get_recent_past_orders(self, limit: int = 100) -> list[dict[str, str]]:
        rows = self.csv.read_rows(self.past_orders_path)
        return rows[-limit:] if rows else []
