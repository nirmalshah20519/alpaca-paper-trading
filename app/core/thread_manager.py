"""
app/core/thread_manager.py

ThreadManager — manages the lifecycle of all service loops.

Phase 3:
  - Accepts a ServiceContainer.
  - Injects specific services into each loop during initialization.
  - Manages thread startup and graceful shutdown.
"""

from __future__ import annotations

import threading
import time
from typing import List

from app.core.state import AppState
from app.datasource.service_container import ServiceContainer
from app.loops.asset_refresh_loop import AssetRefreshLoop
from app.loops.entry_opportunity_loop import EntryOpportunityLoop
from app.loops.open_order_monitor_loop import OpenOrderMonitorLoop
from app.loops.reconciliation_loop import ReconciliationLoop
from app.loops.heartbeat_loop import HeartbeatLoop
from app.loops.base_loop import BaseLoop
from app.utils.logger import logger


class ThreadManager:
    """
    Orchestrates the start and stop of all background loops.
    """

    def __init__(self, app_state: AppState, services: ServiceContainer) -> None:
        self.app_state = app_state
        self.services = services
        
        # Initialize loops with injected services
        self._all_loops: List[BaseLoop] = [
            AssetRefreshLoop(
                app_state=app_state, 
                asset_selector=services.asset_selector
            ),
            EntryOpportunityLoop(
                app_state=app_state,
                market_data_service=services.market_data_service,
                account_service=services.account_service,
                calculator=services.calculator,
                llm=services.llm,
                prompt_builder=services.prompt_builder,
                validator=services.validator,
                executor=services.executor
            ),
            OpenOrderMonitorLoop(
                app_state=app_state,
                account_service=services.account_service,
                market_data_service=services.market_data_service,
                calculator=services.calculator,
                llm=services.llm,
                prompt_builder=services.prompt_builder,
                executor=services.executor
            ),
            ReconciliationLoop(
                app_state=app_state,
                account_service=services.account_service,
                storage_manager=services.storage_manager
            ),
            HeartbeatLoop(
                app_state=app_state
            ),
        ]
        self._threads: List[threading.Thread] = []

    def start_all(self) -> None:
        """Launch all loops in background threads."""
        logger.info("ThreadManager: starting {} loops...", len(self._all_loops))
        
        for loop in self._all_loops:
            t = threading.Thread(target=loop.start, name=loop.name, daemon=True)
            t.start()
            self._threads.append(t)
            
        # Give them a moment to start and log initial status
        time.sleep(0.5)
        self._log_status()

    def stop_all(self) -> None:
        """
        Signal all loops to stop and wait for threads to join.
        Called on SIGINT / shutdown.
        """
        logger.info("ThreadManager: stopping all loops...")
        
        # 1. Signal shutdown (AppState event)
        self.app_state.shutdown_event.set()
        
        # 2. Individual stop signals (just in case)
        for loop in self._all_loops:
            loop.stop()
            
        # 3. Wait for threads to terminate
        for t in self._threads:
            logger.debug("Waiting for thread {}...", t.name)
            t.join(timeout=5.0)
            if t.is_alive():
                logger.warning("Thread {} failed to join within timeout.", t.name)
        
        logger.info("ThreadManager: all loops stopped.")

    def _log_status(self) -> None:
        """Log which loops are alive."""
        for loop in self._all_loops:
            status = "running" if loop.is_running() else "DEAD"
            logger.info("  Loop {} -> {}", loop.name, status)
