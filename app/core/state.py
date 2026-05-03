"""
app/core/state.py

AppState — central thread-safe shared state for the trading service.

Design rules from the plan (§6.2 AppState):
  - One RLock per shared resource.
  - Lock ordering must always be:
      asset_list_lock → open_orders_lock → account_lock → execution_lock → reconciliation_lock
  - Readers copy data quickly under the lock, then release.
  - Long external calls (Alpaca, OpenAI) must never hold a lock.
"""

from __future__ import annotations

import threading
from typing import Optional, Any

from app.utils.time_utils import utc_now


class AppState:
    """
    Central mutable state shared across all service threads.
    """

    def __init__(self) -> None:
        # ----------------------------------------------------------------
        # Locks
        # ----------------------------------------------------------------
        self.asset_list_lock: threading.RLock = threading.RLock()
        self.open_orders_lock: threading.RLock = threading.RLock()
        self.account_lock: threading.RLock = threading.RLock()
        self.execution_lock: threading.RLock = threading.RLock()
        self.reconciliation_lock: threading.RLock = threading.RLock()

        # ----------------------------------------------------------------
        # Shared data
        # ----------------------------------------------------------------
        self._active_assets: list[str] = []
        self._last_asset_refresh_utc: Optional[str] = None
        self._pause_new_entries: bool = False
        
        # Phase 3+: Account snapshot & open orders from Alpaca
        self._account_data: dict[str, Any] = {}
        self._open_order_ids: list[str] = []

        # ----------------------------------------------------------------
        # Shutdown coordination
        # ----------------------------------------------------------------
        self.shutdown_event: threading.Event = threading.Event()

        # ----------------------------------------------------------------
        # Service metadata
        # ----------------------------------------------------------------
        self.service_start_utc: str = utc_now()

    # ------------------------------------------------------------------
    # Active Assets
    # ------------------------------------------------------------------

    def get_active_assets(self) -> list[str]:
        """Return a snapshot of active_assets."""
        with self.asset_list_lock:
            return list(self._active_assets)

    def set_active_assets(self, symbols: list[str], refresh_time: Optional[str] = None) -> None:
        with self.asset_list_lock:
            self._active_assets = list(symbols)
            self._last_asset_refresh_utc = refresh_time or utc_now()

    # ------------------------------------------------------------------
    # Pause State
    # ------------------------------------------------------------------

    def is_paused(self) -> bool:
        with self.account_lock:
            return self._pause_new_entries

    def set_paused(self, pause: bool) -> None:
        with self.account_lock:
            self._pause_new_entries = pause

    # ------------------------------------------------------------------
    # Account Data
    # ------------------------------------------------------------------

    def get_account_data(self) -> dict[str, Any]:
        with self.account_lock:
            return dict(self._account_data)

    def set_account_data(self, data: dict[str, Any]) -> None:
        with self.account_lock:
            self._account_data = dict(data)

    # ------------------------------------------------------------------
    # Open Orders
    # ------------------------------------------------------------------

    def get_open_orders(self) -> list[str]:
        with self.open_orders_lock:
            return list(self._open_order_ids)

    def set_open_orders(self, order_ids: list[str]) -> None:
        with self.open_orders_lock:
            self._open_order_ids = list(order_ids)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def request_shutdown(self) -> None:
        self.shutdown_event.set()

    def is_shutting_down(self) -> bool:
        return self.shutdown_event.is_set()

    def __repr__(self) -> str:
        with self.asset_list_lock:
            assets_len = len(self._active_assets)
        with self.account_lock:
            pause = self._pause_new_entries
        return (
            f"AppState("
            f"assets={assets_len}, "
            f"pause={pause}, "
            f"shutdown={self.is_shutting_down()}"
            f")"
        )
