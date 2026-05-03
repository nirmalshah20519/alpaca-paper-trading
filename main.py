"""
main.py

Application entry point for the Alpaca Trading Service.

Phases 1-3 Summary:
  - Phase 1: Config loading, Environment validation, CSV storage initialization.
  - Phase 2: Thread-safe runtime framework (RLock state, background loops).
  - Phase 3: Alpaca Datasource integration (Gateway, MarketData, Account, Selector).
"""

from __future__ import annotations

import signal
import sys
import time

from app.core.config import AppConfig
from app.core.state import AppState
from app.core.thread_manager import ThreadManager
from app.storage.storage_manager import StorageManager
from app.utils.logger import logger, setup_logger

# Phase 3 Imports
from app.datasource.alpaca_gateway import AlpacaGateway
from app.datasource.market_data_service import AlpacaMarketDataService
from app.datasource.account_service import AlpacaAccountService
from app.datasource.asset_selector import AlpacaAssetSelector
from app.datasource.service_container import ServiceContainer
from app.calculator.calculator_engine import CalculatorEngine
from app.llm.openai_provider import OpenAIProvider
from app.llm.ask_llm import AskLLM
from app.llm.prompt_builder import PromptBuilder
from app.validator.signal_validator import SignalValidator


def main() -> None:
    """Main execution flow."""
    
    # 1. Setup logging
    setup_logger()
    logger.info("=" * 60)
    logger.info("Trading Signal Service — starting up")
    logger.info("=" * 60)

    try:
        # 2. Load and validate environment configuration
        config = AppConfig.load()
        logger.info("Config loaded: {}", config)
        logger.info("Trading mode : {}", config.trading_mode)

        if config.trading_mode == "REAL":
            logger.warning("!!! REAL TRADING MODE DETECTED !!!")
            logger.warning("This system will place REAL ORDERS with REAL MONEY.")
            # Safety double check: we still require user to have confirmed real mode elsewhere if needed
        else:
            logger.info("PAPER mode — no real orders will be placed.")

        # 3. Initialise Thread-safe state
        app_state = AppState()
        logger.info("AppState initialised.")

        # 4. Initialise CSV storage (Phase 1)
        storage_manager = StorageManager()
        storage_manager.init_all()
        logger.info("CSV storage ready.")

        # 5. Initialise Datasource Services (Phase 3)
        gateway = AlpacaGateway(
            api_key=config.alpaca_api_key,
            api_secret=config.alpaca_api_secret,
            trading_mode=config.trading_mode,
        )
        
        # 6. Initialize logic services (Phases 4-7)
        calculator = CalculatorEngine()
        llm_provider = OpenAIProvider(api_key=config.openai_api_key)
        llm = AskLLM(llm_provider)
        prompt_builder = PromptBuilder()
        validator = SignalValidator(app_state)
        
        from app.executor.alpaca_order_submitter import AlpacaOrderSubmitter
        from app.executor.trade_executor import TradeExecutor
        executor = TradeExecutor(
            submitter=AlpacaOrderSubmitter(gateway.trading_client),
            storage=storage_manager
        )

        services = ServiceContainer(
            asset_selector=AlpacaAssetSelector(gateway),
            market_data_service=AlpacaMarketDataService(gateway),
            account_service=AlpacaAccountService(gateway),
            storage_manager=storage_manager,
            calculator=calculator,
            llm=llm,
            prompt_builder=prompt_builder,
            validator=validator,
            executor=executor
        )
        logger.info("Datasource and Logic services initialised.")

        # 7. Initialise Thread Manager with injected services
        thread_manager = ThreadManager(app_state, services)

        # 8. Start Dashboard Server (Background Thread)
        from app.dashboard.server import run_server
        run_server(storage_manager, app_state, port=8000)

        # 9. Setup signal handling for graceful shutdown
        def handle_exit(signum, frame):
            logger.info("Shutdown signal received ({}).", signum)
            thread_manager.stop_all()
            sys.exit(0)

        signal.signal(signal.SIGINT, handle_exit)
        signal.signal(signal.SIGTERM, handle_exit)

        # 8. Start background loops
        thread_manager.start_all()
        logger.info("Service is running. Press Ctrl+C to stop.")

        # 9. Main thread wait loop
        while not app_state.shutdown_event.is_set():
            time.sleep(1.0)

    except Exception as exc:
        logger.exception("FATAL: Service failed during startup or runtime.")
        sys.exit(1)


if __name__ == "__main__":
    main()
