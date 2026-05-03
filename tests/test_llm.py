"""
tests/test_llm.py

Tests for Phase 5: LLM integration and prompt building.
"""

import pytest
import json
from unittest.mock import MagicMock, patch

from app.llm.ask_llm import AskLLM
from app.llm.openai_provider import OpenAIProvider
from app.llm.prompt_builder import PromptBuilder
from app.core.models import EntrySignal


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
        "risk": {"stop_loss": 145.0, "take_profit": 160.0, "rr_ratio": 4.0}
    }
    
    prompt = builder.build_entry_prompt(analysis)
    
    # Check if compact JSON (no spaces)
    assert " " not in prompt
    data = json.loads(prompt)
    assert data["sym"] == "AAPL"
    assert data["ind"]["rsi"] == 45.0


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
