"""
app/llm/ask_llm.py

AskLLM — abstract interface for LLM providers.

Design rules:
  - Single method: ask(prompt, system_message).
  - Returns a Pydantic model (EntrySignal or ExitSignal).
  - Isolates provider-specific logic (OpenAI, Anthropic, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class BaseLLMProvider(ABC):
    """
    Abstract interface for LLM providers.
    """

    @abstractmethod
    def ask(
        self, 
        prompt: str, 
        system_message: str, 
        response_model: Type[T]
    ) -> T:
        """
        Send a prompt to the LLM and return a structured response.
        """


class AskLLM:
    """
    High-level wrapper that uses a BaseLLMProvider.
    """

    def __init__(self, provider: BaseLLMProvider) -> None:
        self.provider = provider

    def get_decision(
        self, 
        prompt: str, 
        system_message: str, 
        response_model: Type[T]
    ) -> T:
        """
        Get a structured decision from the LLM.
        """
        return self.provider.ask(prompt, system_message, response_model)
