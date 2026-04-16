"""Simple strategy-to-approval-to-execution orchestration loop."""

from __future__ import annotations

from app.core.config import Settings
from app.core.trading import MetricsView, OrchestrationCycleResult
from app.execution.engine import ExecutionEngine
from app.market_data.service import MarketDataService
from app.reporting.service import MetricsService
from app.risk.service import ProposalEvaluationService
from app.strategies.registry import CandidateRanker, StrategyRegistry


class OrchestrationService:
    """Run one deterministic paper-trading cycle."""

    def __init__(
        self,
        settings: Settings,
        market_data_service: MarketDataService,
        strategy_registry: StrategyRegistry,
        proposal_service: ProposalEvaluationService,
        execution_engine: ExecutionEngine | None,
        metrics_service: MetricsService,
    ) -> None:
        self._settings = settings
        self._market_data_service = market_data_service
        self._strategy_registry = strategy_registry
        self._proposal_service = proposal_service
        self._execution_engine = execution_engine
        self._metrics_service = metrics_service
        self._ranker = CandidateRanker()

    async def run_cycle(self, *, dry_run: bool = True) -> OrchestrationCycleResult:
        """Run one orchestration cycle from market data to optional execution."""
        if not dry_run and not self._settings.enable_paper_execution:
            raise ValueError(
                "Paper execution is disabled. "
                "Set ENABLE_PAPER_EXECUTION=true to submit paper orders."
            )
        market_ctx = await self._market_data_service.build_market_context(
            self._settings.watchlist,
            limit=50,
        )
        portfolio_ctx = await self._proposal_service.get_strategy_portfolio_context()
        proposals = await self._strategy_registry.generate_candidates(market_ctx, portfolio_ctx)
        ranked = self._ranker.rank(
            proposals,
            market_ctx,
            limit=self._settings.strategy_max_proposals_per_cycle,
        )

        approvals = []
        executions = []
        self._metrics_service.increment("proposals_generated", len(proposals))
        for ranked_proposal in ranked:
            decision = await self._proposal_service.evaluate_proposal(ranked_proposal.proposal)
            approvals.append(decision)
            if decision.approved:
                self._metrics_service.increment("approvals", 1)
                if not dry_run and self._execution_engine is not None:
                    execution = await self._execution_engine.execute(
                        ranked_proposal.proposal,
                        decision,
                    )
                    executions.append(execution)
                    if execution.submitted:
                        self._metrics_service.increment("orders_placed", 1)
            else:
                self._metrics_service.increment("rejections", 1)

        risk_summary = await self._proposal_service.get_risk_summary()
        self._metrics_service.set_open_positions(risk_summary.open_positions)

        return OrchestrationCycleResult(
            proposals_generated=len(proposals),
            proposals_ranked=len(ranked),
            approvals=approvals,
            executions=executions,
        )

    def get_metrics(self) -> MetricsView:
        """Return current in-memory metrics."""
        return self._metrics_service.snapshot()
