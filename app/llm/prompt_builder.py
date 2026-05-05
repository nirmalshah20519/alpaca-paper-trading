"""
app/llm/prompt_builder.py

PromptBuilder — constructs compact JSON payloads for the LLM.

Design rules:
  - Aggregates technical indicators, market data, and risk levels.
  - Returns a stringified JSON (compact, no extra whitespace).
  - Enforces character/token limits by truncating data if necessary.
"""

from __future__ import annotations

import json
from math import floor
from typing import Any

from app.utils.logger import logger
from app.utils.safe_number import safe_float
from app.core.dynamic_risk import dynamic_trade_budget
from config.risk_limits import ALLOW_SHORT_SELLING
from config.settings import MAX_DOLLAR_PER_TRADE, ALLOW_FRACTIONAL_STOCK_QTY
from config.llm_config import MAX_INPUT_CHARS_ENTRY, MAX_INPUT_CHARS_EXIT


class PromptBuilder:
    """
    Constructs the prompt payload for the LLM.
    """

    def build_entry_prompt(self, analysis: dict) -> str:
        """
        Build a compact JSON prompt for an entry decision.
        """
        # Extract the most important data
        symbol = analysis.get("symbol")
        price = analysis.get("entry_price")
        indicators = analysis.get("indicators", {})
        risk = analysis.get("risk", {})
        liquidity = analysis.get("liquidity") or {}
        sizing = analysis.get("sizing") or {}
        account = analysis.get("account") or {}
        qty_max = self._entry_qty_max(symbol, price, sizing, account)
        buy_risk = risk.get("buy") or risk
        sell_risk = risk.get("sell") or {}
        
        # Build a minimal dict to save tokens
        payload = {
            "sym": symbol,
            "px": price,
            "ind": {
                "rsi": indicators.get("rsi_14"),
                "sma20": indicators.get("sma_20"),
                "sma50": indicators.get("sma_50"),
                "atr": indicators.get("atr_14"),
                "vol": indicators.get("volatility_20"),
            },
            "risk": {
                "buy": self._compact_risk(buy_risk),
                "sell": self._compact_risk(sell_risk) if ALLOW_SHORT_SELLING else None,
            },
            "calc": {
                "qty_max": qty_max,
            },
            "liq": liquidity.get("is_liquid"),
            "spr": liquidity.get("spread_pct"),
            "short_allowed": ALLOW_SHORT_SELLING,
        }
        
        # Stringify (compact)
        prompt = json.dumps(payload, separators=(",", ":"))
        
        # Check budget
        if len(prompt) > MAX_INPUT_CHARS_ENTRY:
            logger.warning(
                "Prompt for {} exceeds character budget ({} > {}). Truncating.",
                symbol, len(prompt), MAX_INPUT_CHARS_ENTRY
            )
            # Extremely rare for this minimal payload, but good for robustness
            prompt = prompt[:MAX_INPUT_CHARS_ENTRY]
            
        return prompt

    def _compact_risk(self, risk: dict) -> dict:
        return {
            "sl": risk.get("stop_loss"),
            "tp": risk.get("take_profit"),
            "rr": risk.get("rr_ratio"),
        }

    def _entry_qty_max(self, symbol: str | None, price: Any, sizing: dict, account: dict | None) -> float:
        """
        Quantity cap exposed to the LLM.

        Prefer deterministic calculator sizing when available, but also cap by
        the same per-trade dollar limit the entry loop enforces after the LLM.
        """
        trade_cap_qty = self._trade_cap_qty(symbol, price, account)
        sizing_qty = safe_float(sizing.get("qty"))

        if sizing_qty is None:
            return trade_cap_qty
        if trade_cap_qty <= 0:
            return max(sizing_qty, 0.0)
        return max(min(sizing_qty, trade_cap_qty), 0.0)

    def _trade_cap_qty(self, symbol: str | None, price: Any, account: dict | None) -> float:
        clean_price = safe_float(price)
        if not clean_price or clean_price <= 0:
            return 0.0

        trade_budget = dynamic_trade_budget(account)
        if trade_budget <= 0:
            trade_budget = MAX_DOLLAR_PER_TRADE
        raw_qty = trade_budget / clean_price
        if symbol and "/" in symbol:
            return floor(raw_qty * 10_000) / 10_000
        if ALLOW_FRACTIONAL_STOCK_QTY:
            return floor(raw_qty * 10_000) / 10_000
        return float(int(raw_qty))

    def build_exit_prompt(
        self,
        symbol: str,
        position: dict,
        market_data: dict,
        pnl_risk: dict | None = None,
    ) -> str:
        """
        Build a compact JSON prompt for an exit decision.
        """
        payload = {
            "sym": symbol,
            "pos": {
                "qty": position.get("qty"),
                "side": position.get("side"),
                "entry": position.get("avg_entry_price"),
                "pnl": position.get("unrealized_pl"),
                "pnl_pct": position.get("unrealized_plpc"),
                "target": position.get("target_price") or position.get("target"),
                "stop": position.get("stop_loss_price") or position.get("stop"),
                "target_hit": self._exit_target_hit(position, market_data),
                "stop_hit": self._exit_stop_hit(position, market_data),
            },
            "px": market_data.get("latest_price"),
        }

        if pnl_risk:
            payload["pnl_risk"] = {
                "state": pnl_risk.get("risk_state"),
                "pressure": pnl_risk.get("exit_pressure"),
                "pnl": pnl_risk.get("pnl"),
                "pnl_pct": pnl_risk.get("pnl_pct"),
                "r": pnl_risk.get("r_mult"),
                "pnl_atr": pnl_risk.get("pnl_atr"),
                "mfe_pct": pnl_risk.get("mfe_pct"),
                "giveback_pct": pnl_risk.get("giveback_pct"),
                "giveback_ratio": pnl_risk.get("giveback_ratio"),
                "trail_stop": pnl_risk.get("trail_stop"),
                "trail_breached": pnl_risk.get("trail_breached"),
                "breakeven_breached": pnl_risk.get("breakeven_breached"),
                "protect_profit": pnl_risk.get("protect_profit"),
                "atr_pct": pnl_risk.get("atr_pct"),
            }
        
        prompt = json.dumps(payload, separators=(",", ":"))
        
        if len(prompt) > MAX_INPUT_CHARS_EXIT:
            logger.warning(
                "Exit prompt for {} exceeds character budget ({} > {}). Dropping pnl_risk context.",
                symbol, len(prompt), MAX_INPUT_CHARS_EXIT
            )
            payload.pop("pnl_risk", None)
            prompt = json.dumps(payload, separators=(",", ":"))
            if len(prompt) > MAX_INPUT_CHARS_EXIT:
                prompt = prompt[:MAX_INPUT_CHARS_EXIT]
            
        return prompt

    def _exit_target_hit(self, position: dict, market_data: dict) -> bool:
        current = safe_float(market_data.get("latest_price"))
        target = safe_float(position.get("target_price") or position.get("target"))
        if current is None or target is None:
            return False
        return current <= target if self._is_short_position(position) else current >= target

    def _exit_stop_hit(self, position: dict, market_data: dict) -> bool:
        current = safe_float(market_data.get("latest_price"))
        stop = safe_float(position.get("stop_loss_price") or position.get("stop"))
        if current is None or stop is None:
            return False
        return current >= stop if self._is_short_position(position) else current <= stop

    def _is_short_position(self, position: dict) -> bool:
        side = str(position.get("side") or "").lower()
        qty = safe_float(position.get("qty"), 0.0) or 0.0
        return "short" in side or qty < 0
