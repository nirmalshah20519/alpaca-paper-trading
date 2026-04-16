"""HTTP routes for the control plane."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.trading import (
    BreakerStateView,
    MetricsView,
    OrchestrationCycleResult,
    RiskSummaryView,
    TradeApprovalDecision,
    TradeProposal,
)

router = APIRouter()


class KillSwitchUpdateRequest(BaseModel):
    """Payload for toggling the manual kill switch."""

    is_active: bool
    reason: str | None = None


class RunCycleRequest(BaseModel):
    """Payload for a one-shot orchestration cycle."""

    dry_run: bool = True


@router.get("/internal/broker/account", tags=["internal"])
async def broker_account(request: Request) -> dict[str, object]:
    """Return the current paper account snapshot and connectivity status."""
    trading_adapter = request.app.state.trading_adapter
    if trading_adapter is None:
        raise HTTPException(
            status_code=503,
            detail="Broker adapter is unavailable. Configure Alpaca paper credentials first.",
        )
    snapshot = await trading_adapter.get_account_snapshot()
    return {
        "trading_mode": request.app.state.settings.trading_mode,
        "account_id": snapshot.account_id,
        "status": snapshot.status,
        "currency": snapshot.currency,
        "buying_power": str(snapshot.buying_power),
        "equity": str(snapshot.equity),
    }


@router.get("/health", tags=["system"])
async def health(request: Request) -> dict[str, object]:
    """Return a lightweight health report for app dependencies."""
    services = await request.app.state.health_service.check()
    status = "ok" if all(item["ok"] for item in services.values()) else "degraded"
    return {"status": status, "services": services}


@router.get("/internal/risk/summary", tags=["internal"])
async def risk_summary(request: Request) -> RiskSummaryView:
    """Return the current risk and exposure summary."""
    return await request.app.state.proposal_evaluation_service.get_risk_summary()


@router.get("/internal/risk/breakers", tags=["internal"])
async def breaker_status(request: Request) -> list[BreakerStateView]:
    """Return breaker and kill-switch status."""
    return await request.app.state.proposal_evaluation_service.list_breakers()


@router.get("/internal/risk/kill-switch", tags=["internal"])
async def kill_switch_status(request: Request) -> BreakerStateView:
    """Return the current manual kill-switch state."""
    breakers = await request.app.state.proposal_evaluation_service.list_breakers()
    for breaker in breakers:
        if breaker.control_key == "manual_kill_switch":
            return breaker
    return BreakerStateView(control_key="manual_kill_switch", is_active=False, metadata={})


@router.post("/internal/risk/kill-switch", tags=["internal"])
async def set_kill_switch(
    payload: KillSwitchUpdateRequest,
    request: Request,
) -> BreakerStateView:
    """Toggle the persistent manual kill switch."""
    return await request.app.state.proposal_evaluation_service.set_kill_switch(
        is_active=payload.is_active,
        reason=payload.reason,
    )


@router.post("/internal/proposals/evaluate", tags=["internal"])
async def evaluate_proposal(
    proposal: TradeProposal,
    request: Request,
) -> TradeApprovalDecision:
    """Dry-run a proposal through allocation and risk validation."""
    return await request.app.state.proposal_evaluation_service.evaluate_proposal(proposal)


@router.post("/internal/orchestration/run", tags=["internal"])
async def run_cycle(
    payload: RunCycleRequest,
    request: Request,
) -> OrchestrationCycleResult:
    """Run one simple orchestration cycle."""
    if request.app.state.orchestration_service is None:
        raise HTTPException(status_code=503, detail="Orchestration service is unavailable.")
    try:
        return await request.app.state.orchestration_service.run_cycle(dry_run=payload.dry_run)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/internal/metrics", tags=["internal"])
async def metrics(request: Request) -> MetricsView:
    """Return lightweight runtime metrics."""
    return request.app.state.metrics_service.snapshot()


@router.get("/internal/reporting/daily", tags=["internal"])
async def daily_report(request: Request) -> dict[str, object]:
    """Return the current daily summary."""
    return await request.app.state.reporting_service.generate_daily_summary()
