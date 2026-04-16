Below is a ready-to-paste Markdown file for a new Alpaca paper-trading agent. I designed it around Alpaca’s current paper environment, Trading API, market-data API, WebSocket order/account updates, and official SDK support. Alpaca paper trading is free, uses separate paper credentials and the `https://paper-api.alpaca.markets` base URL, simulates fills from real-time quotes, and offers official SDKs including `alpaca-py`. Alpaca’s free Basic trading/data plan includes IEX real-time equities, historical data since 2016 with a latest-15-minute restriction on historical requests, and limited WebSocket subscriptions for equities; order handling supports market, limit, stop, stop-limit, trailing-stop, bracket/OCO/OTO patterns for equities, and trade/account updates are available via the paper trading stream. ([Alpaca API Docs][1])


# Alpaca Paper Trading Agent — Full Architecture and Implementation Plan

## 1. Goal

Build a production-style **paper trading agent** for Alpaca that is:

- safe for paper trading first,
- modular and easy to extend,
- affordable to run,
- flexible enough to support multiple strategies,
- observable and testable,
- able to graduate later to live trading with minimal code changes.

This design intentionally avoids the weaknesses of the previous agent:
- no prompt-only discipline,
- no uncontrolled churn,
- no weak trade lifecycle management,
- no direct “LLM says trade -> place order” path,
- no fee-blind micro-trading,
- no weak portfolio state.

---

## 2. Design Principles

1. **Deterministic execution, probabilistic intelligence**
   - Strategy generation may use ML/LLM or rule-based logic.
   - Execution, risk, compliance, and portfolio constraints must be deterministic.

2. **Stateful trading, not cycle-by-cycle impulsive trading**
   - Every position must have a lifecycle and explicit state.

3. **Paper-first, live-ready**
   - Paper and live should share the same codebase.
   - Environment/config should be the only switch.

4. **Event-driven where needed, scheduled where cheaper**
   - Use streaming for order/account updates.
   - Use scheduled jobs for scans, ranking, and slower orchestration.

5. **Low-cost default stack**
   - Prefer Python, open-source infra, and simple deploy targets.
   - Add paid services only when they clearly improve safety or reliability.

---

## 3. Alpaca Constraints and Opportunities

### What Alpaca gives us
- Paper trading environment with separate paper credentials and paper endpoint.
- REST trading API.
- Market data API over HTTP and WebSocket.
- WebSocket trade/account/order updates.
- Official SDKs, especially `alpaca-py`.
- Support for advanced order handling like bracket/OCO/OTO and trailing stops for supported instruments.

### Important practical implication
For a personal, affordable paper-trading system, the **default free/basic path should focus on U.S. equities with realistic but not over-aggressive strategies**, and avoid architectures that depend on expensive full-market feeds unless later needed.

---

## 4. Recommended Technology Stack

## 4.1 Core language
- **Python 3.12+**

Why:
- best fit for quant research + trading ops,
- official Alpaca Python SDK,
- strongest ecosystem for backtesting, analytics, and orchestration,
- lower development cost than Java/C# for this use case.

## 4.2 Core application framework
- **FastAPI** for internal APIs and control plane
- **Pydantic v2** for typed config, schemas, and validation

Why:
- fast to build,
- typed,
- easy internal dashboards/API hooks,
- ideal for service-style architecture.

## 4.3 Data + storage
- **PostgreSQL** as the source of truth
- **Redis** for cache, locks, rate limiting, and ephemeral state
- **Parquet files on disk/object storage** for historical research snapshots

Why:
- PostgreSQL is affordable, durable, and strong for transactional/stateful systems.
- Redis is cheap and solves real-time coordination cleanly.
- Parquet is great for analytics and replay.

## 4.4 Task orchestration
Choose one of these:

### Affordable default
- **APScheduler** inside control service for simple scheduled tasks

### Better scalable option
- **Celery + Redis**

### Best modern workflow option
- **Prefect** if you want cleaner orchestration and observability later

Recommendation:
- start with **APScheduler**,
- move to **Celery** only if task volume grows.

