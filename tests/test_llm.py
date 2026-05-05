"""
tests/test_llm.py

Tests for Phase 5: LLM integration and prompt building.
"""

import pytest
import json
from unittest.mock import MagicMock, patch

from app.llm.ask_llm import AskLLM
from app.llm.lfm_provider import LFMProvider
from app.llm.openai_provider import OpenAIProvider
from app.llm.prompt_builder import PromptBuilder
from app.core.models import EntrySignal, ExitSignal
from config.llm_config import MAX_OUTPUT_TOKENS_ENTRY, MAX_OUTPUT_TOKENS_EXIT


@pytest.fixture
def mock_openai_client():
    with patch("app.llm.openai_provider.OpenAI") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        yield mock_client


def test_prompt_builder():
    builder = PromptBuilder()
    analysis = {
        "symbol": "AAPL",
        "entry_price": 150.0,
        "indicators": {"rsi_14": 45.0, "sma_20": 148.0, "atr_14": 2.5},
        "risk": {"stop_loss": 145.0, "take_profit": 160.0, "rr_ratio": 4.0},
        "liquidity": {"is_liquid": True, "spread_pct": 0.001},
        "sizing": {"qty": 3.0},
    }
    
    prompt = builder.build_entry_prompt(analysis)
    
    # Check if compact JSON (no spaces)
    assert " " not in prompt
    data = json.loads(prompt)
    assert data["sym"] == "AAPL"
    assert data["ind"]["rsi"] == 45.0
    assert data["risk"]["buy"]["tp"] == 160.0
    assert data["risk"]["sell"] is None
    assert data["calc"]["qty_max"] == 1.3333
    assert data["liq"] is True
    assert data["spr"] == 0.001
    assert data["short_allowed"] is False


def test_prompt_builder_includes_short_risk_when_shorting_enabled():
    builder = PromptBuilder()
    analysis = {
        "symbol": "AAPL",
        "entry_price": 150.0,
        "risk": {
            "buy": {"stop_loss": 145.0, "take_profit": 160.0, "rr_ratio": 2.0},
            "sell": {"stop_loss": 155.0, "take_profit": 140.0, "rr_ratio": 2.0},
        },
        "liquidity": {"is_liquid": True, "spread_pct": 0.001},
    }

    with patch("app.llm.prompt_builder.ALLOW_SHORT_SELLING", True):
        data = json.loads(builder.build_entry_prompt(analysis))

    assert data["short_allowed"] is True
    assert data["risk"]["buy"]["sl"] == 145.0
    assert data["risk"]["sell"]["tp"] == 140.0


def test_exit_prompt_includes_pnl_risk_context():
    builder = PromptBuilder()
    prompt = builder.build_exit_prompt(
        "AAPL",
        {
            "qty": 10,
            "side": "long",
            "avg_entry_price": 100.0,
            "unrealized_pl": 90.0,
            "unrealized_plpc": 0.09,
            "target_price": 110.0,
            "stop_loss_price": 95.0,
        },
        {"latest_price": 109.0},
        {
            "risk_state": "PROFIT_GIVEBACK",
            "exit_pressure": "high",
            "pnl": 90.0,
            "pnl_pct": 0.09,
            "r_mult": 1.5,
            "giveback_ratio": 0.55,
            "trail_breached": True,
            "protect_profit": True,
        },
    )

    data = json.loads(prompt)
    assert data["sym"] == "AAPL"
    assert data["pos"]["target"] == 110.0
    assert data["pos"]["stop"] == 95.0
    assert data["pos"]["target_hit"] is False
    assert data["pos"]["stop_hit"] is False
    assert data["pnl_risk"]["state"] == "PROFIT_GIVEBACK"
    assert data["pnl_risk"]["pressure"] == "high"
    assert data["pnl_risk"]["giveback_ratio"] == 0.55


