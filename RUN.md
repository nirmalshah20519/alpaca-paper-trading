# Run Guide

## A. Project Overview

This project is a paper-only Alpaca trading system built around a deterministic architecture:

- market data is fetched through a broker-isolated layer
- strategies generate broker-agnostic trade proposals
- proposals pass through portfolio allocation and risk validation
- only approved proposals may reach the execution engine
- execution submits protected paper orders only
- reconciliation and the trade-update stream keep local state aligned with Alpaca

What it currently supports:

- Alpaca paper trading only
- FastAPI control plane
- PostgreSQL state persistence
- Redis connectivity checks and shared runtime wiring
- trade-update stream ingestion
- reconciliation loop
- deterministic strategy proposal generation
- deterministic portfolio + risk approval
- optional paper order submission through an internal orchestration endpoint
- lightweight metrics and daily JSON reporting

What it does not support:

- live trading
- LLM-driven trading
- options or crypto trading
- backtesting
- parameter optimization
- external alert transport
- advanced dashboards

## B. Architecture Summary

Major modules:

- `app/core`: config, logging, events, shared schemas
- `app/broker`: Alpaca paper client wrappers and stream adapter
- `app/market_data`: market context and indicators for strategies
- `app/strategies`: deterministic strategies and proposal ranking
- `app/portfolio`: capital budgeting and lightweight concentration controls
- `app/risk`: risk rules, breakers, kill switch, proposal approval service
- `app/execution`: protected order construction, routing, and paper execution
- `app/state`: database models, repositories, lifecycle transitions
- `app/workers`: reconciliation and scheduler wiring
- `app/reporting`: metrics, alert logging, and daily summary
- `app/orchestration`: one-shot cycle runner

Pipeline:

1. market data is fetched from Alpaca through the broker adapter
2. strategies read only market context and portfolio context
3. strategies emit `TradeProposal`
4. proposals are ranked and capped
5. portfolio allocation adjusts size
6. risk validation approves or rejects
7. approved proposals can be executed as paper orders
8. Alpaca broker responses and trade updates update PostgreSQL state
9. reconciliation keeps local truth aligned with Alpaca

## C. Prerequisites

- Python `3.12+`
- Docker Desktop or Docker Engine with Docker Compose
- an Alpaca paper trading account
- Alpaca paper API key and secret

Required environment variables:

- `TRADING_MODE=paper`
- `DATABASE_URL`
- `REDIS_URL`
- `ALPACA_API_KEY`
- `ALPACA_API_SECRET`
- `ALPACA_API_BASE_URL=https://paper-api.alpaca.markets`

Important execution flag:

- `ENABLE_PAPER_EXECUTION=false` by default

Leave this as `false` until you explicitly want orchestration cycles to submit paper orders.

## D. Setup Steps

1. Clone the project.

```bash
git clone <your-repo-url>
cd alpaca-paper-trading
```

2. Install Python dependencies.

```bash
pip install -r requirements/dev.txt
```

3. Copy `.env.example` to `.env`.

Do not commit `.env`. It should contain your real paper credentials and must stay local.

4. Edit `.env` and fill in at least:

```env
TRADING_MODE=paper
ALPACA_API_KEY=your_paper_key
ALPACA_API_SECRET=your_paper_secret
ALPACA_API_BASE_URL=https://paper-api.alpaca.markets
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/alpaca_paper_agent
REDIS_URL=redis://localhost:6379/0
ENABLE_PAPER_EXECUTION=false
```

If you run the API with `uvicorn` on your host machine, keep `localhost` in `DATABASE_URL` and `REDIS_URL`.
If you run the API as the `app` service in Docker Compose, use `postgres` and `redis` as the hosts instead.

5. Start PostgreSQL and Redis.

```bash
docker compose up -d postgres redis
```

6. Start the app.

```bash
uvicorn app.main:app --reload
```

## E. Verification Steps

1. Check health.

```bash
curl http://localhost:8000/health
```

Expected:

- `database.ok = true`
- `redis.ok = true`
- `api.paper_only = true`
- `broker.configured = true` if Alpaca paper credentials are present

2. Check broker account connectivity.

```bash
curl http://localhost:8000/internal/broker/account
```

Expected:

- paper account id
- status
- currency
- buying power
- equity

3. Check startup logs.

Look for:

- paper startup validation complete
- account sync on startup
- scheduler started
- trade update stream started if enabled

4. Check risk/breaker summary.

```bash
curl http://localhost:8000/internal/risk/summary
curl http://localhost:8000/internal/risk/breakers
```

5. Confirm reconciliation is active.

The reconcile worker runs on the configured interval and logs completion plus mismatch counts.

## F. How To Use The System

