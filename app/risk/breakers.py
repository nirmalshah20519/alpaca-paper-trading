"""Persistent kill-switch and circuit breaker management."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.trading import BreakerStateView
from app.state.repository import AccountRepository, RiskControlRepository

MANUAL_KILL_SWITCH = "manual_kill_switch"
DAILY_LOSS_BREAKER = "daily_loss_breaker"


class BreakerManager:
    """Manage persistent breakers that override all approval paths."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def ensure_defaults(self, session: AsyncSession) -> list[BreakerStateView]:
        """Ensure required control states exist."""
        repository = RiskControlRepository(session)
        states = [
            await repository.get_or_create(MANUAL_KILL_SWITCH),
            await repository.get_or_create(DAILY_LOSS_BREAKER),
        ]
        return [self._to_view(state) for state in states]

    async def set_kill_switch(
        self,
        session: AsyncSession,
        *,
        is_active: bool,
        reason: str | None = None,
    ) -> BreakerStateView:
        """Persist manual kill-switch state."""
        repository = RiskControlRepository(session)
        state = await repository.set_state(
            MANUAL_KILL_SWITCH,
            is_active=is_active,
            reason=reason,
        )
        return self._to_view(state)

    async def evaluate_daily_loss_breaker(self, session: AsyncSession) -> BreakerStateView:
        """Refresh the daily loss breaker from current account equity."""
        account_repo = AccountRepository(session)
        control_repo = RiskControlRepository(session)
        account = await account_repo.get_latest()
        state = await control_repo.get_or_create(DAILY_LOSS_BREAKER)
        if account is None:
            return self._to_view(state)

        today = date.today().isoformat()
        metadata = dict(state.metadata_json)
        baseline = metadata.get("baseline_equity")
        if metadata.get("date") != today or baseline is None:
            metadata = {"date": today, "baseline_equity": str(account.equity)}
            state = await control_repo.set_state(
                DAILY_LOSS_BREAKER,
                is_active=False,
                reason=None,
                metadata=metadata,
            )
            return self._to_view(state)

        baseline_equity = Decimal(str(baseline))
        threshold = baseline_equity * (
            Decimal("1") - Decimal(str(self._settings.risk_daily_loss_breaker_pct))
        )
        if account.equity <= threshold:
            metadata["triggered_at"] = datetime.now(UTC).isoformat()
            state = await control_repo.set_state(
                DAILY_LOSS_BREAKER,
                is_active=True,
                reason="daily_loss_breaker_triggered",
                metadata=metadata,
            )
        else:
            state = await control_repo.set_state(
                DAILY_LOSS_BREAKER,
                is_active=False,
                reason=None,
                metadata=metadata,
            )
        return self._to_view(state)

    async def list_states(self, session: AsyncSession) -> list[BreakerStateView]:
        """Return current breaker and kill-switch state."""
        repository = RiskControlRepository(session)
        states = await repository.list_states()
        return [self._to_view(state) for state in states]

    @staticmethod
    def _to_view(state: object) -> BreakerStateView:
        """Convert persistence state to API view."""
        return BreakerStateView(
            control_key=state.control_key,
            is_active=state.is_active,
            reason=state.reason,
            metadata=state.metadata_json,
        )
