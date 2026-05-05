"""
Opt-in live latency comparison for local LFM vs OpenAI GPT.

This test intentionally does not run in the normal suite. It loads the local
model and calls the OpenAI API, so enable it only when you want a real benchmark:

PowerShell:
    $env:RUN_LLM_LATENCY_TEST="1"
    python -m pytest tests\test_llm_latency.py -s -p no:cacheprovider
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import pytest
from dotenv import dotenv_values

from app.core.models import EntrySignal
from app.llm.prompt_builder import PromptBuilder
from config.llm_config import LLM_MODEL
from config.prompts import ENTRY_SYSTEM_PROMPT


@dataclass(frozen=True)
class LatencyResult:
    provider: str
    seconds: float
    signal: EntrySignal


@pytest.mark.timeout(1800)
def test_live_lfm_vs_openai_prompt_to_response_latency():
    if _env_value("RUN_LLM_LATENCY_TEST") != "1":
        pytest.skip("Set RUN_LLM_LATENCY_TEST=1 to run the live LFM/OpenAI latency benchmark.")

    openai_key = _env_value("OPENAI_API_KEY")
    if not openai_key:
        pytest.skip("OPENAI_API_KEY is required for the OpenAI side of this comparison.")

    prompt = _benchmark_entry_prompt()

    from app.llm.lfm_provider import LFMProvider
    from app.llm.openai_provider import OpenAIProvider

    lfm_model_id = _env_value("LFM_MODEL_ID") or "LiquidAI/LFM2.5-1.2B-Thinking"

    load_start = time.perf_counter()
    lfm_provider = LFMProvider(model_id=lfm_model_id)
    lfm_load_seconds = time.perf_counter() - load_start

    openai_provider = OpenAIProvider(api_key=openai_key)

    lfm = _time_provider("LFM", lfm_provider, prompt)
    openai = _time_provider("OpenAI", openai_provider, prompt)

    assert isinstance(lfm.signal, EntrySignal)
    assert isinstance(openai.signal, EntrySignal)
    assert lfm.signal.sym == "AAPL"
    assert openai.signal.sym == "AAPL"

    faster = min((lfm, openai), key=lambda result: result.seconds)
    slower = max((lfm, openai), key=lambda result: result.seconds)
    ratio = slower.seconds / faster.seconds if faster.seconds > 0 else float("inf")

    print(
        "\nLLM prompt-to-response latency comparison"
        f"\n  prompt_chars={len(prompt)}"
        f"\n  lfm_model={lfm_model_id}"
        f"\n  openai_model={LLM_MODEL}"
        f"\n  lfm_model_load_s={lfm_load_seconds:.3f}"
        f"\n  LFM:    {lfm.seconds:.3f}s action={lfm.signal.action} conf={lfm.signal.conf:.2f} reason={lfm.signal.reason_code}"
        f"\n  OpenAI: {openai.seconds:.3f}s action={openai.signal.action} conf={openai.signal.conf:.2f} reason={openai.signal.reason_code}"
        f"\n  faster={faster.provider} slower={slower.provider} ratio={ratio:.2f}x"
    )


def _time_provider(provider_name: str, provider, prompt: str) -> LatencyResult:
    start = time.perf_counter()
    signal = provider.ask(prompt, ENTRY_SYSTEM_PROMPT, EntrySignal)
    seconds = time.perf_counter() - start
    return LatencyResult(provider=provider_name, seconds=seconds, signal=signal)


def _benchmark_entry_prompt() -> str:
    analysis = {
        "symbol": "AAPL",
        "entry_price": 150.0,
        "indicators": {
            "rsi_14": 48.0,
            "sma_20": 148.5,
            "sma_50": 145.0,
            "atr_14": 2.5,
            "volatility_20": 0.018,
        },
        "risk": {
            "buy": {
                "stop_loss": 145.0,
                "take_profit": 160.0,
                "rr_ratio": 2.0,
            },
            "sell": {},
        },
        "liquidity": {
            "is_liquid": True,
            "spread_pct": 0.0007,
        },
        "sizing": {
            "qty": 1.0,
        },
    }
    return PromptBuilder().build_entry_prompt(analysis)


def _env_value(key: str) -> str:
    value = os.environ.get(key)
    if value:
        return value.strip()

    file_value = dotenv_values(".env").get(key)
    return str(file_value or "").strip()
