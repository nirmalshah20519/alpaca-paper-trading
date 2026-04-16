"""Idempotency helpers for trade intents and order submission."""

from __future__ import annotations

import hashlib
from datetime import datetime

from app.core.enums import Side


def generate_trade_intent_id(
    strategy_id: str,
    symbol: str,
    side: Side,
    bar_timestamp: datetime,
    thesis_version: str,
) -> str:
    """Create a deterministic trade intent id for restart-safe deduplication."""
    raw = "|".join(
        [
            strategy_id.strip().lower(),
            symbol.strip().upper(),
            side.value,
            bar_timestamp.isoformat(),
            thesis_version.strip().lower(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_order_idempotency_key(trade_intent_id: str, attempt: int = 1) -> str:
    """Create a deterministic key for order-submission deduplication."""
    raw = f"{trade_intent_id}:{attempt}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
