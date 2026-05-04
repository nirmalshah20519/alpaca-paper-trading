"""
app/loops/open_order_monitor_loop.py

OpenOrderMonitorLoop — monitors open orders and manages position exits.

Phase 7/8 Update:
  - Fetches open orders to update AppState.
  - Fetches open positions and runs exit logic via LLM.
"""

from __future__ import annotations

from typing import Optional

from app.core.state import AppState
from app.core.models import ExitSignal
from app.datasource.account_service import BaseAccountService
from app.datasource.market_data_service import BaseMarketDataService
from app.calculator.calculator_engine import CalculatorEngine
from app.llm.ask_llm import AskLLM
from app.llm.prompt_builder import PromptBuilder
from app.executor.trade_executor import TradeExecutor
from app.loops.base_loop import BaseLoop
from app.utils.logger import logger
from app.utils.time_utils import utc_now
from config.settings import MONITOR_INTERVAL_SECONDS
from config.prompts import EXIT_SYSTEM_PROMPT


class OpenOrderMonitorLoop(BaseLoop):
    """
    Monitors open orders and manages exits for existing positions.
    """

    def __init__(
        self,
        app_state: AppState,
        account_service: Optional[BaseAccountService] = None,
        market_data_service: Optional[BaseMarketDataService] = None,
        calculator: Optional[CalculatorEngine] = None,
        llm: Optional[AskLLM] = None,
        prompt_builder: Optional[PromptBuilder] = None,
        executor: Optional[TradeExecutor] = None,
    ) -> None:
        super().__init__(
            name="OpenOrderMonitorLoop",
            interval_seconds=MONITOR_INTERVAL_SECONDS,
            app_state=app_state,
        )
        self._account_service = account_service
        self._market_data = market_data_service
        self._calculator = calculator
        self._llm = llm
        self._prompt_builder = prompt_builder
        self._executor = executor

    def run_once(self) -> None:
        if not self._account_service:
            return

        try:
            # 1. Update Open Orders in AppState & Reap Stale Orders
            open_orders = self._account_service.get_open_orders()
            order_ids = []
            
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)
            stale_threshold = timedelta(minutes=5)

            for order in open_orders:
                order_id = order["id"]
                status = order["status"]
                
                # Check for stale orders (submitted but not filled for 5+ mins)
                if status in ["new", "accepted", "submitted", "partially_filled"]:
                    sub_at_str = order.get("submitted_at")
                    if sub_at_str:
                        # Parse '2026-05-03 09:34:09.840540+00:00'
                        try:
                            # Alpaca timestamps can be tricky, simple ISO parse
                            from dateutil import parser
                            sub_at = parser.parse(sub_at_str)
                            if (now - sub_at) > stale_threshold:
                                logger.warning("[OpenOrderMonitorLoop] Order {} is STALE ({}). Cancelling...", order_id, sub_at_str)
                                if self._executor:
                                    self._executor.submitter.cancel_order(order_id)
                                continue # Don't add to active order_ids
                        except Exception as e:
                            logger.error("Failed to parse order timestamp {}: {}", sub_at_str, e)

                order_ids.append(order_id)
            
            self.app_state.set_open_orders(order_ids)
            
            if order_ids:
                logger.info("[OpenOrderMonitorLoop] {} open orders active.", len(order_ids))

            # 2. Manage Position Exits
            positions = self._account_service.get_positions()
            if positions:
                logger.info("[OpenOrderMonitorLoop] Monitoring {} open positions...", len(positions))
                for pos in positions:
                    if self.app_state.shutdown_event.is_set():
                        break
                    self._process_position(pos)

        except Exception as exc:  # noqa: BLE001
            logger.error("[OpenOrderMonitorLoop] Cycle failed: {}", exc)

    def _process_position(self, position: dict) -> None:
        """Evaluate a single position for exit."""
        symbol = position["symbol"]
        qty = position["qty"]
        
        try:
            # 1. Fetch current market data for exit
            if not self._market_data: return
            market_data = self._market_data.fetch_required_exit_data(symbol)
            pnl_risk = {}
            if self._calculator:
                pnl_risk = self._calculator.run_exit_pnl_analysis(position, market_data)
            
            # 2. Ask LLM for exit decision
            if not self._llm or not self._prompt_builder: return
            prompt = self._prompt_builder.build_exit_prompt(
                symbol,
                position,
                market_data,
                pnl_risk,
            )
            
            signal: ExitSignal = self._llm.get_decision(
                prompt=prompt,
                system_message=EXIT_SYSTEM_PROMPT,
                response_model=ExitSignal
            )
            
            # 3. Execute Exit if needed
            if signal.action == "COMPLETE":
                logger.info("[OpenOrderMonitorLoop] EXIT signal for {} | reason={}", symbol, signal.reason_code)
                if self._executor:
                    self._executor.execute_exit(symbol, qty)
                    
                    # Log signal
                    if self._executor.storage:
                        self._executor.storage.record_signal(
                            timestamp=str(utc_now()),
                            flow="EXIT",
                            symbol=symbol,
                            signal=signal,
                            validation=None # Exit signals don't have a validator in this version
                        )
            else:
                logger.debug("[OpenOrderMonitorLoop] HOLDING {} | reason={}", symbol, signal.reason_code)

        except Exception as exc:  # noqa: BLE001
            logger.error("[OpenOrderMonitorLoop] Failed to process position {}: {}", symbol, exc)
