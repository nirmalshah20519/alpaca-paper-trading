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

            # 3. Check for account-level blocks
            if account.get("trading_blocked") or account.get("account_blocked"):
                logger.error("[ReconciliationLoop] ACCOUNT BLOCKED on Alpaca. Pausing entries.")
                self.app_state.set_paused(True)
                return

            # 4. Sync open orders with CSV (Deep Reconciliation)
            if self._storage:
                raw_orders = self._account_service.get_raw_open_orders()
                self._storage.sync_open_orders(raw_orders)
                
                # Update AppState order IDs
                self.app_state.set_open_orders([str(o.id) for o in raw_orders])
            
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
