"""
app/loops/asset_refresh_loop.py

AssetRefreshLoop — refreshes the active trading symbol list every hour.

Phase 3:
  - If an AssetSelector is injected, use it to score and return top-N symbols.
  - Falls back to Phase 2 behaviour (static default universe) when no selector
    is provided (so Phase 2 tests continue to pass).
"""

from __future__ import annotations

from typing import Optional

from app.core.state import AppState
from app.datasource.asset_selector import BaseAssetSelector
from app.loops.base_loop import BaseLoop
from app.utils.logger import logger
from config.settings import DEFAULT_STOCK_UNIVERSE, ASSET_REFRESH_INTERVAL_SECONDS, MAX_ACTIVE_SYMBOLS


class AssetRefreshLoop(BaseLoop):
    """
    Periodically updates AppState.active_assets.

    Parameters
    ----------
    app_state : AppState
    asset_selector : BaseAssetSelector | None
        If provided, use it for live Alpaca scoring (Phase 3+).
        If None, fall back to the static default universe (Phase 2 stub).

    Interval : 1 hour (config/settings.py).
    """

    def __init__(
        self,
        app_state: AppState,
        asset_selector: Optional[BaseAssetSelector] = None,
    ) -> None:
        super().__init__(
            name="AssetRefreshLoop",
            interval_seconds=ASSET_REFRESH_INTERVAL_SECONDS,
            app_state=app_state,
        )
        self._selector = asset_selector

    def run_once(self) -> None:
        logger.info("[AssetRefreshLoop] asset_refresh_started")

        if self._selector is not None:
            # Phase 3+: live Alpaca scoring
            new_assets = self._selector.get_top_n_assets(MAX_ACTIVE_SYMBOLS)
        else:
            # Phase 2 stub: static default universe
            new_assets = list(DEFAULT_STOCK_UNIVERSE[:MAX_ACTIVE_SYMBOLS])

        if not new_assets:
            logger.warning(
                "[AssetRefreshLoop] Asset list came back empty. Keeping previous list."
            )
            return

        self.app_state.set_active_assets(new_assets)
        logger.info(
            "[AssetRefreshLoop] asset_refresh_completed — {} symbols loaded. selector={}",
            len(new_assets),
            type(self._selector).__name__ if self._selector else "stub",
        )
