"""
app/calculator/pnl_risk_calculator.py

PnLRiskCalculator — computes deterministic open-position P&L risk context.

This calculator does not decide whether to exit. It produces compact,
safe metrics for the exit LLM prompt so the model can reason about the
current trade state without calculating P&L itself.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.utils.safe_number import safe_float
from config.strategy_params import (
    EXIT_ATR_PERIOD,
    EXIT_BREAKEVEN_PROFIT_TRIGGER_PCT,
    EXIT_LOSS_CONTROL_PCT,
    EXIT_MAX_PROFIT_GIVEBACK_RATIO,
    EXIT_PROFIT_PROTECTION_TRIGGER_PCT,
    EXIT_TRAILING_ATR_MULT,
    STOP_LOSS_ATR_MULT,
)


class PnLRiskCalculator:
    """
    Computes P&L-aware risk signals for an open position.

    The outputs are designed for compact JSON:
      - current unrealized P&L and P&L %
      - approximate recent MFE/MAE from the supplied bars
      - profit giveback from recent favorable excursion
      - ATR-normalized R proxy and trailing-stop context
      - a conservative risk_state label
    """

    def compute(self, position: dict[str, Any], market_data: dict[str, Any]) -> dict[str, Any]:
        symbol = str(position.get("symbol") or market_data.get("symbol") or "")
        qty = abs(safe_float(position.get("qty"), 0.0) or 0.0)
        entry = safe_float(position.get("avg_entry_price"))
        current = (
            safe_float(market_data.get("latest_price"))
            or safe_float(position.get("current_price"))
        )

        if not symbol or qty <= 0 or not entry or not current or entry <= 0 or current <= 0:
            return {}

        is_short = self._is_short(position)
        direction = -1.0 if is_short else 1.0
        pnl_per_unit = (current - entry) * direction
        calc_pnl = pnl_per_unit * qty
        pnl_amount = safe_float(position.get("unrealized_pl"), calc_pnl) or calc_pnl
        pnl_pct = safe_float(position.get("unrealized_plpc"))
        if pnl_pct is None:
            pnl_pct = pnl_per_unit / entry

        bars = market_data.get("bars")
        atr = self._compute_atr(bars, EXIT_ATR_PERIOD)
        recent_high, recent_low = self._recent_extremes(bars)

        favorable_price, adverse_price = self._favorable_adverse_prices(
            entry=entry,
            current=current,
            recent_high=recent_high,
            recent_low=recent_low,
            is_short=is_short,
        )

        if is_short:
            mfe_pct = max((entry - favorable_price) / entry, pnl_pct, 0.0)
            mae_pct = min((entry - adverse_price) / entry, pnl_pct, 0.0)
            trail_stop = (
                favorable_price + (atr * EXIT_TRAILING_ATR_MULT)
                if atr is not None
                else None
            )
            trail_breached = bool(trail_stop is not None and current >= trail_stop)
            breakeven_breached = bool(
                mfe_pct >= EXIT_BREAKEVEN_PROFIT_TRIGGER_PCT and current >= entry
            )
        else:
            mfe_pct = max((favorable_price - entry) / entry, pnl_pct, 0.0)
            mae_pct = min((adverse_price - entry) / entry, pnl_pct, 0.0)
            trail_stop = (
                favorable_price - (atr * EXIT_TRAILING_ATR_MULT)
                if atr is not None
                else None
            )
            trail_breached = bool(trail_stop is not None and current <= trail_stop)
            breakeven_breached = bool(
                mfe_pct >= EXIT_BREAKEVEN_PROFIT_TRIGGER_PCT and current <= entry
            )

        giveback_pct = max(mfe_pct - max(pnl_pct, 0.0), 0.0)
        giveback_ratio = giveback_pct / mfe_pct if mfe_pct > 0 else 0.0

        risk_unit = (atr or 0.0) * STOP_LOSS_ATR_MULT
        r_multiple = pnl_per_unit / risk_unit if risk_unit > 0 else None
        pnl_atr = pnl_per_unit / atr if atr and atr > 0 else None
        atr_pct = atr / current if atr and current > 0 else None

        protect_profit = (
            pnl_pct >= EXIT_PROFIT_PROTECTION_TRIGGER_PCT
            or (r_multiple is not None and r_multiple >= 1.0)
        )

        risk_state, exit_pressure = self._classify_state(
            pnl_pct=pnl_pct,
            mfe_pct=mfe_pct,
            giveback_ratio=giveback_ratio,
            protect_profit=protect_profit,
            trail_breached=trail_breached,
            breakeven_breached=breakeven_breached,
            r_multiple=r_multiple,
        )

        return self._compact(
            {
                "sym": symbol,
                "side": "short" if is_short else "long",
                "pnl": pnl_amount,
                "pnl_pct": pnl_pct,
                "pnl_unit": pnl_per_unit,
                "r_mult": r_multiple,
                "pnl_atr": pnl_atr,
                "atr": atr,
                "atr_pct": atr_pct,
                "mfe_pct": mfe_pct,
                "mae_pct": mae_pct,
                "giveback_pct": giveback_pct,
                "giveback_ratio": giveback_ratio,
                "trail_stop": trail_stop,
                "trail_breached": trail_breached,
                "breakeven_breached": breakeven_breached,
                "protect_profit": protect_profit,
                "risk_state": risk_state,
                "exit_pressure": exit_pressure,
            }
        )

    def _classify_state(
        self,
        *,
        pnl_pct: float,
        mfe_pct: float,
        giveback_ratio: float,
        protect_profit: bool,
        trail_breached: bool,
        breakeven_breached: bool,
        r_multiple: float | None,
    ) -> tuple[str, str]:
        if pnl_pct <= EXIT_LOSS_CONTROL_PCT or (
            r_multiple is not None and r_multiple <= -1.0
        ):
            return "LOSS_CONTROL", "high"

        if protect_profit and trail_breached:
            return "TRAIL_BREACH", "high"

        if protect_profit and breakeven_breached:
            return "BREAKEVEN_BREACH", "high"

        if (
            mfe_pct >= EXIT_PROFIT_PROTECTION_TRIGGER_PCT
            and giveback_ratio >= EXIT_MAX_PROFIT_GIVEBACK_RATIO
        ):
            return "PROFIT_GIVEBACK", "high"

        if protect_profit:
            return "PROTECT_PROFIT", "medium"

        if pnl_pct > 0:
            return "PROFIT_HEALTHY", "low"

        return "WATCH", "medium"

    def _is_short(self, position: dict[str, Any]) -> bool:
        side = str(position.get("side") or "").lower()
        qty = safe_float(position.get("qty"), 0.0) or 0.0
        return "short" in side or qty < 0

    def _favorable_adverse_prices(
        self,
        *,
        entry: float,
        current: float,
        recent_high: float | None,
        recent_low: float | None,
        is_short: bool,
    ) -> tuple[float, float]:
        if is_short:
            favorable = min(v for v in (entry, current, recent_low) if v is not None)
            adverse = max(v for v in (entry, current, recent_high) if v is not None)
        else:
            favorable = max(v for v in (entry, current, recent_high) if v is not None)
            adverse = min(v for v in (entry, current, recent_low) if v is not None)
        return favorable, adverse

    def _recent_extremes(self, bars: Any) -> tuple[float | None, float | None]:
        if not isinstance(bars, pd.DataFrame) or bars.empty:
            return None, None
        recent_high = safe_float(bars.get("high", pd.Series(dtype=float)).max())
        recent_low = safe_float(bars.get("low", pd.Series(dtype=float)).min())
        return recent_high, recent_low

    def _compute_atr(self, bars: Any, period: int) -> float | None:
        if not isinstance(bars, pd.DataFrame) or len(bars) < period + 1:
            return None
        try:
            df = bars.sort_index()
            prev_close = df["close"].shift(1)
            tr = pd.concat(
                [
                    df["high"] - df["low"],
                    (df["high"] - prev_close).abs(),
                    (df["low"] - prev_close).abs(),
                ],
                axis=1,
            ).max(axis=1)
            return safe_float(tr.rolling(window=period).mean().iloc[-1])
        except Exception:
            return None

    def _compact(self, values: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for key, value in values.items():
            if isinstance(value, bool) or isinstance(value, str):
                compact[key] = value
                continue

            clean = safe_float(value)
            if clean is None:
                compact[key] = None
                continue

            if key in {"pnl_pct", "atr_pct", "mfe_pct", "mae_pct", "giveback_pct", "giveback_ratio"}:
                compact[key] = round(clean, 4)
            elif key in {"atr", "pnl_unit", "trail_stop"}:
                compact[key] = round(clean, 6)
            else:
                compact[key] = round(clean, 2)
        return compact
