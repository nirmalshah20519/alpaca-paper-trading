# Alpaca Paper Agent

Paper-only Alpaca trading MVP built from `plan.md` with FastAPI, `alpaca-py`, PostgreSQL, Redis, APScheduler, and a deterministic proposal -> approval -> execution pipeline.

## What It Supports

- paper trading only
- startup validation and account sync
- trade update stream ingestion
- reconciliation
- deterministic strategies
- portfolio and risk approval
- optional paper execution through internal orchestration
- lightweight metrics and daily summary reporting

## Quick Start

1. Copy `.env.example` to `.env`
2. Fill in Alpaca paper credentials
3. Keep `.env` local only and never commit real credentials
4. Start Postgres and Redis:

```bash
docker compose up -d postgres redis
```

5. Install dependencies:

```bash
pip install -r requirements/dev.txt
```

6. Run the API:

```bash
uvicorn app.main:app --reload
```

7. Check health:

```bash
curl http://localhost:8000/health
```

## Important Safety Defaults

- `TRADING_MODE=paper` is required
- `ALPACA_API_BASE_URL` must remain the paper endpoint
- `ENABLE_PAPER_EXECUTION=false` by default
- the only built-in path that can submit paper orders is `POST /internal/orchestration/run` with `{"dry_run": false}` and `ENABLE_PAPER_EXECUTION=true`
- strategies do not call the broker directly
- execution does not bypass portfolio, risk, state, or reconciliation

## Key Internal Endpoints

- `GET /health`
- `GET /internal/broker/account`
- `GET /internal/risk/summary`
- `GET /internal/risk/breakers`
- `GET /internal/risk/kill-switch`
- `POST /internal/risk/kill-switch`
- `POST /internal/proposals/evaluate`
- `POST /internal/orchestration/run`
- `GET /internal/metrics`
- `GET /internal/reporting/daily`

## Full Operator Guide

See [RUN.md](/d:/Projects/alpaca-paper-trading/RUN.md) for complete setup, verification, dry-run usage, paper execution usage, troubleshooting, and current limitations.
