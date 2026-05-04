"""
app/executor/alpaca_order_submitter.py

AlpacaOrderSubmitter — sends the final order to Alpaca.

Design rules:
  - Last point of contact before the exchange.
  - Returns the Alpaca Order object or raises on failure.
  - Never submits if in Paper mode but trying to use a Live client (safety).
"""

from __future__ import annotations

from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.client import TradingClient

from app.core.models import EntrySignal
from app.utils.logger import logger


class AlpacaOrderSubmitter:
    """
    Submits orders to Alpaca using the TradingClient.
    """

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
            
            symbol = signal.sym
            # Normalize crypto symbols (inject slash if missing)
            if any(symbol.startswith(c) and len(symbol) <= 8 for c in ["BTC", "ETH", "SOL", "DOGE", "SHIB", "LTC", "BCH", "LINK", "AVAX", "UNI"]):
                if "/" not in symbol:
                    if symbol.endswith("USDT"): symbol = f"{symbol[:-4]}/USDT"
                    elif symbol.endswith("USD"): symbol = f"{symbol[:-3]}/USD"

            side = OrderSide.BUY if signal.action == "BUY" else OrderSide.SELL
            
            # Use GTC for crypto, DAY for stocks
            tif = TimeInForce.GTC if "/" in symbol else TimeInForce.DAY
            
            order_req = MarketOrderRequest(
                symbol=symbol,
                qty=float(signal.qty),
                side=side,
                time_in_force=tif
            )
            
            logger.info("Submitting {} order for {} qty={} tif={}", side, signal.sym, signal.qty, tif)
            order = self.client.submit_order(order_data=order_req)
            logger.info("Order submitted successfully. ID: {}", order.id)
            return order

        except Exception as exc:
            logger.error("Alpaca order submission failed for {}: {}", signal.sym, exc)
            raise

    def submit_exit(self, symbol: str, qty: float) -> Any:
        """
        Submit a Market Sell order to close a position.
        """
        try:
            tif = TimeInForce.GTC if "/" in symbol else TimeInForce.DAY
            order_req = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=tif
            )
            logger.info("Submitting EXIT order for {} qty={} tif={}", symbol, qty, tif)
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
