"""
app/loops/reconciliation_loop.py

ReconciliationLoop — ensures the local system state matches Alpaca's reality.

Phase 7/8 Update:
  - Fetches positions and account status from Alpaca.
  - Compares with local CSV storage.
  - Pauses entries if a critical mismatch is detected.
"""

from __future__ import annotations

from typing import Optional

from app.core.state import AppState
from app.datasource.account_service import BaseAccountService
from app.storage.storage_manager import StorageManager
from app.loops.base_loop import BaseLoop
from app.utils.logger import logger
from app.utils.safe_number import safe_float
from config.risk_limits import (
    MAX_DAILY_LOSS_PCT,
    MAX_PORTFOLIO_DRAWDOWN_PCT,
    MAX_TRADES_PER_DAY,
)
from config.settings import RECONCILIATION_INTERVAL_SECONDS


class ReconciliationLoop(BaseLoop):
    """
    Periodically reconciles local state with Alpaca.
    """

    def __init__(
        self,
        app_state: AppState,
        account_service: Optional[BaseAccountService] = None,
        storage_manager: Optional[StorageManager] = None,
    ) -> None:
        super().__init__(
            name="ReconciliationLoop",
            interval_seconds=RECONCILIATION_INTERVAL_SECONDS,
            app_state=app_state,
        )
        self._account_service = account_service
        self._storage = storage_manager
        self._peak_portfolio_value: float | None = None

    def run_once(self) -> None:
        if not self._account_service:
            return

        logger.info("[ReconciliationLoop] Starting reconciliation...")

        try:
            # 1. Fetch account and positions from Alpaca
            account = self._account_service.get_account_snapshot()
            positions = self._account_service.get_positions()

            if not account:
                logger.warning("[ReconciliationLoop] Could not fetch account. Skipping.")
                return

            # 2. Update AppState
            self.app_state.set_account_data(account)
            self.app_state.set_positions(positions)

            # 3. Sync open orders with CSV (Deep Reconciliation)
            if self._storage:
                raw_orders = self._account_service.get_raw_open_orders()
                position_symbols = [str(pos.get("symbol", "")) for pos in positions]
                self._storage.sync_open_orders(raw_orders, position_symbols=position_symbols)
                
                # Update AppState order IDs
                self.app_state.set_open_orders(
                    [str(o.id) for o in raw_orders],
                    [str(o.symbol) for o in raw_orders],
                )

            # 4. Check for account-level and risk-level blocks
            pause_reason = self._pause_reason(account)
            if pause_reason:
                logger.error("[ReconciliationLoop] {} Pausing entries.", pause_reason)
                self.app_state.set_paused(True)
                return
            
            # 5. Clear pause state if healthy
            if self.app_state.is_paused():
                 logger.info("[ReconciliationLoop] Clearing pause state (health check passed).")
                 self.app_state.set_paused(False)

            logger.info(
                "[ReconciliationLoop] Completed | equity={} | positions={}", 
                account.get("equity"), 
                len(positions)
            )

        except Exception as exc:  # noqa: BLE001
            logger.error("[ReconciliationLoop] Failed: {}", exc)

    def _pause_reason(self, account: dict) -> str | None:
        if account.get("trading_blocked") or account.get("account_blocked"):
            return "ACCOUNT BLOCKED on Alpaca."

        daily_loss = self._daily_loss_fraction(account)
        if daily_loss >= MAX_DAILY_LOSS_PCT:
            return (
                f"Daily loss limit breached "
                f"({daily_loss:.2%} >= {MAX_DAILY_LOSS_PCT:.2%})."
            )

        drawdown = self._portfolio_drawdown_fraction(account)
        if drawdown >= MAX_PORTFOLIO_DRAWDOWN_PCT:
            return (
                f"Portfolio drawdown limit breached "
                f"({drawdown:.2%} >= {MAX_PORTFOLIO_DRAWDOWN_PCT:.2%})."
            )

        trades_today = self._submitted_trades_today()
        if trades_today >= MAX_TRADES_PER_DAY:
            return (
                f"Max trades/day reached "
                f"({trades_today} >= {MAX_TRADES_PER_DAY})."
            )

        return None

    def _daily_loss_fraction(self, account: dict) -> float:
        pnl_pct = safe_float(account.get("day_pnl_pct"))
        if pnl_pct is None:
            pnl = safe_float(account.get("day_pnl"), 0.0) or 0.0
            equity = (
                safe_float(account.get("equity"))
                or safe_float(account.get("portfolio_value"))
                or 0.0
            )
            pnl_pct = pnl / equity if equity > 0 else 0.0

        pnl_pct = self._normalise_fraction(pnl_pct)
        return abs(min(pnl_pct, 0.0))

    def _portfolio_drawdown_fraction(self, account: dict) -> float:
        portfolio_value = (
            safe_float(account.get("portfolio_value"))
            or safe_float(account.get("equity"))
            or 0.0
        )
        if portfolio_value <= 0:
            return 0.0

        if self._peak_portfolio_value is None or portfolio_value > self._peak_portfolio_value:
            self._peak_portfolio_value = portfolio_value

        if not self._peak_portfolio_value:
            return 0.0

        return max((self._peak_portfolio_value - portfolio_value) / self._peak_portfolio_value, 0.0)

    def _submitted_trades_today(self) -> int:
        if not self._account_service:
            return 0

        orders = self._account_service.get_today_orders()
        if not isinstance(orders, list):
            return 0

        ignored_statuses = {"canceled", "cancelled", "rejected", "expired"}
        return sum(
            1
            for order in orders
            if str(order.get("status", "")).lower() not in ignored_statuses
        )

    def _normalise_fraction(self, value: float) -> float:
        return value / 100.0 if abs(value) > 1 else value
