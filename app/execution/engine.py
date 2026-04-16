"""Execution engine for approved paper trade proposals."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.events import EventDispatcher, InternalEvent, InternalEventType
from app.core.logging import get_logger
from app.core.trading import ExecutionResult, TradeApprovalDecision, TradeProposal
from app.execution.router import ExecutionRouter
from app.state.repository import OrderRepository


class ExecutionEngine:
    """Submit approved proposals and manage simple stale-order safety."""

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        router: ExecutionRouter,
        dispatcher: EventDispatcher,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._router = router
        self._dispatcher = dispatcher
        self._logger = get_logger(__name__)

    async def execute(
        self,
        proposal: TradeProposal,
        approval: TradeApprovalDecision,
    ) -> ExecutionResult:
        """Submit a single approved proposal if protections are present."""
        if not approval.approved:
            return ExecutionResult(
                submitted=False,
                proposal_id=proposal.proposal_id,
                message="proposal_not_approved",
            )
        if proposal.stop_price <= 0:
            await self._dispatcher.dispatch(
                InternalEvent(
                    event_type=InternalEventType.ALERT,
                    occurred_at=datetime.now(UTC),
                    payload={
                        "type": "order_failure",
                        "proposal_id": proposal.proposal_id,
                        "error": "missing_stop_loss",
                    },
                )
            )
            return ExecutionResult(
                submitted=False,
                proposal_id=proposal.proposal_id,
                message="missing_stop_loss",
            )
        return await self._router.submit_approved_proposal(proposal, approval)

    async def cancel_stale_orders(self) -> list[str]:
        """Cancel still-open orders that have gone stale."""
        cutoff = datetime.now(UTC) - timedelta(minutes=self._settings.execution_stale_order_minutes)
        async with self._session_factory() as session:
            async with session.begin():
                stale_orders = await OrderRepository(session).list_stale_orders(cutoff=cutoff)
            canceled: list[str] = []
            for order in stale_orders:
                if order.broker_order_id is None:
                    continue
                await self._router.cancel_order(order.broker_order_id)
                canceled.append(order.client_order_id)
                self._logger.info("stale_order_canceled", client_order_id=order.client_order_id)
            return canceled
