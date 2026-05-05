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
from app.utils.safe_number import safe_float
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
            order_symbols = []
            
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
                if order.get("symbol"):
                    order_symbols.append(str(order["symbol"]))
            
            self.app_state.set_open_orders(order_ids, order_symbols)
            
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
        qty = abs(safe_float(position.get("qty"), 0.0) or 0.0)
        
        try:
            # 1. Fetch current market data for exit
            if not self._market_data: return
            market_data = self._market_data.fetch_required_exit_data(symbol)
            position_context = self._position_with_local_trade_context(symbol, position)
            pnl_risk = {}
            if self._calculator:
                pnl_risk = self._calculator.run_exit_pnl_analysis(position_context, market_data)

            hard_exit_reason = self._hard_exit_reason(position_context, market_data)
            if hard_exit_reason:
                logger.info("[OpenOrderMonitorLoop] Hard EXIT for {} | reason={}", symbol, hard_exit_reason)
                signal = ExitSignal(sym=symbol, action="COMPLETE", conf=1.0, reason_code=hard_exit_reason)
                self._execute_exit(symbol, qty, position_context, signal)
                return
            
            # 2. Ask LLM for exit decision
            if not self._llm or not self._prompt_builder: return
            prompt = self._prompt_builder.build_exit_prompt(
                symbol,
                position_context,
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
                self._execute_exit(symbol, qty, position_context, signal)
            else:
                logger.debug("[OpenOrderMonitorLoop] HOLDING {} | reason={}", symbol, signal.reason_code)

        except Exception as exc:  # noqa: BLE001
            logger.error("[OpenOrderMonitorLoop] Failed to process position {}: {}", symbol, exc)

    def _exit_side(self, position: dict) -> str:
        side = str(position.get("side") or "").lower()
        qty = safe_float(position.get("qty"), 0.0) or 0.0
        return "BUY" if "short" in side or qty < 0 else "SELL"

    def _execute_exit(self, symbol: str, qty: float, position: dict, signal: ExitSignal) -> None:
        if not self._executor:
            return

        self._executor.execute_exit(
            symbol,
            qty,
            side=self._exit_side(position),
            reason_code=signal.reason_code,
        )

        if getattr(self._executor, "storage", None):
            self._executor.storage.record_signal(
                timestamp=str(utc_now()),
                flow="EXIT",
                symbol=symbol,
                signal=signal,
                validation=None,  # Exit signals don't have a validator in this version.
            )

    def _position_with_local_trade_context(self, symbol: str, position: dict) -> dict:
        context = dict(position)
        row = self._local_open_order_for_symbol(symbol)
        if not row:
            return context

        if not context.get("target_price"):
            context["target_price"] = row.get("target_price")
        if not context.get("stop_loss_price"):
            context["stop_loss_price"] = row.get("stop_loss_price")
        if not context.get("entry_side"):
            context["entry_side"] = row.get("entry_side")
        if not context.get("side"):
            context["side"] = self._position_side_from_entry(row.get("entry_side"))
        return context

    def _local_open_order_for_symbol(self, symbol: str) -> dict | None:
        storage = getattr(self._executor, "storage", None)
        if not storage:
            return None

        try:
            if hasattr(storage, "get_open_order_for_symbol"):
                row = storage.get_open_order_for_symbol(symbol)
                if isinstance(row, dict):
                    return row

            if hasattr(storage, "get_open_orders"):
                wanted = self._canonical_symbol(symbol)
                for row in storage.get_open_orders():
                    if isinstance(row, dict) and self._canonical_symbol(row.get("symbol")) == wanted:
                        return row
        except Exception as exc:  # noqa: BLE001
            logger.warning("[OpenOrderMonitorLoop] Could not load local context for {}: {}", symbol, exc)
        return None

    def _hard_exit_reason(self, position: dict, market_data: dict) -> str | None:
        current = safe_float(market_data.get("latest_price") or position.get("current_price"))
        if current is None:
            return None

        stop = safe_float(position.get("stop_loss_price") or position.get("stop"))
        target = safe_float(position.get("target_price") or position.get("target"))
        is_short = self._exit_side(position) == "BUY"

        if stop is not None:
            stop_hit = current >= stop if is_short else current <= stop
            if stop_hit:
                return "STOP_REACHED"

        if target is not None:
            target_hit = current <= target if is_short else current >= target
            if target_hit:
                return "TARGET_REACHED"

        return None

    def _position_side_from_entry(self, entry_side: object) -> str:
        return "short" if str(entry_side or "").upper() == "SELL" else "long"

    def _canonical_symbol(self, symbol: object) -> str:
        return str(symbol or "").upper().replace("/", "").replace("-", "")
