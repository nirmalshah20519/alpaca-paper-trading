"""APScheduler bootstrap for periodic MVP background tasks."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.broker.trading_adapter import AlpacaTradingAdapter
from app.core.config import Settings
from app.state.service import StateService
from app.workers.reconcile_worker import ReconcileWorker


class SchedulerService:
    """Manage scheduled jobs for the control plane."""

    def __init__(
        self,
        settings: Settings,
        trading_adapter: AlpacaTradingAdapter | None,
        state_service: StateService | None,
    ) -> None:
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._settings = settings
        self._reconcile_worker = (
            ReconcileWorker(trading_adapter, state_service)
            if trading_adapter is not None and state_service is not None
            else None
        )

    def start(self) -> None:
        """Start the scheduler and register MVP jobs."""
        if self._reconcile_worker is not None:
            self._scheduler.add_job(
                self._reconcile_worker.run_once,
                trigger="interval",
                seconds=self._settings.reconcile_interval_seconds,
                id="reconcile-worker",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
        self._scheduler.start()

    def shutdown(self) -> None:
        """Stop the scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
