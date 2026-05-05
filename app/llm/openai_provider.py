"""
app/llm/openai_provider.py

OpenAIProvider — implements BaseLLMProvider using the OpenAI SDK.

Design rules:
  - Uses response_format="json_object" to ensure structured output.
  - Implements exponential backoff via tenacity.
  - Enforces token budgets and max context lengths.
"""

from __future__ import annotations

from typing import Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from app.core.models import ExitSignal
from app.llm.ask_llm import BaseLLMProvider
from app.llm.response_safety import parse_llm_response
from app.utils.logger import logger
from config.llm_config import (
    LLM_MODEL,
    MAX_OUTPUT_TOKENS_ENTRY,
    MAX_OUTPUT_TOKENS_EXIT,
    TEMPERATURE,
)

T = TypeVar("T", bound=BaseModel)


class OpenAIProvider(BaseLLMProvider):
    """
    OpenAI-backed LLM provider.
    """

    def __init__(self, api_key: str) -> None:
        self.client = OpenAI(api_key=api_key)

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def ask(
        self, 
        prompt: str, 
        system_message: str, 
        response_model: Type[T]
    ) -> T:
        """
        Calls OpenAI ChatCompletion with JSON response format.
        """
        try:
            logger.debug("Sending prompt to OpenAI model={}...", LLM_MODEL)
            
            # Append JSON instruction to system message to be safe with json_object mode
            full_system_message = (
                f"{system_message}\n\nYou MUST return a valid JSON object matching "
                f" the following schema: {response_model.model_json_schema()}"
            )

            response = self.client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": full_system_message},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=(
                    MAX_OUTPUT_TOKENS_EXIT
                    if response_model is ExitSignal
                    else MAX_OUTPUT_TOKENS_ENTRY
                ),
                temperature=TEMPERATURE,
            )

            raw_content = response.choices[0].message.content
            return parse_llm_response(raw_content, response_model, prompt, "OpenAI")

        except Exception as exc:
            logger.error("OpenAI request failed: {}", exc)
            raise
