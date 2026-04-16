"""Lightweight portfolio concentration helpers."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.trading import TradeProposal
from app.state.models import Position


@dataclass(slots=True)
class BucketConcentrationResult:
    """Result of checking lightweight concentration buckets."""

    allowed: bool
    reasons: list[str]


class CorrelationEngine:
    """Use simple symbol/sector/strategy buckets instead of statistical correlation."""

    def check_buckets(
        self,
        proposal: TradeProposal,
        active_positions: list[Position],
        *,
        sector_bucket_limit: int,
    ) -> BucketConcentrationResult:
        """Reject concentrated sector buckets while keeping logic simple."""
        reasons: list[str] = []
        sector_positions = [
            position
            for position in active_positions
            if proposal.sector is not None and position.sector == proposal.sector
        ]
        if proposal.sector is not None and len(sector_positions) >= sector_bucket_limit:
            reasons.append(f"sector_bucket_limit_exceeded:{proposal.sector}")
        return BucketConcentrationResult(allowed=not reasons, reasons=reasons)