### Dry-run orchestration

This runs the full pipeline but does not place paper orders.

```bash
curl -X POST http://localhost:8000/internal/orchestration/run ^
  -H "Content-Type: application/json" ^
  -d "{\"dry_run\": true}"
```

What happens:

- fetch market data
- run strategies
- rank proposals
- evaluate portfolio + risk
- return approvals and rejections
- do not submit orders

### Paper execution orchestration

Before doing this:

1. verify Alpaca paper credentials work
2. confirm breakers are not active
3. set `ENABLE_PAPER_EXECUTION=true` in `.env`
4. restart the app

Then run:

```bash
curl -X POST http://localhost:8000/internal/orchestration/run ^
  -H "Content-Type: application/json" ^
  -d "{\"dry_run\": false}"
```

This is the only built-in action that can submit paper orders through the orchestration flow.

### Dry-run proposal evaluation

You can manually evaluate a proposal without using the strategies.

```bash
curl -X POST http://localhost:8000/internal/proposals/evaluate ^
  -H "Content-Type: application/json" ^
  -d "{\"proposal_id\":\"manual-1\",\"strategy_id\":\"manual\",\"strategy_version\":\"v1\",\"symbol\":\"AAPL\",\"side\":\"buy\",\"entry_price\":100,\"stop_price\":98,\"take_profit_price\":104,\"requested_qty\":10}"
```

### Metrics endpoint

```bash
curl http://localhost:8000/internal/metrics
```

### Daily reporting endpoint

```bash
curl http://localhost:8000/internal/reporting/daily
```

### Risk and breaker endpoints

```bash
curl http://localhost:8000/internal/risk/summary
curl http://localhost:8000/internal/risk/breakers
curl http://localhost:8000/internal/risk/kill-switch
```

### Kill switch usage

Activate:

```bash
curl -X POST http://localhost:8000/internal/risk/kill-switch ^
  -H "Content-Type: application/json" ^
  -d "{\"is_active\": true, \"reason\": \"manual stop\"}"
```

Deactivate:

```bash
curl -X POST http://localhost:8000/internal/risk/kill-switch ^
  -H "Content-Type: application/json" ^
  -d "{\"is_active\": false}"
```

When active, the kill switch blocks proposal approval and therefore prevents execution.

## G. Safety Notes

- This system is paper trading only.
- `TRADING_MODE` must remain `paper`.
- `ALPACA_API_BASE_URL` must remain the Alpaca paper endpoint.
- `ENABLE_PAPER_EXECUTION=false` is the safe default and keeps orchestration in dry-run mode.
- The approval path is mandatory: strategy -> portfolio -> risk -> execution.
- Strategies do not place orders directly.
- Execution requires approved proposals and stop-loss protection.
- Reconciliation and the stream are the source of truth for order and position lifecycle updates.

To stop trading safely:

1. activate the kill switch
2. set `ENABLE_PAPER_EXECUTION=false`
3. restart the app if you changed `.env`
4. optionally stop the app process

## H. Troubleshooting

### Missing env vars

Symptoms:

- startup validation fails
- `/internal/broker/account` returns `503`

Check:

- `ALPACA_API_KEY`
- `ALPACA_API_SECRET`
- `TRADING_MODE=paper`
- `ALPACA_API_BASE_URL=https://paper-api.alpaca.markets`

### Broker connection issues

Symptoms:

- startup fails during broker validation
- `/internal/broker/account` errors

Check:

- paper keys are correct
- paper endpoint is correct
- network access to Alpaca is available

### Database connection issues

Symptoms:

- `/health` shows `database.ok = false`
- startup fails on schema creation

Check:

- Postgres container is running
- `DATABASE_URL` points to the right host and port

### Redis issues

Symptoms:

- `/health` shows `redis.ok = false`

Check:

- Redis container is running
- `REDIS_URL` points to the right host and port

### Stream disconnects

Symptoms:

- warning logs about stream retries

Notes:

- the stream has built-in exponential backoff
- reconciliation still helps keep state aligned during interruptions

### Reconciliation mismatch warnings

Symptoms:

- warning logs with mismatch counts
- reconciliation mismatch alert events

Meaning:

- local state and Alpaca state differ

Action:

- inspect recent orders and positions
- rerun or wait for reconciliation
- verify paper account state through Alpaca

## I. Current Limitations

Intentionally not implemented yet:

- live trading
- backtesting and replay
- parameter optimization
- advanced dashboards
- external alert delivery
- advanced cancel/replace and signal-invalidation execution management
- deep position management logic from strategies

Next logical phases:

- richer monitoring and alert transports
- research/backtesting layer
- optimization and evaluation tooling
- more advanced execution lifecycle management
