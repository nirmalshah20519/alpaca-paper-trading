from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.core.models import ExecutionResult
from app.executor.trade_executor import TradeExecutor
from app.storage.storage_manager import StorageManager


def _storage(tmp_path):
    manager = StorageManager()
    manager.open_orders_path = tmp_path / "open_orders.csv"
    manager.past_orders_path = tmp_path / "past_orders.csv"
    manager.signal_logs_path = tmp_path / "signal_logs.csv"
    manager.rejected_signals_path = tmp_path / "rejected_signals.csv"
    manager.init_all()
    return manager


def test_execute_exit_records_closed_trade_history(tmp_path):
    storage = _storage(tmp_path)
    storage.record_open_order(ExecutionResult(
        local_trade_id="trade-1",
        alpaca_order_id="entry-1",
        client_order_id="client-entry-1",
        symbol="AAPL",
        side="BUY",
        qty=2,
        submitted_at="2026-05-05T00:00:00+00:00",
        status="filled",
        target_price=150.0,
        stop_loss_price=140.0,
    ))

    submitter = MagicMock()
    submitter.submit_exit.return_value = SimpleNamespace(
        id="exit-1",
        client_order_id="client-exit-1",
        status=SimpleNamespace(value="filled"),
    )

    result = TradeExecutor(submitter, storage).execute_exit(
        "AAPL",
        2,
        side="SELL",
        reason_code="TARGET_REACHED",
    )

    assert result.status == "filled"
    submitter.submit_exit.assert_called_once_with("AAPL", 2.0, side="SELL")
    assert storage.get_open_orders() == []
    history = storage.get_recent_past_orders()
    assert history[0]["symbol"] == "AAPL"
    assert history[0]["exit_alpaca_order_id"] == "exit-1"
    assert history[0]["exit_reason_code"] == "TARGET_REACHED"
