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
from typing import Optional

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
                status="submitted"
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

    def execute_exit(self, symbol: str, qty: float) -> ExecutionResult:
        """
        Submit exit order and record.
        """
        local_id = str(uuid.uuid4())[:8]
        try:
            alpaca_order = self.submitter.submit_exit(symbol, qty)
            result = ExecutionResult(
                local_trade_id=local_id,
                alpaca_order_id=str(alpaca_order.id),
                client_order_id=str(alpaca_order.client_order_id),
                symbol=symbol,
                side="SELL",
                qty=int(qty),
                submitted_at=str(utc_now()),
                status="submitted"
            )
            return result
        except Exception as exc:
            logger.error("Exit execution failed for {}: {}", symbol, exc)
            return ExecutionResult(
                local_trade_id=local_id,
                client_order_id=f"fail-exit-{local_id}",
                symbol=symbol,
                side="SELL",
                qty=int(qty),
                submitted_at=str(utc_now()),
                status="failed",
                error=str(exc)
            )
