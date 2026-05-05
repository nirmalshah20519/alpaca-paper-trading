"""
Safety helpers for turning LLM text into typed signal models.

Invalid LLM output should never crash a trading loop. If the model cannot
satisfy the entry schema, the safe action is SKIP; for exit, it is COMPLETE.
"""

from __future__ import annotations

import json
from typing import Type, TypeVar, cast

from pydantic import BaseModel, ValidationError

from app.core.models import EntrySignal, ExitSignal
from app.utils.logger import logger

T = TypeVar("T", bound=BaseModel)

ENTRY_INVALID_RESPONSE_REASON = "LLM_INVALID_RESPONSE_SKIP"
EXIT_INVALID_RESPONSE_REASON = "LLM_INVALID_RESPONSE_COMPLETE"


def parse_llm_response(
    raw_content: str | None,
    response_model: Type[T],
    prompt: str,
    provider_name: str,
) -> T:
    """
    Parse JSON content and validate it as the requested Pydantic model.

    For EntrySignal, malformed/empty/schema-invalid model output becomes a
    conservative SKIP signal. For ExitSignal, the conservative action is
    COMPLETE because capital is already exposed.
    """
    if not raw_content:
        fallback = _safe_fallback(response_model, prompt, provider_name, "empty response", "")
        if fallback is not None:
            return fallback
        raise ValueError(f"{provider_name} returned an empty response.")

    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        fallback = _safe_fallback(response_model, prompt, provider_name, str(exc), raw_content)
        if fallback is not None:
            return fallback
        raise

    try:
        return response_model.model_validate(data)
    except ValidationError as exc:
        fallback = _safe_fallback(response_model, prompt, provider_name, str(exc), raw_content)
        if fallback is not None:
            return fallback
        raise


def _safe_fallback(
    response_model: Type[T],
    prompt: str,
    provider_name: str,
    error: str,
    raw_content: str,
) -> T | None:
    if response_model is EntrySignal:
        return _entry_fallback(prompt, provider_name, error, raw_content)
    if response_model is ExitSignal:
        return _exit_fallback(prompt, provider_name, error, raw_content)
    return None


def _entry_fallback(prompt: str, provider_name: str, error: str, raw_content: str) -> T:
    symbol = _symbol_from_prompt(prompt)
    logger.warning(
        "{} returned an invalid EntrySignal; using SKIP fallback | sym={} | error={} | raw={}",
        provider_name,
        symbol,
        error,
        _excerpt(raw_content),
    )
    return cast(
        T,
        EntrySignal(
            sym=symbol,
            action="SKIP",
            conf=0.0,
            qty=0,
            target=None,
            stop=None,
            reason_code=ENTRY_INVALID_RESPONSE_REASON,
        ),
    )


def _exit_fallback(prompt: str, provider_name: str, error: str, raw_content: str) -> T:
    symbol = _symbol_from_prompt(prompt)
    logger.warning(
        "{} returned an invalid ExitSignal; using COMPLETE fallback | sym={} | error={} | raw={}",
        provider_name,
        symbol,
        error,
        _excerpt(raw_content),
    )
    return cast(
        T,
        ExitSignal(
            sym=symbol,
            action="COMPLETE",
            conf=0.0,
            reason_code=EXIT_INVALID_RESPONSE_REASON,
        ),
    )


def _symbol_from_prompt(prompt: str) -> str:
    try:
        data = json.loads(prompt)
    except json.JSONDecodeError:
        return "UNKNOWN"

    symbol = data.get("sym") or data.get("symbol")
    if isinstance(symbol, str) and symbol:
        return symbol
    return "UNKNOWN"


def _excerpt(text: str, limit: int = 500) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."
