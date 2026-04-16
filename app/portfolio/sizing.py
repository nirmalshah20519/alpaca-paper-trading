"""Deterministic sizing helpers for portfolio allocation."""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal


def floor_quantity(quantity: Decimal) -> Decimal:
    """Round quantity down to a simple whole-share quantity for MVP equities."""
    return quantity.quantize(Decimal("1"), rounding=ROUND_DOWN)


def quantity_for_budget(entry_price: Decimal, budget: Decimal) -> Decimal:
    """Convert a notional budget into a whole-share quantity."""
    if entry_price <= 0 or budget <= 0:
        return Decimal("0")
    return floor_quantity(budget / entry_price)
