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
from typing import Any

from app.utils.logger import logger
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
                "sl": risk.get("stop_loss"),
                "tp": risk.get("take_profit"),
                "rr": risk.get("rr_ratio"),
            }
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

    def build_exit_prompt(self, symbol: str, position: dict, market_data: dict) -> str:
        """
        Build a compact JSON prompt for an exit decision.
        """
        payload = {
            "sym": symbol,
            "pos": {
                "qty": position.get("qty"),
                "entry": position.get("avg_entry_price"),
                "pnl": position.get("unrealized_pl"),
                "pnl_pct": position.get("unrealized_plpc"),
            },
            "px": market_data.get("latest_price"),
            # Add any exit-specific indicators if needed
        }
        
        prompt = json.dumps(payload, separators=(",", ":"))
        
        if len(prompt) > MAX_INPUT_CHARS_EXIT:
            prompt = prompt[:MAX_INPUT_CHARS_EXIT]
            
        return prompt
