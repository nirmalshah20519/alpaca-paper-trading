"""Central execution router with idempotent paper-order submission."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.broker.trading_adapter import AlpacaTradingAdapter
from app.core.events import EventDispatcher, InternalEvent, InternalEventType
from app.core.idempotency import generate_order_idempotency_key
from app.core.logging import get_logger
from app.core.trading import ExecutionResult, TradeApprovalDecision, TradeProposal
from app.execution.order_factory import OrderFactory
from app.state.repository import OrderRepository, TradeIntentRepository


class ExecutionRouter:
    """Submit approved proposals without bypassing state and idempotency."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        trading_adapter: AlpacaTradingAdapter,
        dispatcher: EventDispatcher,
        order_factory: OrderFactory | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._trading_adapter = trading_adapter
        self._dispatcher = dispatcher
        self._order_factory = order_factory or OrderFactory()
        self._logger = get_logger(__name__)

    async def submit_approved_proposal(
        self,
        proposal: TradeProposal,
        approval: TradeApprovalDecision,
    ) -> ExecutionResult:
        """Persist, reserve, build, and submit a protected paper order."""
        async with self._session_factory() as session:
            async with session.begin():
                trade_intent_repo = TradeIntentRepository(session)
                order_repo = OrderRepository(session)

                trade_intent = await trade_intent_repo.create_trade_intent(
                    intent_key=proposal.proposal_id,
                    strategy_id=proposal.strategy_id,
                    strategy_version=proposal.strategy_version,
                    symbol=proposal.symbol,
                    side=proposal.side,
                    thesis=proposal.thesis,
                    confidence=proposal.confidence,
                    requested_qty=approval.approved_qty,
                    metadata={
                        "invalidations": proposal.invalidations,
                        "min_hold_minutes": proposal.min_hold_minutes,
                        "generated_at": proposal.generated_at.isoformat(),
                    },
                )
                idempotency_key = generate_order_idempotency_key(trade_intent.intent_key)
                await trade_intent_repo.reserve_order_submission(
                    trade_intent.intent_key,
                    idempotency_key,
                )
                built = self._order_factory.build(
                    proposal,
                    approval,
                    client_order_id=idempotency_key[:48],
                )
                existing_order = await order_repo.get_by_client_order_id(built.client_order_id)
                if existing_order is not None:
                    return ExecutionResult(
                        submitted=False,
                        proposal_id=proposal.proposal_id,
                        trade_intent_id=trade_intent.intent_key,
                        client_order_id=existing_order.client_order_id,
                        broker_order_id=existing_order.broker_order_id,
                        message="duplicate_submission_deduplicated",
                    )

            try:
                submitted = await self._trading_adapter.submit_order(built.order_request)
            except Exception as exc:
                await self._dispatcher.dispatch(
                    InternalEvent(
                        event_type=InternalEventType.ALERT,
                        occurred_at=datetime.now(UTC),
                        payload={
                            "type": "order_failure",
                            "proposal_id": proposal.proposal_id,
                            "error": str(exc),
                        },
                    )
                )
                raise

            async with session.begin():
                order = await order_repo.upsert_from_snapshot(
                    submitted,
                    trade_intent=trade_intent,
                )
                order.strategy_id = proposal.strategy_id
                order.sector = proposal.sector
                order.raw_payload = {
                    **order.raw_payload,
                    "proposal_id": proposal.proposal_id,
                    "invalidations": proposal.invalidations,
                    "min_hold_minutes": proposal.min_hold_minutes,
                }
                self._logger.info(
                    "paper_order_submitted",
                    proposal_id=proposal.proposal_id,
                    client_order_id=order.client_order_id,
                    broker_order_id=order.broker_order_id,
                )
                return ExecutionResult(
                    submitted=True,
                    proposal_id=proposal.proposal_id,
                    trade_intent_id=trade_intent.intent_key,
                    client_order_id=order.client_order_id,
                    broker_order_id=order.broker_order_id,
                    message="paper_order_submitted",
                )

    async def cancel_order(self, broker_order_id: str) -> None:
        """Cancel an open broker order."""
        await self._trading_adapter.cancel_order(broker_order_id)