def test_exit_prompt_marks_target_and_stop_hits_by_position_side():
    builder = PromptBuilder()

    long_target = json.loads(builder.build_exit_prompt(
        "AAPL",
        {"qty": 10, "side": "long", "target_price": 110.0, "stop_loss_price": 95.0},
        {"latest_price": 111.0},
    ))
    short_stop = json.loads(builder.build_exit_prompt(
        "AAPL",
        {"qty": 10, "side": "short", "target_price": 90.0, "stop_loss_price": 105.0},
        {"latest_price": 106.0},
    ))

    assert long_target["pos"]["target_hit"] is True
    assert long_target["pos"]["stop_hit"] is False
    assert short_stop["pos"]["target_hit"] is False
    assert short_stop["pos"]["stop_hit"] is True


def test_openai_provider_success(mock_openai_client):
    provider = OpenAIProvider(api_key="fake-key")
    
    # Mock response
    mock_completion = MagicMock()
    mock_completion.choices[0].message.content = json.dumps({
        "sym": "AAPL",
        "action": "BUY",
        "conf": 0.85,
        "qty": 10,
        "target": 160.0,
        "stop": 145.0,
        "reason_code": "trend_aligned"
    })
    mock_openai_client.chat.completions.create.return_value = mock_completion
    
    signal = provider.ask("prompt", "system", EntrySignal)
    
    assert isinstance(signal, EntrySignal)
    assert signal.action == "BUY"
    assert signal.conf == 0.85
    mock_openai_client.chat.completions.create.assert_called_once()
    assert mock_openai_client.chat.completions.create.call_args.kwargs["max_tokens"] == MAX_OUTPUT_TOKENS_ENTRY


def test_openai_provider_empty_entry_object_falls_back_to_skip(mock_openai_client):
    provider = OpenAIProvider(api_key="fake-key")

    mock_completion = MagicMock()
    mock_completion.choices[0].message.content = "{}"
    mock_openai_client.chat.completions.create.return_value = mock_completion

    signal = provider.ask(json.dumps({"sym": "AVAX/USD"}), "system", EntrySignal)

    assert isinstance(signal, EntrySignal)
    assert signal.sym == "AVAX/USD"
    assert signal.action == "SKIP"
    assert signal.conf == 0.0
    assert signal.qty == 0
    assert signal.reason_code == "LLM_INVALID_RESPONSE_SKIP"
    mock_openai_client.chat.completions.create.assert_called_once()


def test_openai_provider_empty_exit_object_falls_back_to_complete(mock_openai_client):
    provider = OpenAIProvider(api_key="fake-key")

    mock_completion = MagicMock()
    mock_completion.choices[0].message.content = "{}"
    mock_openai_client.chat.completions.create.return_value = mock_completion

    signal = provider.ask(json.dumps({"sym": "AAPL"}), "system", ExitSignal)

    assert isinstance(signal, ExitSignal)
    assert signal.sym == "AAPL"
    assert signal.action == "COMPLETE"
    assert signal.conf == 0.0
    assert signal.reason_code == "LLM_INVALID_RESPONSE_COMPLETE"
    assert mock_openai_client.chat.completions.create.call_args.kwargs["max_tokens"] == MAX_OUTPUT_TOKENS_EXIT


def test_ask_llm_wrapper(mock_openai_client):
    provider = OpenAIProvider(api_key="fake-key")
    ask_llm = AskLLM(provider)
    
    # Mock response
    mock_completion = MagicMock()
    mock_completion.choices[0].message.content = json.dumps({
        "sym": "AAPL",
        "action": "SKIP",
        "conf": 0.2,
        "qty": 0,
        "reason_code": "low_confidence"
    })
    mock_openai_client.chat.completions.create.return_value = mock_completion
    
    signal = ask_llm.get_decision("prompt", "system", EntrySignal)
    assert signal.action == "SKIP"


def test_lfm_provider_uses_configured_output_budgets():
    provider = LFMProvider.__new__(LFMProvider)

    assert provider._max_new_tokens(EntrySignal) == MAX_OUTPUT_TOKENS_ENTRY
    assert provider._max_new_tokens(ExitSignal) == MAX_OUTPUT_TOKENS_EXIT
