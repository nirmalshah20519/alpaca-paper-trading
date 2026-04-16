"""Map approved proposals into Alpaca paper order requests."""

from __future__ import annotations

from dataclasses import dataclass

from alpaca.trading.enums import OrderClass, OrderSide, OrderType, TimeInForce
from alpaca.trading.requests import (
    LimitOrderRequest,
    MarketOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)

from app.core.trading import TradeApprovalDecision, TradeProposal


@dataclass(slots=True)
class OrderBuildResult:
    """Built broker request plus derived client order id."""

    client_order_id: str
    order_request: LimitOrderRequest | MarketOrderRequest


class OrderFactory:
    """Create protected paper orders from approved proposals."""

    def build(
        self,
        proposal: TradeProposal,
        approval: TradeApprovalDecision,
        *,
        client_order_id: str,
    ) -> OrderBuildResult:
        """Build a protected bracket order request."""
        if proposal.stop_price <= 0:
            raise ValueError("Cannot build order without stop-loss protection.")

        side = OrderSide.BUY if proposal.side.value == "buy" else OrderSide.SELL
        take_profit = TakeProfitRequest(limit_price=float(proposal.take_profit_price))
        stop_loss = StopLossRequest(stop_price=float(proposal.stop_price))
        common = {
            "symbol": proposal.symbol,
            "qty": float(approval.approved_qty),
            "side": side,
            "time_in_force": TimeInForce.DAY,
            "order_class": OrderClass.BRACKET,
            "client_order_id": client_order_id,
            "take_profit": take_profit,
            "stop_loss": stop_loss,
        }

        entry_style = proposal.metadata.get("entry_style", "limit")
        if "market" in str(entry_style):
            request = MarketOrderRequest(type=OrderType.MARKET, **common)
        else:
            request = LimitOrderRequest(
                type=OrderType.LIMIT,
                limit_price=float(proposal.entry_price),
                **common,
            )
        return OrderBuildResult(client_order_id=client_order_id, order_request=request)
