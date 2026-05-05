"""
app/storage/storage_manager.py

StorageManager — initialises all CSV files with correct headers and
exposes typed store accessors.

Call `StorageManager.init_all()` once at service startup.
"""

from __future__ import annotations

from datetime import datetime, timezone
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
from app.utils.time_utils import utc_now


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

    def get_open_order_for_symbol(self, symbol: str) -> dict[str, str] | None:
        """Return the local open-trade row for *symbol*, if present."""
        wanted = self._canonical_symbol(symbol)
        for row in self.get_open_orders():
            if self._canonical_symbol(row.get("symbol")) == wanted:
                return row
        return None

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

    def remove_open_order_by_symbol(self, symbol: str) -> None:
        """Remove local open-trade rows for *symbol* after an exit is submitted."""
        wanted = self._canonical_symbol(symbol)
        remaining = [
            row for row in self.get_open_orders()
            if self._canonical_symbol(row.get("symbol")) != wanted
        ]
        self.csv.rewrite_rows_atomic(
            self.open_orders_path,
            OPEN_ORDERS_HEADERS,
            remaining,
        )

    def record_closed_order(
        self,
        entry_row: dict[str, Any] | None,
        exit_result: ExecutionResult | None,
        exit_reason_code: str = "",
    ) -> None:
        """Append a closed/reconciled trade record to past_orders.csv."""
        row = entry_row or {}
        exit_side = exit_result.side if exit_result else ""
        qty = row.get("qty") or (exit_result.qty if exit_result else "")
        opened_at = row.get("opened_at", "")
        closed_at = exit_result.submitted_at if exit_result else utc_now()

        closed = {
            "local_trade_id": row.get("local_trade_id") or (exit_result.local_trade_id if exit_result else ""),
            "entry_alpaca_order_id": row.get("alpaca_order_id", ""),
            "exit_alpaca_order_id": exit_result.alpaca_order_id if exit_result else "",
            "symbol": row.get("symbol") or (exit_result.symbol if exit_result else ""),
            "asset_class": row.get("asset_class", ""),
            "entry_side": row.get("entry_side", ""),
            "exit_side": exit_side,
            "qty": qty,
            "entry_price": row.get("entry_price_estimate", ""),
            "exit_price": "",
            "target_price": row.get("target_price", ""),
            "stop_loss_price": row.get("stop_loss_price", ""),
            "gross_pnl": "",
            "pnl_pct": "",
            "opened_at": opened_at,
            "closed_at": closed_at,
            "holding_minutes": self._holding_minutes(opened_at, closed_at),
            "entry_reason_code": row.get("reason_code", ""),
            "exit_reason_code": exit_reason_code,
            "status": (exit_result.status if exit_result else "RECONCILED_CLOSED"),
        }
        self.csv.append_row(self.past_orders_path, closed)

    def sync_open_orders(
        self,
        alpaca_orders: list[Any],
        position_symbols: list[str] | None = None,
    ) -> None:
        """
        Synchronise the open_orders.csv with the actual list from Alpaca.
        Existing rows are preserved when their symbol is still an open
        position, because filled entry orders disappear from Alpaca's open
        orders while their TP/SL context is still needed for exits.
        """
        import uuid

        current_rows = self.get_open_orders()
        # Map alpaca_id -> row_dict
        row_map = {r["alpaca_order_id"]: r for r in current_rows if r.get("alpaca_order_id")}
        position_set = {
            self._canonical_symbol(symbol)
            for symbol in (position_symbols or [])
        }
        
        new_rows = []
        retained_order_ids: set[str] = set()
        for ao in alpaca_orders:
            aid = str(ao.id)
            symbol = str(getattr(ao, "symbol", ""))
            retained_order_ids.add(aid)
            if aid in row_map:
                # Update status if needed, but keep the rest
                row = dict(row_map[aid])
                row["status"] = self._value(ao.status).upper()
                row["last_checked_at"] = utc_now()
                new_rows.append(row)
            else:
                if self._canonical_symbol(symbol) in position_set:
                    logger.debug(
                        "Skipping unmatched Alpaca open order {} for held symbol {}",
                        aid,
                        symbol,
                    )
                    continue

                # New order found on Alpaca not in CSV
                new_rows.append({
                    "local_trade_id": str(uuid.uuid4())[:8],
                    "alpaca_order_id": aid,
                    "client_order_id": str(getattr(ao, "client_order_id", "")),
                    "symbol": symbol,
                    "entry_side": self._value(getattr(ao, "side", "")).upper(),
                    "qty": str(getattr(ao, "qty", "")),
                    "entry_status": self._value(getattr(ao, "status", "")).upper(),
                    "opened_at": str(getattr(ao, "created_at", "") or utc_now()),
                    "last_checked_at": utc_now(),
                    "status": "OPEN",
                })

        for row in current_rows:
            aid = row.get("alpaca_order_id")
            if aid and aid in retained_order_ids:
                continue

            if self._canonical_symbol(row.get("symbol")) in position_set:
                preserved = dict(row)
                preserved["entry_status"] = "FILLED"
                preserved["status"] = "POSITION_OPEN"
                preserved["last_checked_at"] = utc_now()
                new_rows.append(preserved)
            else:
                self.record_closed_order(row, None, "RECONCILED_CLOSED")
        
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

    def _canonical_symbol(self, symbol: Any) -> str:
        return str(symbol or "").upper().replace("/", "").replace("-", "")

    def _value(self, value: Any) -> str:
        return str(value.value) if hasattr(value, "value") else str(value)

    def _holding_minutes(self, opened_at: Any, closed_at: Any) -> str:
        start = self._parse_datetime(opened_at)
        end = self._parse_datetime(closed_at)
        if not start or not end:
            return ""
        minutes = max((end - start).total_seconds() / 60.0, 0.0)
        return f"{minutes:.2f}"

    def _parse_datetime(self, value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        try:
            text = str(value).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
