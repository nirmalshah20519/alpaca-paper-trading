"""Periodic reconciliation worker."""

from __future__ import annotations

from datetime import UTC, datetime

from app.broker.trading_adapter import AlpacaTradingAdapter
from app.core.logging import get_logger
from app.state.service import ReconciliationReport, StateService


class ReconcileWorker:
    """Compare broker truth with local state and heal safe mismatches."""

    def __init__(
        self,
        trading_adapter: AlpacaTradingAdapter,
        state_service: StateService,
    ) -> None:
        self._trading_adapter = trading_adapter
        self._state_service = state_service
        self._logger = get_logger(__name__)

    async def run_once(self) -> ReconciliationReport:
        """Run one reconciliation cycle."""
        self._logger.info("reconcile_worker_tick")
        account = await self._trading_adapter.get_account_snapshot()
        orders = await self._trading_adapter.list_order_snapshots(status="open")
        positions = await self._trading_adapter.get_position_snapshots()
        report = await self._state_service.reconcile(
            remote_account=account,
            remote_orders=orders,
            remote_positions=positions,
            now=datetime.now(UTC),
        )
        self._logger.info(
            "reconcile_worker_complete",
            missing_orders=len(report.missing_orders),
            mismatched_positions=len(report.mismatched_positions),
            stale_orders=len(report.stale_orders),
        )
        return report