## 4.5 Broker and market integration
- **alpaca-py** for trading/data integration

## 4.6 Analytics / research
- pandas
- numpy
- scipy
- statsmodels
- vectorbt or backtesting.py for research layer
- matplotlib / plotly for analysis

## 4.7 Monitoring
- **Structured logging** with `structlog` or JSON logging
- **Prometheus + Grafana** if self-hosting and you want robust metrics
- Simpler affordable version:
  - JSON logs
  - health endpoints
  - Telegram/Slack alerts
  - daily report email

## 4.8 Deployment
### Cheapest good option
- Single VM on:
  - Hetzner
  - DigitalOcean
  - AWS Lightsail

### Alternative
- Railway / Render for control plane only, but a VM is usually better for a persistent trading worker.

## 4.9 Containers
- **Docker Compose** for:
  - app
  - postgres
  - redis
  - optional Grafana/Prometheus

---

## 5. High-Level Architecture

```text
                        +-------------------------+
                        |   Web / CLI Control     |
                        |   FastAPI Admin Layer   |
                        +-----------+-------------+
                                    |
                                    v
+------------------------------------------------------------------+
|                         Control Plane                             |
| - strategy registry                                               |
| - scheduler                                                       |
| - config management                                               |
| - deployment mode (paper/live)                                   |
| - kill switch                                                     |
| - reporting                                                       |
+-------------------+---------------------+--------------------------+
                    |                     |
                    |                     |
                    v                     v
        +--------------------+   +-----------------------+
        |  Portfolio Engine  |   |   Risk Engine         |
        | - current exposure |   | - pre-trade checks    |
        | - positions        |   | - post-trade checks   |
        | - capital budgets  |   | - drawdown guard      |
        | - correlation caps |   | - max turnover        |
        +----------+---------+   +-----------+-----------+
                   |                         |
                   +------------+------------+
                                |
                                v
                      +----------------------+
                      |   Decision Engine    |
                      | - strategy signals   |
                      | - ranking            |
                      | - regime filter      |
                      | - optional LLM layer |
                      +----------+-----------+
                                 |
                                 v
                      +----------------------+
                      |  Execution Engine    |
                      | - order translator   |
                      | - bracket logic      |
                      | - idempotency        |
                      | - retry handling     |
                      +----------+-----------+
                                 |
               +-----------------+------------------+
               |                                    |
               v                                    v
+-------------------------------+      +-----------------------------+
|   Alpaca Trading API          |      | Alpaca Market Data API      |
|   REST + trade_updates stream |      | HTTP + WebSocket            |
+-------------------------------+      +-----------------------------+

                                 |
                                 v
                      +----------------------+
                      |   State Store        |
                      | PostgreSQL + Redis   |
                      +----------------------+
````

## 6. Core Services

## 6.1 Market Data Service

Responsibilities:

* fetch watchlist prices and bars,
* subscribe to real-time updates where needed,
* normalize Alpaca data into internal schema,
* cache current bars/quotes in Redis,
* write canonical market snapshots to PostgreSQL/Parquet.

Inputs:

* symbols,
* timeframes,
* account plan constraints,
* market calendar.

Outputs:

* normalized OHLCV bars,
* live quote/trade snapshots,
* session metadata.

Rules:

* do not let strategy code call Alpaca directly,
* all market access should go through this service or a shared client adapter.

---

## 6.2 Strategy Engine

Responsibilities:

* run signal generation,
* score opportunities,
* decide entries/exits/adjustments,
* produce **proposals**, not executable orders.

Output example:

```json
{
  "symbol": "AAPL",
  "strategy_id": "mean_reversion_v1",
  "intent": "enter_long",
  "confidence": 0.73,
  "expected_holding_minutes": 180,
  "entry_style": "limit_pullback",
  "thesis": "short-term oversold inside higher timeframe uptrend",
  "invalidations": [
    "close_below_prev_day_low",
    "time_stop_240m"
  ]
}
```

Important:

* strategy output must be **broker-agnostic**,
* no direct order objects here.

---

## 6.3 Portfolio Engine

Responsibilities:

* maintain position ledger,
* allocate capital across strategies,
* manage portfolio-level risk,
* compute current exposure by:

  * symbol,
  * sector,
  * beta bucket,
  * strategy,
  * side,
  * correlation cluster.

This is where we fix one of the biggest old-agent problems:

* no more “many small trades just because the agent found them”.

The portfolio engine should decide:

* whether this trade deserves capital,
* whether it conflicts with open positions,
* whether a stronger opportunity should replace a weaker one.

---

## 6.4 Risk Engine

Responsibilities:

* deterministic pre-trade and post-trade control,
* no optional compliance.

Checks:

* max position size by symbol,
* max gross exposure,
* max net exposure,
* sector concentration,
* strategy concentration,
* max daily loss,
* max account drawdown,
* max turnover per day,
* cooldown after exit,
* minimum expected edge,
* minimum stop distance,
* minimum reward/risk,
* session rule checks,
* no trading during restricted windows if configured.

This is where the new system becomes “full proof” compared with the old one.

### Hard rule examples

* do not open a new position if estimated edge < estimated cost × threshold
* do not flip side within `N` minutes unless hard stop or hard invalidation triggered
* do not open if position count already above allowed cap
* do not open correlated positions above cluster budget
* do not place order without attached exit plan

---

## 6.5 Execution Engine

Responsibilities:

* convert approved proposals into Alpaca orders,
* attach bracket/OCO/OTO logic where appropriate,
* manage order lifecycle,
* reconcile fills with local state,
* retry safely,
* guarantee idempotency.

Execution rules:

* market orders only when urgency is high,
* limit orders for normal entries,
* brackets for most position entries,
* trailing logic only when strategy explicitly supports it,
* all submitted orders must carry:

  * `client_order_id`,
  * strategy id,
  * version,
  * correlation/trade group id,
  * risk snapshot hash.

### Idempotency

Every trade intent gets a unique id:
`trade_intent_id = hash(strategy_id, symbol, side, bar_timestamp, thesis_version)`

If the worker restarts, it should not duplicate the same order.

---

## 6.6 Event Ingestion / Trade Update Service

Responsibilities:

* subscribe to Alpaca `trade_updates`,
* consume order fill/cancel/replace updates,
* update local order and position state immediately,
* emit internal events.

Internal event examples:

* `order_submitted`
* `order_partially_filled`
* `order_filled`
* `stop_loss_triggered`
* `take_profit_filled`
* `position_closed`
* `reconciliation_mismatch`

This service is essential. It turns the system from polling-only to stateful and robust.

---

## 6.7 Reconciliation Service

Responsibilities:

* compare Alpaca account/orders/positions with local database,
* detect mismatches,
* self-heal when safe,
* alert when unsafe.

Run:

* every minute during market hours,
* on startup,
* after reconnect,
* after any fatal exception.

Without reconciliation, paper systems drift silently.

---

## 6.8 Reporting & Analytics Service

Responsibilities:

* end-of-day report,
* trade attribution,
* turnover,
* holding time,
* realized vs unrealized PnL,
* strategy-wise expectancy,
* slippage proxy,
* paper-vs-backtest divergence analysis.

Reports:

* daily HTML/Markdown report,
* Telegram summary,
* CSV export,
* dashboard API.

---

## 7. Recommended Strategy Architecture

## 7.1 Strategy types supported

Build the framework to support multiple strategies from day one:

* trend-following
* mean reversion
* breakout
* opening range
* news/sentiment-assisted
* market regime filter
* portfolio hedging overlay

## 7.2 Strategy interface

Every strategy must implement:

```python
class Strategy:
    id: str
    version: str

    async def prepare(self, market_ctx, portfolio_ctx): ...
    async def generate_candidates(self) -> list[TradeIntent]: ...
    async def manage_open_positions(self, positions, market_ctx) -> list[PositionAction]: ...
