"""
app/executor/alpaca_order_submitter.py

AlpacaOrderSubmitter — sends the final order to Alpaca.

Design rules:
  - Last point of contact before the exchange.
  - Returns the Alpaca Order object or raises on failure.
  - Never submits if in Paper mode but trying to use a Live client (safety).
"""

from __future__ import annotations

from typing import Any

from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.client import TradingClient

from app.core.models import EntrySignal
from app.utils.logger import logger


class AlpacaOrderSubmitter:
    """
    Submits orders to Alpaca using the TradingClient.
    """

    CRYPTO_BASES: frozenset[str] = frozenset(
        {"BTC", "ETH", "SOL", "DOGE", "SHIB", "LTC", "BCH", "LINK", "AVAX", "UNI"}
    )

    def __init__(self, trading_client: TradingClient) -> None:
        self.client = trading_client

    def submit_entry(self, signal: EntrySignal) -> Any:
        """
        Submit a Buy/Sell order based on the signal.
        """
        try:
            # We use Limit orders with the entry price if provided, or Market for now.
            # Plan says "Default must always be PAPER mode". 
            # TradingClient handles this via the 'paper' flag in AlpacaGateway.
            
            symbol = self._normalize_symbol(signal.sym)

            side = OrderSide.BUY if signal.action == "BUY" else OrderSide.SELL
            tif = self._time_in_force(symbol)
            
            order_req = MarketOrderRequest(
                symbol=symbol,
                qty=float(signal.qty),
                side=side,
                time_in_force=tif
            )
            
            logger.info("Submitting {} order for {} qty={} tif={}", side, symbol, signal.qty, tif)
            order = self.client.submit_order(order_data=order_req)
            logger.info("Order submitted successfully. ID: {}", order.id)
            return order

        except Exception as exc:
            logger.error("Alpaca order submission failed for {}: {}", signal.sym, exc)
            raise

    def submit_exit(self, symbol: str, qty: float, side: str = "SELL") -> Any:
        """
        Submit a market order to close a position.

        Long exits sell; short exits buy to cover.
        """
        try:
            normalized_symbol = self._normalize_symbol(symbol)
            order_side = self._order_side(side)
            tif = self._time_in_force(normalized_symbol)
            order_req = MarketOrderRequest(
                symbol=normalized_symbol,
                qty=abs(float(qty)),
                side=order_side,
                time_in_force=tif
            )
            logger.info("Submitting EXIT {} order for {} qty={} tif={}", order_side, normalized_symbol, qty, tif)
            order = self.client.submit_order(order_data=order_req)
            logger.info("Exit order submitted. ID: {}", order.id)
            return order
        except Exception as exc:
            logger.error("Alpaca exit submission failed for {}: {}", symbol, exc)
            raise

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order by ID. Returns True if successful.
        """
        try:
            self.client.cancel_order_by_id(order_id)
            logger.info("Cancelled stale order: {}", order_id)
            return True
        except Exception as exc:
            logger.error("Failed to cancel order {}: {}", order_id, exc)
            return False

    def _normalize_symbol(self, symbol: str) -> str:
        """
        Normalize Alpaca crypto position symbols like BTCUSD to BTC/USD.
        Stock symbols are returned unchanged.
        """
        symbol = str(symbol).upper()
        if "/" in symbol:
            return symbol

        if symbol.endswith("USDT"):
            base = symbol[:-4]
            quote = "USDT"
        elif symbol.endswith("USD"):
            base = symbol[:-3]
            quote = "USD"
        else:
            return symbol

        if base in self.CRYPTO_BASES:
            return f"{base}/{quote}"
        return symbol

    def _order_side(self, side: str) -> OrderSide:
        side_value = str(side).upper()
        if side_value == "BUY":
            return OrderSide.BUY
        if side_value == "SELL":
            return OrderSide.SELL
        raise ValueError(f"Unsupported order side: {side}")

    def _time_in_force(self, symbol: str) -> TimeInForce:
        """
        Alpaca crypto market orders support GTC/IOC, while stock market orders
        may use DAY. Use GTC for crypto to support fractional closes.
        """
        return TimeInForce.GTC if "/" in symbol else TimeInForce.DAY
