"""
app/loops/entry_opportunity_loop.py

EntryOpportunityLoop — scans active assets for entry signals and executes trades.

Phase 7 Update:
  - Full pipeline: MarketData -> Calculator -> LLM -> Validator -> Executor.
"""

from __future__ import annotations

from typing import Optional

from app.core.state import AppState
from app.core.models import EntrySignal
from app.datasource.market_data_service import BaseMarketDataService
from app.datasource.account_service import BaseAccountService
from app.calculator.calculator_engine import CalculatorEngine
from app.llm.ask_llm import AskLLM
from app.llm.prompt_builder import PromptBuilder
from app.validator.signal_validator import SignalValidator
from app.executor.trade_executor import TradeExecutor
from app.loops.base_loop import BaseLoop
from app.utils.logger import logger
from app.utils.time_utils import utc_now
from config.settings import (
    ENTRY_INTERVAL_SECONDS, 
    MAX_DOLLAR_PER_TRADE, 
    STOCK_CLOSE_BUFFER_MINUTES
)
from config.prompts import ENTRY_SYSTEM_PROMPT


class EntryOpportunityLoop(BaseLoop):
    """
    Periodically scans active symbols for entry signals.
    """

    def __init__(
        self,
        app_state: AppState,
        market_data_service: Optional[BaseMarketDataService] = None,
        account_service: Optional[BaseAccountService] = None,
        calculator: Optional[CalculatorEngine] = None,
        llm: Optional[AskLLM] = None,
        prompt_builder: Optional[PromptBuilder] = None,
        validator: Optional[SignalValidator] = None,
        executor: Optional[TradeExecutor] = None,
    ) -> None:
        super().__init__(
            name="EntryOpportunityLoop",
            interval_seconds=ENTRY_INTERVAL_SECONDS,
            app_state=app_state,
        )
        self._market_data = market_data_service
        self._account_service = account_service
        self._calculator = calculator
        self._llm = llm
        self._prompt_builder = prompt_builder
        self._validator = validator
        self._executor = executor

    def run_once(self) -> None:
        if self.app_state.is_paused():
            logger.info("[EntryOpportunityLoop] Entries are paused.")
            return

        symbols = self.app_state.get_active_assets()
        if not symbols:
            logger.debug("[EntryOpportunityLoop] No active assets.")
            return

        logger.info("[EntryOpportunityLoop] entry_cycle_started | symbols={}", len(symbols))

        # Fetch account snapshot once per cycle
        account_snapshot = {}
        if self._account_service:
            account_snapshot = self._account_service.get_account_snapshot()

        for symbol in symbols:
            if self.app_state.shutdown_event.is_set():
                break
            self._process_symbol(symbol, account_snapshot)

        logger.info("[EntryOpportunityLoop] entry_cycle_completed.")

    def _process_symbol(self, symbol: str, account_snapshot: dict) -> None:
        """The full entry pipeline."""
        try:
            # 1. Fetch Market Data
            if not self._market_data: return
            market_data = self._market_data.fetch_required_entry_data(symbol)
            if not market_data.get("latest_price") or market_data.get("bars") is None or market_data["bars"].empty:
                return

            # 2. Run Calculations (Phase 4)
            if not self._calculator: return
            analysis = self._calculator.run_entry_analysis(market_data, account_snapshot)
            if not analysis: return

            # Check for Analysis Throttling (Cost Efficiency)
            latest_price = market_data.get("latest_price", 0)
            if not self.app_state.should_analyze(symbol, latest_price):
                logger.debug("[EntryOpportunityLoop] Skipping {} (Price/Time threshold not met).", symbol)
                return

            # Check Market Close Buffer for Stocks
            if "/" not in symbol: # Stock
                if self._account_service and self._account_service.is_market_closing_soon(STOCK_CLOSE_BUFFER_MINUTES):
                    logger.warning("[EntryOpportunityLoop] Skipping Stock {} (Market Close Buffer).", symbol)
                    return

            # 3. LLM Decision (Phase 5)
            if not self._llm or not self._prompt_builder: return
            prompt = self._prompt_builder.build_entry_prompt(analysis)
            signal: EntrySignal = self._llm.get_decision(
                prompt=prompt,
                system_message=ENTRY_SYSTEM_PROMPT,
                response_model=EntrySignal
            )

            # Mark as analyzed with price to throttle future calls
            self.app_state.mark_analyzed(symbol, latest_price)

            if signal.action == "SKIP":
                # Log skip
                if self._executor and self._executor.storage:
                    self._executor.storage.record_signal(str(utc_now()), "ENTRY", symbol, signal, None)
                return

            # 4. Risk Management: Capital Sizing (Support Fractional)
            # Use entry_price from analysis or latest_price from market_data
            calc_price = analysis.get("entry_price") or market_data.get("latest_price", 0)
            
            if calc_price > 0:
                # For Crypto, we use 4 decimal places. For Stocks, Alpaca usually wants integers (or limited fractions).
                is_crypto = "/" in symbol
                raw_qty = MAX_DOLLAR_PER_TRADE / calc_price
                
                if is_crypto:
                    calculated_qty = round(raw_qty, 4)
                else:
                    calculated_qty = int(raw_qty) # Stocks default to whole shares for safety
                
                if calculated_qty <= 0:
                    logger.warning("[EntryOpportunityLoop] Calculated qty for {} is 0 (Price={}). Skipping.", symbol, calc_price)
                    return
                
                if abs(signal.qty - calculated_qty) > 0.00001:
                    logger.info("[EntryOpportunityLoop] Overriding LLM qty ({}) with Risk-Managed qty ({}) for {}.", signal.qty, calculated_qty, symbol)
                    signal.qty = calculated_qty

            # 5. Validation (Phase 6)
            if not self._validator: return
            validation = self._validator.validate_entry(signal)
            
            # Log signal decision to CSV
            if self._executor and self._executor.storage:
                self._executor.storage.record_signal(
                    timestamp=str(utc_now()),
                    flow="ENTRY",
                    symbol=symbol,
                    signal=signal,
                    validation=validation
                )

            # 5. Execution (Phase 7)
            if signal.action != "SKIP" and validation.validated:
                if self._executor:
                    logger.info("[EntryOpportunityLoop] EXECUTING trade for {}...", symbol)
                    self._executor.execute_entry(signal)
                else:
                    logger.warning("[EntryOpportunityLoop] No executor. Trade skipped.")

        except Exception as exc:  # noqa: BLE001
            logger.error("[EntryOpportunityLoop] Failed to process {}: {}", symbol, exc)
