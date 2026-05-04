"""
tests/test_order_submitter.py

Regression tests for Alpaca order mapping.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from alpaca.trading.enums import TimeInForce

from app.executor.alpaca_order_submitter import AlpacaOrderSubmitter


def test_submit_exit_normalizes_unslashed_crypto_and_uses_gtc():
    client = MagicMock()
    client.submit_order.return_value = SimpleNamespace(id="ord-1", client_order_id="cid-1")
    submitter = AlpacaOrderSubmitter(client)

    submitter.submit_exit("BTCUSD", 1.00996875)

    order_req = client.submit_order.call_args.kwargs["order_data"]
    assert order_req.symbol == "BTC/USD"
    assert order_req.time_in_force == TimeInForce.GTC
    assert float(order_req.qty) == 1.00996875


def test_submit_exit_keeps_stock_day_tif():
    client = MagicMock()
    client.submit_order.return_value = SimpleNamespace(id="ord-2", client_order_id="cid-2")
    submitter = AlpacaOrderSubmitter(client)

    submitter.submit_exit("AMD", 2)

    order_req = client.submit_order.call_args.kwargs["order_data"]
    assert order_req.symbol == "AMD"
    assert order_req.time_in_force == TimeInForce.DAY
