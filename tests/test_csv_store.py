"""
tests/test_csv_store.py

Tests for CsvStore CSV initialisation, append, read, and atomic rewrite.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.storage.csv_store import CsvStore
from app.storage.storage_manager import (
    StorageManager,
    OPEN_ORDERS_HEADERS,
    PAST_ORDERS_HEADERS,
    SIGNAL_LOGS_HEADERS,
    REJECTED_SIGNALS_HEADERS,
)
from app.core.models import ExecutionResult


# ---------------------------------------------------------------------------
# CsvStore unit tests
# ---------------------------------------------------------------------------

class TestCsvStoreInit:

    def test_creates_file_with_headers(self, tmp_path):
        store = CsvStore()
        f = tmp_path / "test.csv"
        headers = ["id", "name", "value"]
        store.init_file(f, headers)

        assert f.exists()
        lines = f.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "id,name,value"

    def test_does_not_overwrite_existing_file(self, tmp_path):
        store = CsvStore()
        f = tmp_path / "existing.csv"
        headers = ["a", "b"]
        store.init_file(f, headers)
        # Write a data row manually
        f.write_text("a,b\n1,2\n", encoding="utf-8")

        # Call init_file again — should NOT overwrite
        store.init_file(f, headers)
        content = f.read_text(encoding="utf-8")
        assert "1,2" in content

    def test_creates_parent_directories(self, tmp_path):
        store = CsvStore()
        f = tmp_path / "nested" / "deep" / "file.csv"
        store.init_file(f, ["col1", "col2"])
        assert f.exists()


class TestCsvStoreAppendAndRead:

    def test_append_and_read_single_row(self, tmp_path):
        store = CsvStore()
        f = tmp_path / "data.csv"
        headers = ["sym", "action", "qty"]
        store.init_file(f, headers)

        row = {"sym": "AAPL", "action": "BUY", "qty": "2"}
        store.append_row(f, row)

        rows = store.read_rows(f)
        assert len(rows) == 1
        assert rows[0]["sym"] == "AAPL"
        assert rows[0]["action"] == "BUY"

    def test_append_multiple_rows(self, tmp_path):
        store = CsvStore()
        f = tmp_path / "multi.csv"
        headers = ["sym", "action"]
        store.init_file(f, headers)

        store.append_row(f, {"sym": "AAPL", "action": "BUY"})
        store.append_row(f, {"sym": "MSFT", "action": "SKIP"})
        store.append_row(f, {"sym": "NVDA", "action": "BUY"})

        rows = store.read_rows(f)
        assert len(rows) == 3
        assert rows[2]["sym"] == "NVDA"

    def test_read_empty_file_returns_empty_list(self, tmp_path):
        store = CsvStore()
        f = tmp_path / "empty.csv"
        store.init_file(f, ["a", "b"])
        rows = store.read_rows(f)
        assert rows == []

    def test_read_nonexistent_file_returns_empty_list(self, tmp_path):
        store = CsvStore()
        f = tmp_path / "ghost.csv"
        rows = store.read_rows(f)
        assert rows == []

    def test_extra_keys_are_ignored_on_append(self, tmp_path):
        """Columns not in headers should be silently dropped (extrasaction=ignore)."""
        store = CsvStore()
        f = tmp_path / "narrow.csv"
        headers = ["sym"]
        store.init_file(f, headers)

        # Row has 'extra' key that is not in headers
        store.append_row(f, {"sym": "AAPL", "extra": "should_be_dropped"})
        rows = store.read_rows(f)
        assert len(rows) == 1
        assert "extra" not in rows[0]


class TestCsvStoreAtomicRewrite:

    def test_rewrite_replaces_all_rows(self, tmp_path):
        store = CsvStore()
        f = tmp_path / "orders.csv"
        headers = ["id", "sym"]
        store.init_file(f, headers)
        store.append_row(f, {"id": "1", "sym": "AAPL"})
        store.append_row(f, {"id": "2", "sym": "MSFT"})

        new_rows = [{"id": "3", "sym": "NVDA"}]
        store.rewrite_rows_atomic(f, headers, new_rows)

        rows = store.read_rows(f)
        assert len(rows) == 1
        assert rows[0]["sym"] == "NVDA"

    def test_rewrite_empty_rows_leaves_headers_only(self, tmp_path):
        store = CsvStore()
        f = tmp_path / "orders.csv"
        headers = ["id", "sym"]
        store.init_file(f, headers)
        store.append_row(f, {"id": "1", "sym": "AAPL"})

        store.rewrite_rows_atomic(f, headers, [])
        rows = store.read_rows(f)
        assert rows == []
        # Headers should still be present
        first_line = f.read_text(encoding="utf-8").splitlines()[0]
        assert first_line == "id,sym"


# ---------------------------------------------------------------------------
# StorageManager integration test
# ---------------------------------------------------------------------------

class TestStorageManagerInit:

    def test_all_csv_files_created_with_correct_headers(self, tmp_path, monkeypatch):
        """StorageManager.init_all() should create all 4 CSV files."""
        import config.settings as settings_mod

        # Redirect data paths to tmp_path
        monkeypatch.setattr(settings_mod, "DATA_DIR", str(tmp_path))
        monkeypatch.setattr(settings_mod, "OPEN_ORDERS_CSV", str(tmp_path / "open_orders.csv"))
        monkeypatch.setattr(settings_mod, "PAST_ORDERS_CSV", str(tmp_path / "past_orders.csv"))
        monkeypatch.setattr(settings_mod, "SIGNAL_LOGS_CSV", str(tmp_path / "signal_logs.csv"))
        monkeypatch.setattr(settings_mod, "REJECTED_SIGNALS_CSV", str(tmp_path / "rejected_signals.csv"))

        # Re-import StorageManager so it picks up patched paths
        import importlib
        import app.storage.storage_manager as sm_mod
        importlib.reload(sm_mod)

        manager = sm_mod.StorageManager()
        manager.init_all()

        open_orders_headers = (tmp_path / "open_orders.csv").read_text().splitlines()[0]
        assert "local_trade_id" in open_orders_headers
        assert "symbol" in open_orders_headers

        past_orders_headers = (tmp_path / "past_orders.csv").read_text().splitlines()[0]
        assert "gross_pnl" in past_orders_headers

        signal_logs_headers = (tmp_path / "signal_logs.csv").read_text().splitlines()[0]
        assert "validator_status" in signal_logs_headers

        rejected_headers = (tmp_path / "rejected_signals.csv").read_text().splitlines()[0]
        assert "payload_hash" in rejected_headers


class TestStorageManagerOrderLifecycle:

    def _manager(self, tmp_path: Path) -> StorageManager:
        manager = StorageManager()
        manager.open_orders_path = tmp_path / "open_orders.csv"
        manager.past_orders_path = tmp_path / "past_orders.csv"
        manager.signal_logs_path = tmp_path / "signal_logs.csv"
        manager.rejected_signals_path = tmp_path / "rejected_signals.csv"
        manager.init_all()
        return manager

    def test_record_closed_order_moves_exit_to_history(self, tmp_path):
        manager = self._manager(tmp_path)
        manager.record_open_order(ExecutionResult(
            local_trade_id="trade-1",
            alpaca_order_id="entry-1",
            client_order_id="client-1",
            symbol="AAPL",
            side="BUY",
            qty=2,
            submitted_at="2026-05-05T00:00:00+00:00",
            status="filled",
            target_price=150.0,
            stop_loss_price=140.0,
        ))

        entry_row = manager.get_open_order_for_symbol("AAPL")
        manager.record_closed_order(
            entry_row,
            ExecutionResult(
                local_trade_id="exit-1",
                alpaca_order_id="exit-1",
                client_order_id="client-exit-1",
                symbol="AAPL",
                side="SELL",
                qty=2,
                submitted_at="2026-05-05T00:30:00+00:00",
                status="filled",
            ),
            "TARGET_REACHED",
        )
        manager.remove_open_order_by_symbol("AAPL")

        assert manager.get_open_orders() == []
        history = manager.get_recent_past_orders()
        assert history[0]["symbol"] == "AAPL"
        assert history[0]["entry_alpaca_order_id"] == "entry-1"
        assert history[0]["exit_alpaca_order_id"] == "exit-1"
        assert history[0]["exit_reason_code"] == "TARGET_REACHED"
        assert history[0]["holding_minutes"] == "30.00"

    def test_sync_preserves_position_rows_then_archives_closed_rows(self, tmp_path):
        manager = self._manager(tmp_path)
        manager.csv.append_row(manager.open_orders_path, {
            "local_trade_id": "trade-1",
            "alpaca_order_id": "entry-1",
            "symbol": "BTC/USD",
            "entry_side": "BUY",
            "qty": "0.1",
            "entry_status": "SUBMITTED",
            "target_price": "65000",
            "stop_loss_price": "59000",
            "opened_at": "2026-05-05T00:00:00+00:00",
            "status": "OPEN",
        })

        manager.sync_open_orders([], position_symbols=["BTCUSD"])

        rows = manager.get_open_orders()
        assert len(rows) == 1
        assert rows[0]["status"] == "POSITION_OPEN"
        assert rows[0]["target_price"] == "65000"
        assert manager.get_recent_past_orders() == []

        manager.sync_open_orders([], position_symbols=[])

        assert manager.get_open_orders() == []
        history = manager.get_recent_past_orders()
        assert len(history) == 1
        assert history[0]["symbol"] == "BTC/USD"
        assert history[0]["exit_reason_code"] == "RECONCILED_CLOSED"

    def test_sync_does_not_create_entry_row_for_unmatched_order_on_held_symbol(self, tmp_path):
        manager = self._manager(tmp_path)

        manager.sync_open_orders(
            [
                SimpleNamespace(
                    id="exit-1",
                    client_order_id="client-exit-1",
                    symbol="AAPL",
                    side="sell",
                    qty="2",
                    status="new",
                    created_at="2026-05-05T00:00:00+00:00",
                )
            ],
            position_symbols=["AAPL"],
        )

        assert manager.get_open_orders() == []
