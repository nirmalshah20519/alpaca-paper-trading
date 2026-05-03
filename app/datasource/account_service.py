"""
app/datasource/account_service.py

AccountService — fetches account info, positions, and open orders from Alpaca.

Architecture:
  - BaseAccountService defines the interface (ABC).
  - AlpacaAccountService is the real implementation.
  - MockAccountService lives in tests/ for unit testing.

The account snapshot is used by calculators and validators.
Loops must NOT hold any lock during Alpaca calls — fetch first, then lock.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from tenacity import (
    retry,
    wait_exponential,
    stop_after_attempt,
    retry_if_exception_type,
)

from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus

from app.datasource.alpaca_gateway import AlpacaGateway
from app.utils.logger import logger
from app.utils.safe_number import safe_float
from app.utils.time_utils import utc_now


# ---------------------------------------------------------------------------
# Base interface
# ---------------------------------------------------------------------------

class BaseAccountService(ABC):
    """Abstract interface for account data providers."""

    @abstractmethod
    def get_account_snapshot(self) -> dict:
        """
        Return a compact account dict:
            {equity, cash, buying_power, portfolio_value,
             day_pnl, day_pnl_pct, open_position_count,
             trading_blocked, account_blocked, status, fetched_at}
        """

    @abstractmethod
    def get_positions(self) -> list[dict]:
        """
        Return all open positions as a list of dicts:
            {symbol, qty, side, avg_entry_price, market_value,
             unrealized_pl, unrealized_plpc, current_price}
        """

    @abstractmethod
    def get_open_orders(self) -> list[dict]:
        """Return all open Alpaca orders as a list of dicts."""

    @abstractmethod
    def get_raw_open_orders(self) -> list[Any]:
        """Return raw Alpaca order objects."""

    @abstractmethod
    def get_position(self, symbol: str) -> Optional[dict]:
        """Return position dict for *symbol*, or None if not held."""

    @abstractmethod
    def is_market_closing_soon(self, buffer_minutes: int = 15) -> bool:
        """Return True if US equity market is closing within buffer_minutes."""


# ---------------------------------------------------------------------------
# Alpaca implementation
# ---------------------------------------------------------------------------

class AlpacaAccountService(BaseAccountService):
    """
    Real account service backed by Alpaca's TradingClient.

    All external calls have tenacity retry for transient errors.
    """

    def __init__(self, gateway: AlpacaGateway) -> None:
        self._client = gateway.trading_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_account_snapshot(self) -> dict:
        try:
            account = self._fetch_account()
            equity = safe_float(account.equity, 0.0)
            cash = safe_float(account.cash, 0.0)
            buying_power = safe_float(account.buying_power, 0.0)
            portfolio_value = safe_float(account.portfolio_value, 0.0)

            return {
                "equity": equity,
                "cash": cash,
                "buying_power": buying_power,
                "portfolio_value": portfolio_value,
                "day_pnl": safe_float(getattr(account, "equity_change", 0.0), 0.0),
                "day_pnl_pct": safe_float(getattr(account, "equity_change_percent", 0.0), 0.0),
                "trading_blocked": bool(account.trading_blocked),
                "account_blocked": bool(account.account_blocked),
                "status": str(account.status.value) if hasattr(account.status, "value") else str(account.status),
                "fetched_at": utc_now(),
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("get_account_snapshot failed: {}", exc)
            return {}

    def get_positions(self) -> list[dict]:
        try:
            raw_positions = self._fetch_positions()
            result = []
            for pos in raw_positions:
                result.append({
                    "symbol": str(pos.symbol),
                    "qty": safe_float(pos.qty, 0.0),
                    "side": str(pos.side.value) if hasattr(pos.side, "value") else str(pos.side),
                    "avg_entry_price": safe_float(pos.avg_entry_price),
                    "market_value": safe_float(pos.market_value),
                    "unrealized_pl": safe_float(pos.unrealized_pl),
                    "unrealized_plpc": safe_float(pos.unrealized_plpc),
                    "current_price": safe_float(pos.current_price),
                })
            return result
        except Exception as exc:  # noqa: BLE001
            logger.error("get_positions failed: {}", exc)
            return []

    def get_open_orders(self) -> list[dict]:
        try:
            raw_orders = self._fetch_open_orders()
            result = []
            for order in raw_orders:
                result.append({
                    "id": str(order.id),
                    "client_order_id": str(order.client_order_id),
                    "symbol": str(order.symbol),
                    "qty": safe_float(order.qty),
                    "filled_qty": safe_float(order.filled_qty, 0.0),
                    "side": str(order.side.value) if hasattr(order.side, "value") else str(order.side),
                    "order_type": str(order.order_type.value) if hasattr(order.order_type, "value") else str(order.order_type),
                    "status": str(order.status.value) if hasattr(order.status, "value") else str(order.status),
                    "submitted_at": str(order.submitted_at) if order.submitted_at else None,
                })
            return result
        except Exception as exc:  # noqa: BLE001
            logger.error("get_open_orders failed: {}", exc)
            return []

    def get_raw_open_orders(self) -> list[Any]:
        try:
            return self._fetch_open_orders()
        except Exception as exc:
            logger.error("get_raw_open_orders failed: {}", exc)
            return []

    def get_position(self, symbol: str) -> Optional[dict]:
        positions = self.get_positions()
        for pos in positions:
            if pos.get("symbol") == symbol:
                return pos
        return None

    def is_market_closing_soon(self, buffer_minutes: int = 15) -> bool:
        """
        Check Alpaca Clock to see if next_close is within buffer_minutes.
        Returns False if error or if it's currently crypto time (market closed).
        """
        try:
            clock = self._client.get_clock()
            if not clock.is_open:
                return False  # Already closed
            
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            time_until_close = clock.next_close - now
            
            is_soon = time_until_close.total_seconds() < (buffer_minutes * 60)
            if is_soon:
                logger.warning("Market is closing in {} seconds. Buffer triggered.", int(time_until_close.total_seconds()))
            return is_soon
        except Exception as exc:
            logger.error("is_market_closing_soon failed: {}", exc)
            return False

    # ------------------------------------------------------------------
    # Retried internal helpers
    # ------------------------------------------------------------------

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _fetch_account(self):
        return self._client.get_account()

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _fetch_positions(self):
        return self._client.get_all_positions()

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _fetch_open_orders(self):
        req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
        return self._client.get_orders(filter=req)
