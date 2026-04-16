"""Service entrypoints for Phase 3 portfolio allocation and risk approval."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.events import EventDispatcher, InternalEvent, InternalEventType
from app.core.trading import (
    BreakerStateView,
    RiskSummaryView,
    StrategyPortfolioContext,
    StrategyPositionView,
    TradeApprovalDecision,
    TradeProposal,
)
from app.portfolio.engine import PortfolioEngine, PortfolioSnapshot
from app.risk.breakers import MANUAL_KILL_SWITCH, BreakerManager
from app.risk.engine import RiskEngine
from app.state.models import Fill, Position
from app.state.repository import AccountRepository, PositionRepository


class ProposalEvaluationService:
    """Evaluate proposals against current state without placing orders."""

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        dispatcher: EventDispatcher | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._dispatcher = dispatcher
        self._portfolio_engine = PortfolioEngine(settings)
        self._risk_engine = RiskEngine(settings)
        self._breaker_manager = BreakerManager(settings)

    async def evaluate_proposal(self, proposal: TradeProposal) -> TradeApprovalDecision:
        """Run `proposal -> portfolio allocation -> risk validation`."""
        async with self._session_factory() as session:
            snapshot, active_positions, recent_closed_positions, breakers = (
                await self._build_context(session)
            )
            allocation = self._portfolio_engine.allocate(proposal, snapshot, active_positions)
            return self._risk_engine.evaluate(
                proposal=proposal,
                snapshot=snapshot,
                breaker_states=breakers,
                active_positions=active_positions,
                recent_closed_positions=recent_closed_positions,
                approved_qty=allocation.approved_qty,
                applied_caps=allocation.applied_caps,
                allocation_reasons=allocation.reasons,
            )

    async def get_risk_summary(self) -> RiskSummaryView:
        """Return current portfolio/risk summary."""
        async with self._session_factory() as session:
            snapshot, _, _, breakers = await self._build_context(session)
            return RiskSummaryView(
                as_of=snapshot.as_of,
                equity=snapshot.equity,
                buying_power=snapshot.buying_power,
                gross_exposure=snapshot.gross_exposure,
                net_exposure=snapshot.net_exposure,
                open_positions=snapshot.open_positions,
                daily_turnover=snapshot.daily_turnover,
                kill_switch_active=any(
                    state.control_key == MANUAL_KILL_SWITCH and state.is_active
                    for state in breakers
                ),
                breakers=breakers,
            )

    async def get_strategy_portfolio_context(self) -> StrategyPortfolioContext:
        """Return strategy-safe portfolio context for candidate generation."""
        async with self._session_factory() as session:
            snapshot, active_positions, _, _ = await self._build_context(session)
            return StrategyPortfolioContext(
                equity=snapshot.equity,
                buying_power=snapshot.buying_power,
                gross_exposure=snapshot.gross_exposure,
                net_exposure=snapshot.net_exposure,
                open_positions=[
                    StrategyPositionView(
                        symbol=position.symbol,
                        side=position.side,
                        qty=position.qty,
                        avg_entry_price=position.avg_entry_price,
                        strategy_id=position.strategy_id,
                        sector=position.sector,
                        opened_at=position.opened_at,
                        metadata=position.raw_payload,
                    )
                    for position in active_positions
                ],
            )

    async def list_breakers(self) -> list[BreakerStateView]:
        """Return persistent breaker and kill-switch state."""
        async with self._session_factory() as session:
            return await self._refresh_breakers(session)

    async def set_kill_switch(
        self,
        *,
        is_active: bool,
        reason: str | None = None,
    ) -> BreakerStateView:
        """Persist manual kill switch state."""
        async with self._session_factory() as session:
            async with session.begin():
                return await self._breaker_manager.set_kill_switch(
                    session,
                    is_active=is_active,
                    reason=reason,
                )

    async def _build_context(
        self,
        session: AsyncSession,
    ) -> tuple[PortfolioSnapshot, list[Position], list[Position], list[BreakerStateView]]:
        """Load the current state needed by portfolio and risk evaluation."""
        account_repo = AccountRepository(session)
        position_repo = PositionRepository(session)
        account = await account_repo.get_latest()
        active_positions = await position_repo.list_active_positions()
        recent_closed_positions = await position_repo.list_recent_closed_positions(limit=50)
        daily_turnover = await self._calculate_daily_turnover(session)
        breakers = await self._refresh_breakers(session)

        equity = account.equity if account is not None else Decimal("0")
        buying_power = account.buying_power if account is not None else Decimal("0")

        gross_exposure = sum(
            abs(position.market_value or (position.avg_entry_price or Decimal("0")) * position.qty)
            for position in active_positions
        )
        net_exposure = sum(
            (
                position.market_value
                or (position.avg_entry_price or Decimal("0")) * position.qty
            )
            if position.side.value == "buy"
            else -(
                position.market_value
                or (position.avg_entry_price or Decimal("0")) * position.qty
            )
            for position in active_positions
        )
        symbol_exposure: dict[str, Decimal] = {}
        strategy_exposure: dict[str, Decimal] = {}
        sector_exposure: dict[str, Decimal] = {}
        for position in active_positions:
            notional = abs(
                position.market_value
                or (position.avg_entry_price or Decimal("0")) * position.qty
            )
            symbol_exposure[position.symbol] = (
                symbol_exposure.get(position.symbol, Decimal("0")) + notional
            )
            strategy_key = position.strategy_id or "unknown"
            strategy_exposure[strategy_key] = (
                strategy_exposure.get(strategy_key, Decimal("0")) + notional
            )
            if position.sector is not None:
                sector_exposure[position.sector] = (
                    sector_exposure.get(position.sector, Decimal("0")) + notional
                )

        snapshot = PortfolioSnapshot(
            as_of=datetime.now(UTC),
            equity=equity,
            buying_power=buying_power,
            gross_exposure=gross_exposure,
            net_exposure=net_exposure,
            daily_turnover=daily_turnover,
            open_positions=len(active_positions),
            symbol_exposure=symbol_exposure,
            strategy_exposure=strategy_exposure,
            sector_exposure=sector_exposure,
        )
        return snapshot, active_positions, recent_closed_positions, breakers

    async def _refresh_breakers(self, session: AsyncSession) -> list[BreakerStateView]:
        """Ensure breaker state exists and refresh the daily breaker."""
        async with session.begin_nested():
            await self._breaker_manager.ensure_defaults(session)
            await self._breaker_manager.evaluate_daily_loss_breaker(session)
        states = await self._breaker_manager.list_states(session)
        if self._dispatcher is not None:
            for state in states:
                if state.is_active:
                    await self._dispatcher.dispatch(
                        InternalEvent(
                            event_type=InternalEventType.ALERT,
                            occurred_at=datetime.now(UTC),
                            payload={
                                "type": "breaker_active",
                                "control_key": state.control_key,
                                "reason": state.reason,
                            },
                        )
                    )
        return states

    async def _calculate_daily_turnover(self, session: AsyncSession) -> Decimal:
        """Compute same-day filled turnover from persisted fills."""
        start_of_day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        result = await session.execute(select(Fill).where(Fill.filled_at >= start_of_day))
        fills = list(result.scalars().all())
        return sum(fill.qty * fill.price for fill in fills)