```

This keeps the system extensible and avoids a monolithic “god agent”.

---

## 8. Should You Use an LLM?

## Recommendation

Use an LLM only as an **assistant layer**, not the primary execution brain.

Good LLM uses:

* daily market summary,
* explain why a rule-based trade was taken,
* classify news into risk buckets,
* detect anomalies in logs,
* generate natural-language reports,
* help tune watchlists.

Bad LLM uses:

* final order placement authority,
* minute-by-minute direct buy/sell decisions without hard constraints,
* replacing deterministic risk controls.

### Best pattern

```text
Deterministic strategy signal
        +
Optional LLM commentary / context enrichment
        ->
Portfolio + Risk Engine
        ->
Execution Engine
```

If budget matters, skip the LLM in version 1 and add it only after the deterministic core is stable.

---

## 9. State Model

Use explicit state tables.

## 9.1 Tables

* `accounts`
* `positions`
* `orders`
* `fills`
* `trade_intents`
* `trade_lifecycles`
* `strategy_runs`
* `market_snapshots`
* `alerts`
* `risk_events`
* `reconciliation_events`

## 9.2 Position lifecycle state machine

```text
IDEA
 -> APPROVED
 -> ORDER_PENDING
 -> PARTIALLY_FILLED
 -> OPEN
 -> REDUCING
 -> CLOSED
 -> ARCHIVED
