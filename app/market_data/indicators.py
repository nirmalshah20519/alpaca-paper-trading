"""Lightweight indicator helpers for deterministic strategies."""

from __future__ import annotations

from decimal import Decimal


def ema(values: list[Decimal], period: int) -> Decimal | None:
    """Calculate a simple exponential moving average."""
    if len(values) < period or period <= 0:
        return None
    multiplier = Decimal("2") / Decimal(period + 1)
    result = sum(values[:period], Decimal("0")) / Decimal(period)
    for value in values[period:]:
        result = ((value - result) * multiplier) + result
    return result


def rsi(values: list[Decimal], period: int = 14) -> Decimal | None:
    """Calculate RSI using closing prices."""
    if len(values) <= period:
        return None
    gains = Decimal("0")
    losses = Decimal("0")
    for index in range(1, period + 1):
        delta = values[index] - values[index - 1]
        if delta >= 0:
            gains += delta
        else:
            losses += abs(delta)
    average_gain = gains / Decimal(period)
    average_loss = losses / Decimal(period)
    if average_loss == 0:
        return Decimal("100")
    rs = average_gain / average_loss
    return Decimal("100") - (Decimal("100") / (Decimal("1") + rs))


def volatility_pct(values: list[Decimal], lookback: int = 10) -> Decimal | None:
    """Estimate recent percentage range volatility."""
    if len(values) < lookback:
        return None
    window = values[-lookback:]
    highest = max(window)
    lowest = min(window)
    if lowest <= 0:
        return None
    return (highest - lowest) / lowest
