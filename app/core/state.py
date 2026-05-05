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
        self._recently_analyzed: set[str] = set()
        self._last_analysis_data: dict[str, dict] = {} # symbol -> {price, time}
        
        # Phase 3+: Account snapshot & open orders from Alpaca
        self._account_data: dict[str, Any] = {}
        self._positions: list[dict[str, Any]] = []
        self._open_order_ids: list[str] = []
        self._open_order_symbols: list[str] = []

        # ----------------------------------------------------------------
        # Shutdown coordination
        # ----------------------------------------------------------------
        self.shutdown_event: threading.Event = threading.Event()

        # ----------------------------------------------------------------
        # Service metadata
        # ----------------------------------------------------------------
        self.service_start_utc: str = utc_now()

    # ------------------------------------------------------------------
    # Analysis Throttle
    # ------------------------------------------------------------------

    def should_analyze(self, symbol: str, current_price: float, threshold: float = 0.002, max_age_mins: int = 30) -> bool:
        """
        Returns True if the symbol should be analyzed by the LLM.
        Criteria: Price move > threshold OR age > max_age_mins.
        """
        from datetime import datetime, timezone
        with self.asset_list_lock:
            data = self._last_analysis_data.get(symbol)
            if not data:
                return True
            
            last_price = data["price"]
            last_time = data["time"]
            
            # 1. Check price move
            price_move = abs(current_price - last_price) / last_price if last_price > 0 else 1.0
            if price_move >= threshold:
                return True
            
            # 2. Check time age
            age_mins = (datetime.now(timezone.utc) - last_time).total_seconds() / 60
            if age_mins >= max_age_mins:
                return True
                
            return False

    def mark_analyzed(self, symbol: str, price: float) -> None:
        from datetime import datetime, timezone
        with self.asset_list_lock:
            self._recently_analyzed.add(symbol)
            self._last_analysis_data[symbol] = {
                "price": price,
                "time": datetime.now(timezone.utc)
            }

    def clear_analysis_cache(self) -> None:
        with self.asset_list_lock:
            self._recently_analyzed.clear()
            self._last_analysis_data.clear()

    # ------------------------------------------------------------------
    # Active Assets
    # ------------------------------------------------------------------

    def get_active_assets(self) -> list[str]:
        """Return a snapshot of active_assets."""
        with self.asset_list_lock:
            return list(self._active_assets)

    @property
    def last_asset_refresh_utc(self) -> Optional[str]:
        with self.asset_list_lock:
            return self._last_asset_refresh_utc

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
    # Positions
    # ------------------------------------------------------------------

    def get_positions(self) -> list[dict[str, Any]]:
        with self.account_lock:
            return list(self._positions if hasattr(self, "_positions") else [])

    def set_positions(self, positions: list[dict[str, Any]]) -> None:
        with self.account_lock:
            self._positions = list(positions)

    # ------------------------------------------------------------------
    # Open Orders
    # ------------------------------------------------------------------

    def get_open_orders(self) -> list[str]:
        with self.open_orders_lock:
            return list(self._open_order_ids)

    def get_open_order_symbols(self) -> list[str]:
        with self.open_orders_lock:
            return list(self._open_order_symbols)

    def set_open_orders(self, order_ids: list[str], symbols: list[str] | None = None) -> None:
        with self.open_orders_lock:
            self._open_order_ids = list(order_ids)
            if symbols is not None:
                self._open_order_symbols = list(symbols)

    def add_open_order(self, order_id: str | None, symbol: str | None) -> None:
        with self.open_orders_lock:
            if order_id and order_id not in self._open_order_ids:
                self._open_order_ids.append(order_id)
            if symbol and symbol not in self._open_order_symbols:
                self._open_order_symbols.append(symbol)

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
