from __future__ import annotations

from unittest.mock import MagicMock

from app.core.state import AppState
from app.loops.reconciliation_loop import ReconciliationLoop
from config.risk_limits import MAX_TRADES_PER_DAY


def _account(account_snapshot: dict, positions: list[dict] | None = None) -> MagicMock:
    service = MagicMock()
    service.get_account_snapshot.return_value = {
        "equity": 100_000.0,
        "portfolio_value": 100_000.0,
        "day_pnl_pct": 0.0,
        "trading_blocked": False,
        "account_blocked": False,
        **account_snapshot,
    }
    service.get_positions.return_value = positions or []
    service.get_raw_open_orders.return_value = []
    service.get_today_orders.return_value = []
    return service


def test_reconciliation_pauses_on_daily_loss_limit():
    state = AppState()
    storage = MagicMock()
    account = _account({"day_pnl_pct": -0.04})

    ReconciliationLoop(state, account_service=account, storage_manager=storage).run_once()

    assert state.is_paused() is True
    storage.sync_open_orders.assert_called_once_with([], position_symbols=[])


def test_reconciliation_pauses_on_portfolio_drawdown_limit():
    state = AppState()
    storage = MagicMock()
    account = _account({"portfolio_value": 100_000.0})
    loop = ReconciliationLoop(state, account_service=account, storage_manager=storage)

    loop.run_once()
    assert state.is_paused() is False

    account.get_account_snapshot.return_value = {
        "equity": 89_000.0,
        "portfolio_value": 89_000.0,
        "day_pnl_pct": 0.0,
        "trading_blocked": False,
        "account_blocked": False,
    }
    loop.run_once()

    assert state.is_paused() is True


def test_reconciliation_pauses_on_max_trades_per_day():
    state = AppState()
    account = _account({})
    account.get_today_orders.return_value = [
        {"id": str(i), "status": "filled"}
        for i in range(MAX_TRADES_PER_DAY)
    ]

    ReconciliationLoop(state, account_service=account, storage_manager=MagicMock()).run_once()

    assert state.is_paused() is True


def test_reconciliation_ignores_rejected_orders_for_trade_limit():
    state = AppState()
    account = _account({})
    account.get_today_orders.return_value = [
        {"id": str(i), "status": "rejected"}
        for i in range(MAX_TRADES_PER_DAY + 5)
    ]

    ReconciliationLoop(state, account_service=account, storage_manager=MagicMock()).run_once()

    assert state.is_paused() is False
