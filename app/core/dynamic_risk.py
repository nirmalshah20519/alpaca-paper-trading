from __future__ import annotations

from app.utils.safe_number import safe_float
from config.risk_limits import (
    DYNAMIC_TRADE_BUDGET_PCT_OF_BUYING_POWER,
    DYNAMIC_TRADE_BUDGET_MIN_DOLLARS,
    DYNAMIC_TRADE_BUDGET_MAX_DOLLARS,
    DYNAMIC_CRYPTO_LIQUIDITY_MULTIPLIER,
    DYNAMIC_CRYPTO_LIQUIDITY_MIN_DOLLARS,
    DYNAMIC_CRYPTO_LIQUIDITY_MAX_DOLLARS,
    DYNAMIC_STOCK_LIQUIDITY_MULTIPLIER,
    DYNAMIC_STOCK_LIQUIDITY_MIN_SHARES,
    DYNAMIC_STOCK_LIQUIDITY_MAX_SHARES,
)
from config.settings import MAX_DOLLAR_PER_TRADE


def _numeric_from_account(account_data: dict | None, key: str) -> float | None:
    raw_value = (account_data or {}).get(key)
    if not isinstance(raw_value, (int, float, str)):
        return None
    return safe_float(raw_value)


def dynamic_trade_budget(account_data: dict | None) -> float:
    buying_power = _numeric_from_account(account_data, "buying_power")
    if buying_power is None:
        buying_power = _numeric_from_account(account_data, "cash")
    if buying_power is None or buying_power <= 0:
        return MAX_DOLLAR_PER_TRADE

    budget = buying_power * DYNAMIC_TRADE_BUDGET_PCT_OF_BUYING_POWER
    budget = max(budget, DYNAMIC_TRADE_BUDGET_MIN_DOLLARS)
    budget = min(budget, DYNAMIC_TRADE_BUDGET_MAX_DOLLARS, buying_power)
    return budget


def dynamic_crypto_liquidity_floor(account_data: dict | None) -> float:
    budget = dynamic_trade_budget(account_data)
    floor_value = budget * DYNAMIC_CRYPTO_LIQUIDITY_MULTIPLIER
    floor_value = max(floor_value, DYNAMIC_CRYPTO_LIQUIDITY_MIN_DOLLARS)
    floor_value = min(floor_value, DYNAMIC_CRYPTO_LIQUIDITY_MAX_DOLLARS)
    return float(floor_value)


def dynamic_stock_liquidity_floor(account_data: dict | None) -> float:
    budget = dynamic_trade_budget(account_data)
    floor_value = budget * DYNAMIC_STOCK_LIQUIDITY_MULTIPLIER
    floor_value = max(floor_value, float(DYNAMIC_STOCK_LIQUIDITY_MIN_SHARES))
    floor_value = min(floor_value, float(DYNAMIC_STOCK_LIQUIDITY_MAX_SHARES))
    return float(floor_value)
