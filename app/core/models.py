"""
app/core/models.py

Pydantic data models shared across the service.

Phase 1/2: LLM signal schemas are defined here.
Executor, validator, and storage models will be added in later phases.
"""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# LLM Signal Schemas  (plan §9)
# ---------------------------------------------------------------------------

class EntrySignal(BaseModel):
    """
    JSON output expected from the LLM for entry decisions.

    BUY / SELL:  qty > 0, target is not None, stop is not None.
    SKIP:        qty = 0, target and stop may be null.
    """

    sym: str
    action: Literal["BUY", "SELL", "SKIP"]
    conf: float = Field(ge=0.0, le=1.0)
    qty: float = Field(ge=0.0)
    target: Optional[float] = None
    stop: Optional[float] = None
    reason_code: str


class ExitSignal(BaseModel):
    """
    JSON output expected from the LLM for exit decisions.
    """

    sym: str
    action: Literal["HOLD", "COMPLETE"]
    conf: float = Field(ge=0.0, le=1.0)
    reason_code: str


# ---------------------------------------------------------------------------
# Validation Result (used by SignalValidator)
# ---------------------------------------------------------------------------

class ValidationResult(BaseModel):
    """
    Outcome of running an entry or exit signal through the validator.
    """

    validated: bool
    reason: Optional[str] = None   # human-readable rejection reason


# ---------------------------------------------------------------------------
# Execution Result (used by TradeExecutor — placeholder for Phase 7)
# ---------------------------------------------------------------------------

class ExecutionResult(BaseModel):
    """
    Record of a submitted Alpaca order. Returned by TradeExecutor.
    """

    local_trade_id: str
    alpaca_order_id: Optional[str] = None
    client_order_id: str
    symbol: str
    side: str
    qty: float
    submitted_at: str
    status: str  # e.g. "submitted", "filled", "failed"
    target_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    error: Optional[str] = None
