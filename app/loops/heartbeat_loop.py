"""
app/loops/heartbeat_loop.py

HeartbeatLoop — logs a health summary every minute so that silence
in the logs is never ambiguous (the service is running, just quiet).
"""

from __future__ import annotations

from app.core.state import AppState
from app.loops.base_loop import BaseLoop
from app.utils.logger import logger
from app.utils.time_utils import utc_now
from config.settings import HEARTBEAT_INTERVAL_SECONDS


class HeartbeatLoop(BaseLoop):
    """
    Emits a health log line every minute.

    Interval : 1 minute.
    """

    def __init__(self, app_state: AppState) -> None:
        super().__init__(
            name="HeartbeatLoop",
            interval_seconds=HEARTBEAT_INTERVAL_SECONDS,
            app_state=app_state,
        )

    def run_once(self) -> None:
        n_assets = len(self.app_state.get_active_assets_copy())
        paused = self.app_state.is_paused()

        logger.info(
            "[HeartbeatLoop] [ALIVE] service_alive | time={} | active_assets={} | "
            "entries_paused={} | last_refresh={}",
            utc_now(),
            n_assets,
            paused,
            self.app_state.last_asset_refresh_utc or "never",
        )
