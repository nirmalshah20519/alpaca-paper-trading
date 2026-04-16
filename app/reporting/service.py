"""Minimal reporting, alerting, and metrics services."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.events import InternalEvent, InternalEventType
from app.core.logging import get_logger
from app.core.trading import MetricsView
from app.state.models import Fill, Order, Position


class MetricsService:
    """Simple in-memory metrics counter."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()

    def increment(self, key: str, amount: int = 1) -> None:
        self._counts[key] += amount

    def set_open_positions(self, count: int) -> None:
        self._counts["open_positions"] = count

    def snapshot(self) -> MetricsView:
        return MetricsView(
            proposals_generated=self._counts["proposals_generated"],
            approvals=self._counts["approvals"],
            rejections=self._counts["rejections"],
            orders_placed=self._counts["orders_placed"],
            open_positions=self._counts["open_positions"],
        )


class AlertService:
    """Placeholder alerting that logs alert-worthy internal events."""

    def __init__(self) -> None:
        self._logger = get_logger(__name__)

    async def handle_event(self, event: InternalEvent) -> None:
        """Log alert-worthy internal events."""
        if event.event_type not in {
            InternalEventType.ALERT,
            InternalEventType.RECONCILIATION_MISMATCH,
        }:
            return
        self._logger.warning(
            "alert_event",
            event_type=event.event_type.value,
            occurred_at=event.occurred_at.isoformat(),
            **event.payload,
        )


class ReportingService:
    """Generate simple JSON-friendly daily summaries."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._logger = get_logger(__name__)

    async def generate_daily_summary(self) -> dict[str, object]:
        """Compute a simple end-of-day operational summary."""
        start_of_day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        async with self._session_factory() as session:
            fills = list(
                (
                    await session.execute(select(Fill).where(Fill.filled_at >= start_of_day))
                ).scalars()
            )
            orders = list(
                (
                    await session.execute(select(Order).where(Order.created_at >= start_of_day))
                ).scalars()
            )
            closed_positions = list(
                (
                    await session.execute(
                        select(Position).where(
                            Position.closed_at.is_not(None),
                            Position.closed_at >= start_of_day,
                        )
                    )
                ).scalars()
            )

        trade_count = len({fill.order_id for fill in fills})
        pnl_values = [
            Decimal(
                str(position.raw_payload.get("realized_pl", position.unrealized_pl or Decimal("0")))
            )
            for position in closed_positions
        ]
        wins = sum(1 for value in pnl_values if value > 0)
        losses = sum(1 for value in pnl_values if value < 0)
        summary = {
            "generated_at": datetime.now(UTC).isoformat(),
            "trade_count": trade_count,
            "orders_created": len(orders),
            "pnl": str(sum(pnl_values, Decimal("0"))),
            "wins": wins,
            "losses": losses,
        }
        self._logger.info("daily_summary", **summary)
        return summary
