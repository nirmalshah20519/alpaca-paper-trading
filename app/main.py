"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.routes import router as api_router
from app.broker.alpaca_client import AlpacaClientFactory
from app.broker.market_data_adapter import AlpacaMarketDataAdapter
from app.broker.stream_adapter import AlpacaStreamAdapter
from app.broker.trading_adapter import AlpacaTradingAdapter
from app.core.config import Settings, get_settings
from app.core.database import build_engine, build_session_factory, create_schema, ping_database
from app.core.events import EventDispatcher, InternalEvent, InternalEventType
from app.core.logging import configure_logging, get_logger
from app.core.redis import build_redis_client, ping_redis
from app.execution.engine import ExecutionEngine
from app.execution.router import ExecutionRouter
from app.market_data.service import MarketDataService
from app.orchestration.service import OrchestrationService
from app.reporting.service import AlertService, MetricsService, ReportingService
from app.risk.service import ProposalEvaluationService
from app.state.service import StateService
from app.strategies.mean_reversion import MeanReversionStrategy
from app.strategies.registry import StrategyRegistry
from app.strategies.trend_following import TrendFollowingStrategy
from app.workers.scheduler import SchedulerService
from app.workers.stream_worker import StreamWorker


class HealthService:
    """Aggregate dependency health checks."""

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        redis_client: Redis,
        broker_enabled: bool,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._redis_client = redis_client
        self._broker_enabled = broker_enabled

    async def check(self) -> dict[str, dict[str, bool]]:
        """Return a simple dependency health map."""
        database_ok = await ping_database(self._session_factory)
        redis_ok = await ping_redis(self._redis_client)
        return {
            "api": {"ok": True, "paper_only": self._settings.trading_mode == "paper"},
            "database": {"ok": database_ok},
            "redis": {"ok": redis_ok},
            "broker": {"ok": self._broker_enabled, "configured": self._broker_enabled},
        }


async def validate_broker_startup(
    settings: Settings,
    trading_adapter: AlpacaTradingAdapter,
    state_service: StateService,
) -> None:
    """Run safe startup validation for paper credentials and account connectivity."""
    settings.validate_trading_safety()
    if not settings.enable_startup_broker_validation:
        return

    await state_service.sync_account(await trading_adapter.get_account_snapshot())
    await state_service.sync_orders(await trading_adapter.list_order_snapshots(status="open"))
    await state_service.sync_positions(await trading_adapter.get_position_snapshots())


async def log_internal_event(event: InternalEvent) -> None:
    """Default internal event sink."""
    logger = get_logger("app.internal_events")
    warning_events = {
        InternalEventType.ALERT,
        InternalEventType.RECONCILIATION_MISMATCH,
    }
    log_method = logger.warning if event.event_type in warning_events else logger.info
    log_method(
        "internal_event",
        event_type=event.event_type.value,
        occurred_at=event.occurred_at.isoformat(),
        **event.payload,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared resources, schema, logging, and startup checks."""
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger(__name__)

    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    redis_client = build_redis_client(settings.redis_url)
    await create_schema(engine)
    dispatcher = EventDispatcher()
    state_service = StateService(session_factory, dispatcher)
    proposal_evaluation_service = ProposalEvaluationService(settings, session_factory, dispatcher)
    metrics_service = MetricsService()
    alert_service = AlertService()
    reporting_service = ReportingService(session_factory)
    for event_type in InternalEventType:
        dispatcher.subscribe(event_type, log_internal_event)
    dispatcher.subscribe(InternalEventType.ALERT, alert_service.handle_event)
    dispatcher.subscribe(InternalEventType.RECONCILIATION_MISMATCH, alert_service.handle_event)

    clients = None
    trading_adapter = None
    market_data_adapter = None
    stream_adapter = None
    stream_worker = None
    market_data_service = None
    execution_router = None
    execution_engine = None
    strategy_registry = StrategyRegistry()
    strategy_registry.register(TrendFollowingStrategy())
    strategy_registry.register(MeanReversionStrategy())
    orchestration_service = None

    if settings.alpaca_api_key and settings.alpaca_api_secret:
        clients = AlpacaClientFactory(settings).create()
        trading_adapter = AlpacaTradingAdapter(clients)
        market_data_adapter = AlpacaMarketDataAdapter(clients)
        market_data_service = MarketDataService(market_data_adapter)
        stream_adapter = AlpacaStreamAdapter(clients)
        stream_adapter.subscribe_trade_updates(state_service.apply_trade_update)
        stream_worker = StreamWorker(stream_adapter)
        execution_router = ExecutionRouter(
            session_factory,
            trading_adapter,
            dispatcher,
        )
        execution_engine = ExecutionEngine(
            settings,
            session_factory,
            execution_router,
            dispatcher,
        )
        await validate_broker_startup(settings, trading_adapter, state_service)
        logger.info("alpaca_startup_validation_complete", masked_key=settings.masked_alpaca_key)
    elif settings.enable_startup_broker_validation:
        settings.validate_trading_safety()

    scheduler = SchedulerService(settings, trading_adapter, state_service)
    scheduler.start()
    if stream_worker is not None and settings.enable_stream_worker:
        await stream_worker.start()
    if market_data_service is not None:
        orchestration_service = OrchestrationService(
            settings,
            market_data_service,
            strategy_registry,
            proposal_evaluation_service,
            execution_engine,
            metrics_service,
        )

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.redis = redis_client
    app.state.health_service = HealthService(
        settings,
        session_factory,
        redis_client,
        broker_enabled=trading_adapter is not None,
    )
    app.state.scheduler = scheduler
    app.state.dispatcher = dispatcher
    app.state.state_service = state_service
    app.state.proposal_evaluation_service = proposal_evaluation_service
    app.state.reporting_service = reporting_service
    app.state.metrics_service = metrics_service
    app.state.alpaca_clients = clients
    app.state.trading_adapter = trading_adapter
    app.state.market_data_adapter = market_data_adapter
    app.state.market_data_service = market_data_service
    app.state.stream_adapter = stream_adapter
    app.state.stream_worker = stream_worker
    app.state.execution_router = execution_router
    app.state.execution_engine = execution_engine
    app.state.strategy_registry = strategy_registry
    app.state.orchestration_service = orchestration_service

    try:
        yield
    finally:
        if stream_worker is not None:
            await stream_worker.stop()
        scheduler.shutdown()
        await redis_client.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    """Application factory."""
    app = FastAPI(title="Alpaca Paper Agent", lifespan=lifespan)
    app.include_router(api_router)
    return app


app = create_app()