```

Exceptional states:

* `REJECTED`
* `CANCELLED`
* `ERROR`
* `RECONCILE_REQUIRED`

This directly solves the old agent’s lack of strong trade state.

---

## 10. Risk Architecture

## 10.1 Pre-trade risk checks

* account enabled?
* market session valid?
* symbol tradable?
* buying power sufficient?
* max open positions exceeded?
* per-symbol exposure exceeded?
* portfolio correlation threshold exceeded?
* daily loss breaker active?
* cooldown active?
* minimum liquidity / spread filter passed?
* expected edge > trading cost threshold?
* stop distance valid?
* reward/risk valid?

## 10.2 Post-trade risk checks

* exposure drift
* stop/target placement confirmation
* fill too far from model price
* unexpected partial fill
* stale open orders
* orphaned position
* unintended position reversal
* repeated failed orders

## 10.3 Circuit breakers

At least these:

* daily drawdown breaker
* max rejected orders per window
* max API failures per window
* max reconciliation mismatches
* max turnover
* max same-symbol churn
* manual kill switch

---

## 11. Execution Rules

## 11.1 Order policy

Default:

* entry: limit
* exit protection: bracket or OCO
* emergency stop: marketable protective action
* avoid naked positions without exit instructions

## 11.2 Session policy

For version 1:

* trade only regular U.S. market hours
* avoid extended-hours complexity initially
* no overnight holds unless strategy explicitly supports it

## 11.3 Repricing policy

* max replace attempts per order
* expire stale entries
* do not chase indefinitely
* if signal degrades while entry unfilled, cancel

## 11.4 No-churn rules

* minimum hold time by strategy
* side-flip cooldown
* no same-symbol reopen within X minutes after stop unless new regime trigger
* per-symbol daily turnover cap

This is one of the highest-value upgrades over the old design.

---

## 12. Market Data Design

## 12.1 Version 1 affordable setup

Focus on:

* equities only
* few timeframes: 1m, 5m, 15m, daily
* watchlist-based streaming, not “everything”

## 12.2 Data layers

* **Live cache** in Redis
* **Canonical bars** in PostgreSQL/Parquet
* **Indicator cache** to avoid recomputation

## 12.3 Session awareness

Use market calendar handling for:

* pre-market
* regular hours
* half days
* holidays
* closing windows

---

## 13. Observability and Reliability

## 13.1 Logging

Every action must be logged with:

* correlation id
* trade_intent_id
* strategy id
* symbol
* event type
* latency
* broker response
* state before/after

## 13.2 Metrics

Track:

* signal count
* approved count
* rejected count
* order success rate
* partial fill rate
* average hold time
* turnover
* PnL by strategy
* realized/unrealized PnL
* drawdown
* reconciliation mismatches
* stream reconnect count
* API latency

## 13.3 Alerts

Send alert on:

* order rejection
* missing stop
* reconciliation mismatch
* circuit breaker activation
* process restart
* disconnected stream
* daily report ready

Telegram is the cheapest practical first option.

---

## 14. Security

* keep Alpaca paper keys in `.env` or secret manager
* never hardcode credentials
* separate paper and live configs strictly
* add an explicit `TRADING_MODE=paper`
* refuse startup if `TRADING_MODE=live` and live safeguards are not enabled
* use least-privilege hosting and private database networking

---

## 15. Suggested Repository Structure

```text
alpaca-paper-agent/
├── app/
│   ├── api/
│   ├── core/
│   │   ├── config.py
│   │   ├── logging.py
│   │   ├── enums.py
│   │   └── clock.py
│   ├── broker/
│   │   ├── alpaca_client.py
│   │   ├── trading_adapter.py
│   │   ├── market_data_adapter.py
│   │   └── stream_adapter.py
│   ├── market_data/
│   │   ├── service.py
│   │   ├── indicators.py
│   │   └── cache.py
│   ├── strategies/
│   │   ├── base.py
│   │   ├── trend_following.py
│   │   ├── mean_reversion.py
│   │   └── registry.py
│   ├── portfolio/
│   │   ├── engine.py
│   │   ├── sizing.py
│   │   └── correlation.py
│   ├── risk/
│   │   ├── engine.py
│   │   ├── rules.py
│   │   └── breakers.py
│   ├── execution/
│   │   ├── engine.py
│   │   ├── order_factory.py
│   │   ├── router.py
│   │   └── reconciliation.py
│   ├── state/
│   │   ├── models.py
│   │   ├── repository.py
│   │   └── migrations/
│   ├── reporting/
│   │   ├── service.py
│   │   └── templates/
│   └── workers/
│       ├── scheduler.py
│       ├── stream_worker.py
│       └── reconcile_worker.py
├── tests/
├── notebooks/
├── docker-compose.yml
├── .env.example
├── Makefile
└── README.md
```

---

## 16. Implementation Plan

## Phase 0 — Project Foundation

Goal: create a stable skeleton.

Tasks:

* initialize repo
* setup Python project
* add `ruff`, `black`, `mypy`, `pytest`
* add FastAPI skeleton
* add Docker Compose
* add PostgreSQL and Redis
* add `.env.example`
* add config validation with Pydantic
* add structured logging

Deliverable:

* app boots locally,
* health endpoint works,
* DB and Redis connected.

---

## Phase 1 — Alpaca Integration

Goal: connect safely to paper account.

Tasks:

* implement Alpaca REST client wrapper
* implement market data wrapper
* implement trade updates stream consumer
* add startup validation:

  * keys present
  * mode is paper
  * account reachable
* create account snapshot ingestion
* store orders/positions/fills locally

Deliverable:

* can fetch account,
* can fetch bars,
* can listen to trade updates,
* can place and cancel a paper order in test mode.

---

## Phase 2 — State and Reconciliation

Goal: make the system stateful and trustworthy.

Tasks:

* create DB models
* store trade intents, orders, fills, positions
* build reconciliation loop
* add idempotency layer
* add restart-safe state recovery
* add orphan position/order detection

Deliverable:

* restart does not lose local truth,
* local state matches Alpaca after reconciliation.

---

## Phase 3 — Risk and Portfolio Core

Goal: prevent bad behavior before strategy goes live.

Tasks:

* implement risk rules
* implement portfolio capital allocation
* implement correlation-aware exposure buckets
* implement cooldown and anti-churn rules
* add circuit breakers
* add kill switch

Deliverable:

* system rejects low-quality or unsafe trades before execution.

---

## Phase 4 — Strategy Framework

Goal: allow multiple clean strategies.

Tasks:

* implement strategy base class
* implement first two deterministic strategies:

  * trend-following
  * mean-reversion
* implement candidate ranking
* implement position management hooks
* add strategy-specific configs

Deliverable:

* strategies produce standardized trade intents,
* no direct broker calls from strategy code.

---

## Phase 5 — Execution Engine

Goal: broker-safe order placement.

Tasks:

* build order factory
* translate intents into Alpaca orders
* attach bracket/OCO/OTO where needed
* support cancel/replace
* handle partial fills
* confirm protective legs
* add stale order logic

Deliverable:

* approved trade intents convert into controlled paper orders.

---

## Phase 6 — Reporting and Monitoring

Goal: make the system observable.

Tasks:

* daily report generator
* Telegram alerts
* metrics endpoint
* trade journal page/API
* strategy performance table
* churn / turnover report
* reconciliation mismatch report

Deliverable:

* operator can see what happened and why.

---

## Phase 7 — Research and Optimization Layer

Goal: improve strategy quality without destabilizing runtime.

Tasks:

* backtest harness
* paper-vs-backtest comparison
* parameter sweep tools
* expectancy and turnover analysis
* cost-aware evaluation

Deliverable:

* controlled iteration loop for improving strategy quality.

---

## 17. MVP Scope

To avoid building too much too early, the MVP should include only:

* Alpaca paper integration
* equities only
* watchlist of 10–30 symbols
* 1–2 deterministic strategies
* bracket-protected entries
* PostgreSQL state
* Redis cache/locks
* reconciliation
* Telegram alerts
* daily report
* dashboard API

Avoid in MVP:

* options
* crypto
* full LLM-driven trading
* ultra-high-frequency logic
* multi-broker routing
* advanced UI
* complex distributed microservices

---

## 18. Cost-Minimized Deployment Plan

## Cheapest serious setup

* 1 small VM
* Docker Compose
* FastAPI app
* PostgreSQL
* Redis
* local disk backups
* Telegram alerts

Approximate service profile:

* low monthly cost
* good enough for paper trading
* simple maintenance
* easy migration later

## When to scale

Move to:

* managed Postgres
* managed Redis
* separate workers
* Prometheus/Grafana
* object storage for research artifacts

only after the paper agent proves stable.

---

## 19. Testing Plan

## 19.1 Unit tests

* indicators
* strategy outputs
* risk rules
* order factory
* sizing
* state transitions

## 19.2 Integration tests

* Alpaca paper account connectivity
* order submit/cancel
* trade_updates handling
* reconciliation loop

## 19.3 Simulation tests

* replay historical bars through strategy engine
* event replay into portfolio/risk/execution stack

## 19.4 Chaos tests

* stream disconnect
* duplicate events
* partial fill
* DB restart
* Redis outage
* API timeout

---

## 20. Non-Negotiable Safety Rules

1. No trade without stored trade intent.
2. No order without idempotency key.
3. No new position without explicit exit logic.
4. No strategy can bypass risk engine.
5. No execution worker can bypass portfolio engine.
6. No live trading mode without separate approval path.
7. Reconciliation must run continuously.
8. Circuit breakers must override all strategies.
9. Paper and live keys must be isolated.
10. Manual kill switch must always exist.

---

## 21. Suggested Build Order (Practical)

Week 1:

* repo skeleton
* config
* logging
* Docker
* DB/Redis
* Alpaca connectivity

Week 2:

* order + account models
* trade_updates consumer
* reconciliation
* basic admin endpoints

Week 3:

* risk engine
* portfolio engine
* anti-churn and cooldown logic

Week 4:

* first deterministic strategy
* candidate ranking
* order factory
* execution engine

Week 5:

* second strategy
* reporting
* Telegram alerts
* metrics

Week 6:

* backtest/paper comparison
* cleanup
* deployment hardening
* restart recovery tests

---

## 22. Final Recommendation

Build this new agent as a **deterministic, event-aware, stateful trading platform with optional AI assistance**, not as an LLM-first trading bot.

### Best practical stack

* Python
* FastAPI
* alpaca-py
* PostgreSQL
* Redis
* Docker Compose
* APScheduler
* Telegram alerts
* VM deployment

This stack is:

* affordable,
* flexible,
* easy to hire for,
* good for paper trading,
* strong enough to evolve into a more advanced system later.

### Most important architectural decision

Use the LLM only for:

* research,
* ranking support,
* summaries,
* anomaly explanation,
* report generation,

and **never as the final unchecked trading authority**.

That is the single biggest lesson carried forward from the previous agent.

```