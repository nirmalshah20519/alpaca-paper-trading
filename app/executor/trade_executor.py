"""
app/executor/trade_executor.py

TradeExecutor — manages the end-to-end execution of a signal.

Design rules:
  - Calls AlpacaOrderSubmitter.
  - Calls ExecutionRecorder to save results.
  - Returns ExecutionResult.
"""

from __future__ import annotations

import uuid
from app.core.models import EntrySignal, ExecutionResult
from app.executor.alpaca_order_submitter import AlpacaOrderSubmitter
from app.storage.storage_manager import StorageManager
from app.utils.logger import logger
from app.utils.time_utils import utc_now


class TradeExecutor:
    """
    Orchestrates order submission and recording.
    """

    def __init__(
        self, 
        submitter: AlpacaOrderSubmitter, 
        storage: StorageManager
    ) -> None:
        self.submitter = submitter
        self.storage = storage

    def execute_entry(self, signal: EntrySignal) -> ExecutionResult:
        """
        Submit order and record to CSV.
        """
        local_id = str(uuid.uuid4())[:8]
        
        try:
            alpaca_order = self.submitter.submit_entry(signal)
            
            result = ExecutionResult(
                local_trade_id=local_id,
                alpaca_order_id=str(alpaca_order.id),
                client_order_id=str(alpaca_order.client_order_id),
                symbol=signal.sym,
                side=signal.action,
                qty=signal.qty,
                submitted_at=str(utc_now()),
                status="submitted",
                target_price=signal.target,
                stop_loss_price=signal.stop
            )
            
            # Record to past_orders.csv or open_orders.csv
            # For now, we put it in open_orders.csv
            self.storage.record_open_order(result)
            
            return result

        except Exception as exc:
            logger.error("Execution failed for {}: {}", signal.sym, exc)
            return ExecutionResult(
                local_trade_id=local_id,
                client_order_id=f"fail-{local_id}",
                symbol=signal.sym,
                side=signal.action,
                qty=signal.qty,
                submitted_at=str(utc_now()),
                status="failed",
                error=str(exc)
            )

    def execute_exit(
        self,
        symbol: str,
        qty: float,
        side: str = "SELL",
        reason_code: str | None = None,
    ) -> ExecutionResult:
        """
        Submit exit order and record.
        """
        local_id = str(uuid.uuid4())[:8]
        exit_side = str(side).upper()
        exit_qty = abs(float(qty))
        entry_row = self._open_order_for_symbol(symbol)

        try:
            alpaca_order = self.submitter.submit_exit(symbol, exit_qty, side=exit_side)
            result = ExecutionResult(
                local_trade_id=local_id,
                alpaca_order_id=str(alpaca_order.id),
                client_order_id=str(alpaca_order.client_order_id),
                symbol=symbol,
                side=exit_side,
                qty=exit_qty,
                submitted_at=str(utc_now()),
                status=self._order_status(alpaca_order),
            )
            self._record_exit(symbol, result, entry_row, reason_code or "")
            return result
        except Exception as exc:
            logger.error("Exit execution failed for {}: {}", symbol, exc)
            return ExecutionResult(
                local_trade_id=local_id,
                client_order_id=f"fail-exit-{local_id}",
                symbol=symbol,
                side=exit_side,
                qty=exit_qty,
                submitted_at=str(utc_now()),
                status="failed",
                error=str(exc)
            )

    def _open_order_for_symbol(self, symbol: str) -> dict | None:
        try:
            row = self.storage.get_open_order_for_symbol(symbol)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not load local open order for {}: {}", symbol, exc)
            return None
        return row if isinstance(row, dict) else None

    def _record_exit(
        self,
        symbol: str,
        result: ExecutionResult,
        entry_row: dict | None,
        reason_code: str,
    ) -> None:
        try:
            self.storage.record_closed_order(entry_row, result, reason_code)
            self.storage.remove_open_order_by_symbol(symbol)
        except Exception as exc:  # noqa: BLE001
            logger.error("Exit submitted for {}, but local history update failed: {}", symbol, exc)

    def _order_status(self, order: object) -> str:
        status = getattr(order, "status", "submitted")
        return str(status.value) if hasattr(status, "value") else str(status)
