"""
app/datasource/service_container.py

ServiceContainer — groups all initialized datasource services into one object.

Phase 7 Update:
  - Added Calculator, LLM, Validator, and Executor services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.datasource.market_data_service import BaseMarketDataService
from app.datasource.account_service import BaseAccountService
from app.datasource.asset_selector import BaseAssetSelector
from app.storage.storage_manager import StorageManager
from app.calculator.calculator_engine import CalculatorEngine
from app.llm.ask_llm import AskLLM
from app.llm.prompt_builder import PromptBuilder
from app.validator.signal_validator import SignalValidator
from app.executor.trade_executor import TradeExecutor


@dataclass
class ServiceContainer:
    """
    Holds references to all major service objects.
    """

    asset_selector: Optional[BaseAssetSelector] = field(default=None)
    market_data_service: Optional[BaseMarketDataService] = field(default=None)
    account_service: Optional[BaseAccountService] = field(default=None)
    storage_manager: Optional[StorageManager] = field(default=None)
    
    # Phase 4-7
    calculator: Optional[CalculatorEngine] = field(default=None)
    llm: Optional[AskLLM] = field(default=None)
    prompt_builder: Optional[PromptBuilder] = field(default=None)
    validator: Optional[SignalValidator] = field(default=None)
    executor: Optional[TradeExecutor] = field(default=None)

    def __repr__(self) -> str:
        parts = []
        if self.asset_selector: parts.append("selector")
        if self.market_data_service: parts.append("market_data")
        if self.account_service: parts.append("account")
        if self.storage_manager: parts.append("storage")
        if self.calculator: parts.append("calculator")
        if self.llm: parts.append("llm")
        if self.validator: parts.append("validator")
        if self.executor: parts.append("executor")
        return f"ServiceContainer({', '.join(parts)})"
