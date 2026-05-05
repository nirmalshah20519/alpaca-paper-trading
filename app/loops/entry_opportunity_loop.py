"""
app/loops/entry_opportunity_loop.py

EntryOpportunityLoop — scans active assets for entry signals and executes trades.

Phase 7 Update:
  - Full pipeline: MarketData -> Calculator -> LLM -> Validator -> Executor.
"""

from __future__ import annotations

from math import floor
from typing import Optional

from app.core.state import AppState
from app.core.models import EntrySignal, ValidationResult
from app.datasource.market_data_service import BaseMarketDataService
from app.datasource.account_service import BaseAccountService
from app.calculator.calculator_engine import CalculatorEngine
from app.llm.ask_llm import AskLLM
from app.llm.prompt_builder import PromptBuilder
from app.validator.signal_validator import SignalValidator
from app.executor.trade_executor import TradeExecutor
from app.loops.base_loop import BaseLoop
from app.utils.logger import logger
from app.utils.safe_number import safe_float
from app.utils.time_utils import utc_now
from app.core.dynamic_risk import dynamic_trade_budget
from config.settings import (
    ENTRY_INTERVAL_SECONDS, 
    MAX_DOLLAR_PER_TRADE, 
    STOCK_CLOSE_BUFFER_MINUTES,
    ALLOW_FRACTIONAL_STOCK_QTY,
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

            liquidity = analysis.get("liquidity") or {}
            if liquidity.get("is_liquid") is False:
                reason = str(liquidity.get("reason") or "Liquidity gate failed")
                if self._is_hard_liquidity_rejection(reason):
                    logger.info(
                        "[EntryOpportunityLoop] Skipping {} before LLM: {}",
                        symbol,
                        reason,
                    )
                    self._record_deterministic_skip(
                        symbol,
                        reason_code="LIQUIDITY_GATE_SKIP",
                        reason=reason,
                    )
                    return
                logger.warning(
                    "[EntryOpportunityLoop] Soft liquidity warning for {}: {}. Proceeding to LLM with caution.",
                    symbol,
                    reason,
                )
                liquidity["is_liquid"] = True
                liquidity["soft_warning"] = reason
                analysis["liquidity"] = liquidity

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
            calc_price = safe_float(analysis.get("entry_price") or market_data.get("latest_price", 0), 0.0)
            
            if calc_price and calc_price > 0:
                calculated_qty = self._calculate_qty_cap(symbol, calc_price, analysis, account_snapshot)
                
                if calculated_qty <= 0:
                    logger.warning("[EntryOpportunityLoop] Calculated qty for {} is 0 (Price={}). Skipping.", symbol, calc_price)
                    return
                
                approved_qty = min(signal.qty, calculated_qty)
                approved_qty = self._format_qty(symbol, approved_qty)
                if approved_qty <= 0:
                    logger.warning("[EntryOpportunityLoop] LLM qty for {} becomes 0 after lot-size/risk cap. Skipping.", symbol)
                    return

                if abs(signal.qty - approved_qty) > 0.00001:
                    logger.info("[EntryOpportunityLoop] Capping LLM qty ({}) to Risk-Managed qty ({}) for {}.", signal.qty, approved_qty, symbol)
                    signal.qty = approved_qty

            # 5. Validation (Phase 6)
            if not self._validator: return
            validation = self._validator.validate_entry(
                signal,
                account_data=account_snapshot,
                expected_symbol=symbol,
                entry_price=calc_price,
            )
            
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
                    result = self._executor.execute_entry(signal)
                    if result.status == "submitted":
                        self.app_state.add_open_order(result.alpaca_order_id, result.symbol)
                else:
                    logger.warning("[EntryOpportunityLoop] No executor. Trade skipped.")

        except Exception as exc:  # noqa: BLE001
            logger.error("[EntryOpportunityLoop] Failed to process {}: {}", symbol, exc)

    def _record_deterministic_skip(self, symbol: str, reason_code: str, reason: str) -> None:
        if not self._executor or not self._executor.storage:
            return
        signal = EntrySignal(
            sym=symbol,
            action="SKIP",
            conf=0.0,
            qty=0.0,
            target=None,
            stop=None,
            reason_code=reason_code,
        )
        self._executor.storage.record_signal(
            timestamp=str(utc_now()),
            flow="ENTRY",
            symbol=symbol,
            signal=signal,
            validation=ValidationResult(validated=False, reason=reason),
        )

    def _calculate_qty_cap(self, symbol: str, price: float, analysis: dict, account_snapshot: dict | None) -> float:
        trade_budget = dynamic_trade_budget(account_snapshot)
        if trade_budget <= 0:
            trade_budget = MAX_DOLLAR_PER_TRADE
        trade_cap = trade_budget / price if price > 0 else 0.0
        sizing = analysis.get("sizing") or {}
        risk_cap = safe_float(sizing.get("qty"))

        cap = trade_cap
        if risk_cap is not None:
            cap = min(trade_cap, max(risk_cap, 0.0))

        return self._format_qty(symbol, cap)

    def _format_qty(self, symbol: str, qty: float) -> float:
        if "/" in symbol:
            return floor(qty * 10_000) / 10_000
        if ALLOW_FRACTIONAL_STOCK_QTY:
            return floor(qty * 10_000) / 10_000
        return float(int(qty))

    def _is_hard_liquidity_rejection(self, reason: str) -> bool:
        text = str(reason).lower()
        if "quote unavailable" in text or "quote_unavailable" in text:
            return True
        if "spread too wide" in text or "spread_too_wide" in text:
            return True
        return False
