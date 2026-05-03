# Alpaca + OpenAI Trading Signal System — Improved Coding-Agent Plan

## 0. Goal

Build a secure, object-oriented trading service that:

1. Uses **Alpaca** for both market data and trade execution.
2. Uses deterministic calculators for all numeric work: indicators, risk metrics, liquidity checks, position sizing, PnL, target/stop checks.
3. Uses an LLM only as a constrained decision layer over compact precomputed summaries.
4. Keeps LLM input/output token usage low and predictable.
5. Runs two independent loops:
   - Entry opportunity scanner.
   - Open-order monitor / exit manager.
6. Uses thread-safe shared state and CSV persistence.
7. Validates every trade signal before execution.
8. Supports easy LLM migration through one generic `AskLLM` abstraction.

Default mode must be **PAPER**. Real trading must only happen when `TRADING_MODE=REAL` is explicitly set.

---

## 1. Hard Environment Constraint

Only these 4 values can be provided in `.env`:

```env
ALPACA_API_KEY=your_alpaca_key
ALPACA_API_SECRET=your_alpaca_secret
OPENAI_API_KEY=your_openai_key
TRADING_MODE=PAPER
```

Allowed `TRADING_MODE` values:

```txt
PAPER
REAL
```

No model name, thresholds, time intervals, symbols, or risk limits should be read from `.env`.

All other constants must live in version-controlled config files:

```txt
config/settings.py
config/risk_limits.py
config/strategy_params.py
config/prompts.py
config/llm_config.py
```

---

## 2. Core Design Principles

### 2.1 Deterministic First, LLM Second

Correct flow:

```txt
Alpaca Data
    -> Deterministic Calculators
    -> Compact Decision Payload
    -> AskLLM
    -> Pydantic JSON Schema Validation
    -> Deterministic Validator
    -> Alpaca Executor
    -> Thread-safe CSV Storage
```

Incorrect flow:

```txt
Raw market data
    -> LLM calculates indicators / risk / PnL
    -> Executor
```

The LLM must never calculate:
- risk metrics
- PnL
- buying power
- max quantity
- spread safety
- portfolio exposure
- stop-loss validity
- Alpaca order payloads

The LLM only chooses from constrained actions using supplied compact metrics.

---

## 3. Recommended Tech Stack

Use Python for v1.

Required packages:

```txt
alpaca-py
openai
pydantic
pandas
numpy
python-dotenv
tenacity
loguru
portalocker
pytest
```

Optional later:

```txt
apscheduler
polars
quantstats
empyrical
pyportfolioopt
ruff
mypy
```

Use Python standard library threading first:

```txt
threading
queue
time
datetime
uuid
json
csv
pathlib
```

Avoid over-engineering with Redis/Kafka/database in v1. Keep it simple and local.

---

## 4. Object-Oriented Architecture

The service should be easy to understand and extend.

### 4.1 High-Level Classes

```txt
TradingService
├── AppConfig
├── AppState
├── ThreadManager
│
├── AlpacaGateway
│   ├── MarketDataService
│   ├── AccountService
│   └── AssetSelector
│
├── CalculatorEngine
│   ├── IndicatorCalculator
│   ├── RiskCalculator
│   ├── LiquidityCalculator
│   ├── PositionSizer
│   └── PnLCalculator
│
├── AskLLM
│   ├── OpenAIProvider
│   ├── PromptBuilder
│   ├── TokenBudgeter
│   └── LLMResponseParser
│
├── SignalValidator
│   ├── SchemaValidator
│   ├── AccountValidator
│   ├── RiskValidator
│   └── DuplicateTradeValidator
│
├── TradeExecutor
│   ├── OrderMapper
│   ├── AlpacaOrderSubmitter
│   └── ExecutionRecorder
│
└── StorageManager
    ├── CsvStore
    ├── OpenOrderStore
    ├── PastOrderStore
    ├── SignalLogStore
    └── RejectedSignalStore
```

---

## 5. Project Structure

```txt
trading_signal_system/
│
├── main.py
├── requirements.txt
├── .env.example
├── README.md
├── plan.md
│
├── config/
│   ├── settings.py
│   ├── risk_limits.py
│   ├── strategy_params.py
│   ├── prompts.py
│   └── llm_config.py
│
├── app/
│   ├── core/
│   │   ├── config.py
│   │   ├── state.py
│   │   ├── thread_manager.py
│   │   ├── models.py
│   │   └── exceptions.py
│   │
│   ├── datasource/
│   │   ├── alpaca_gateway.py
│   │   ├── market_data_service.py
│   │   ├── account_service.py
│   │   └── asset_selector.py
│   │
│   ├── calculator/
│   │   ├── calculator_engine.py
│   │   ├── indicators.py
│   │   ├── risk_metrics.py
│   │   ├── liquidity.py
│   │   ├── position_sizing.py
│   │   ├── pnl.py
│   │   └── compact_summary.py
│   │
│   ├── llm/
│   │   ├── ask_llm.py
│   │   ├── providers.py
│   │   ├── prompt_builder.py
│   │   ├── token_budgeter.py
│   │   ├── response_parser.py
│   │   └── schemas.py
│   │
│   ├── validator/
│   │   ├── signal_validator.py
│   │   ├── schema_validator.py
│   │   ├── account_validator.py
│   │   ├── risk_validator.py
│   │   └── duplicate_validator.py
│   │
│   ├── executor/
│   │   ├── trade_executor.py
│   │   ├── order_mapper.py
│   │   └── order_submitter.py
│   │
│   ├── storage/
│   │   ├── csv_store.py
│   │   ├── open_order_store.py
│   │   ├── past_order_store.py
│   │   ├── signal_log_store.py
│   │   └── rejected_signal_store.py
│   │
│   ├── loops/
│   │   ├── asset_refresh_loop.py
│   │   ├── entry_opportunity_loop.py
│   │   ├── open_order_monitor_loop.py
│   │   ├── reconciliation_loop.py
│   │   └── heartbeat_loop.py
│   │
│   └── utils/
│       ├── logger.py
│       ├── time_utils.py
│       └── safe_number.py
│
├── data/
│   ├── open_orders.csv
│   ├── past_orders.csv
│   ├── signal_logs.csv
│   ├── rejected_signals.csv
│   └── service_state.json
│
└── tests/
    ├── test_env_config.py
    ├── test_calculators.py
    ├── test_compact_summary.py
    ├── test_ask_llm_schema.py
    ├── test_validator.py
    ├── test_order_mapper.py
    ├── test_csv_store.py
    └── test_thread_safety.py
```

---

## 6. Shared State and Thread Safety

### 6.1 Independent Runtime Threads

Run these threads independently:

```txt
Thread 1: AssetRefreshLoop
    - Runs on startup and every 1 hour.
    - Updates active top-20 asset list.

Thread 2: EntryOpportunityLoop
    - Runs every 2 minutes.
    - Scans active asset list for new trade opportunities.
    - Does not wait for OpenOrderMonitorLoop.

Thread 3: OpenOrderMonitorLoop
    - Runs every 2 minutes.
    - Monitors existing open orders.
    - Does not wait for EntryOpportunityLoop.

Thread 4: ReconciliationLoop
    - Runs every 10 minutes.
    - Reconciles local CSV state with Alpaca broker state.

Thread 5: HeartbeatLoop
    - Runs every 1 minute.
    - Logs service health.
```

Entry and exit loops must be fully independent. If one loop is slow, blocked, or failing, the other must keep running.

### 6.2 AppState

Create a central thread-safe `AppState`.

```python
class AppState:
    def __init__(self):
        self.asset_list_lock = threading.RLock()
        self.open_orders_lock = threading.RLock()
        self.account_lock = threading.RLock()
        self.execution_lock = threading.RLock()
        self.reconciliation_lock = threading.RLock()

        self.active_assets: list[str] = []
        self.last_asset_refresh_utc: str | None = None
        self.pause_new_entries: bool = False
        self.shutdown_event = threading.Event()
```

### 6.3 Shared Resource Rules

#### `active_assets`

- Written only by `AssetRefreshLoop`.
- Read by `EntryOpportunityLoop`.
- Protect with `asset_list_lock`.
- Readers must copy the list quickly, then release lock.

```python
with app_state.asset_list_lock:
    symbols = list(app_state.active_assets)
```

#### `open_orders.csv`

- Written by Entry loop when a new trade is executed.
- Read by OpenOrderMonitor loop.
- Updated by OpenOrderMonitor loop when an order closes.
- Read by Reconciliation loop.
- Protect with `open_orders_lock`.
- Also use file locking through `portalocker`.

#### Alpaca execution

- Any actual order submission must acquire `execution_lock`.
- This prevents entry and exit threads from submitting conflicting orders for the same symbol at the same time.

```python
with app_state.execution_lock:
    executor.execute_order(...)
```

#### Account state

- Account data can be fetched by both loops.
- Keep no long-held lock during external Alpaca calls.
- Fetch externally first, then update cached state inside a short lock.

### 6.4 Lock Ordering Rule

To avoid deadlocks, always acquire locks in this order if multiple locks are needed:

```txt
asset_list_lock
-> open_orders_lock
-> account_lock
-> execution_lock
-> reconciliation_lock
```

Never acquire them in reverse order.

### 6.5 Same-Job Overlap Prevention

Each loop should have an internal `running_lock`.

If a loop cycle is still running when the next interval arrives, skip that cycle.

```python
if not self.running_lock.acquire(blocking=False):
    logger.warning("Previous cycle still running. Skipping this cycle.")
    return
try:
    self.run_once()
finally:
    self.running_lock.release()
```

---

## 7. Token-Friendly LLM Design

### 7.1 LLM Usage Rule

Do not send:
- full OHLCV dataframes
- raw bars
- raw account objects
- raw positions list unless needed
- long histories
- repeated prompt text per symbol if avoidable
- verbose calculator JSON

Send only compact summaries.

### 7.2 Two-Step Calculation Output

The calculator should produce:

1. Full internal result for logs/debugging.
2. Compact LLM payload for decision making.

```python
full_result = calculator.compute_all(symbol, market_data, account_state)
llm_payload = compact_summary.build_entry_summary(full_result, account_snapshot)
```

Only `llm_payload` is sent to `AskLLM`.

### 7.3 Compact Entry Payload

Use short keys to reduce tokens.

Example:

```json
{
  "task": "entry",
  "sym": "AAPL",
  "cls": "stock",
  "px": 190.25,
  "acct": {
    "eq": 10000.0,
    "cash": 4200.0,
    "bp": 8400.0,
    "open_pos": 2,
    "dd": -0.018,
    "day_pnl": -35.2
  },
  "calc": {
    "trend": "bull",
    "mom": 0.71,
    "rsi": 62.4,
    "vol_reg": "normal",
    "rv20": 0.22,
    "atr": 2.1,
    "var95": 0.028,
    "cvar95": 0.041,
    "mdd60": -0.12,
    "spr": 0.00031,
    "liq": true,
    "qty_max": 2,
    "rr_min": 1.5
  },
  "rules": {
    "actions": ["BUY", "SELL", "SKIP"],
    "prefer_skip": true,
    "short_allowed": false
  }
}
```

### 7.4 Compact Exit Payload

Example:

```json
{
  "task": "exit",
  "sym": "AAPL",
  "side": "buy",
  "qty": 2,
  "entry": 190.25,
  "px": 194.1,
  "target": 195.0,
  "stop": 186.0,
  "pnl": 7.7,
  "pnl_pct": 0.0202,
  "held_min": 84,
  "risk": {
    "target_hit": false,
    "stop_hit": false,
    "trend_now": "bull",
    "vol_reg": "normal"
  },
  "rules": {
    "actions": ["HOLD", "COMPLETE"],
    "complete_if_target_or_stop": true
  }
}
```

### 7.5 Token Budget

Define in `config/llm_config.py`:

```python
LLM_MODEL = "gpt-4o-mini"  # change here only for OpenAI model switch
MAX_INPUT_CHARS_ENTRY = 2500
MAX_INPUT_CHARS_EXIT = 1800
MAX_OUTPUT_TOKENS_ENTRY = 220
MAX_OUTPUT_TOKENS_EXIT = 160
TEMPERATURE = 0.0
```

Use `TokenBudgeter` to reject or compress oversized payloads before calling LLM.

```python
class TokenBudgeter:
    def compact_json(self, payload: dict) -> str:
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

    def enforce_char_budget(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        raise ValueError("LLM payload exceeds configured budget")
```

### 7.6 Output Must Be Tiny JSON

Entry output:

```json
{
  "sym": "AAPL",
  "action": "BUY",
  "conf": 0.72,
  "qty": 2,
  "target": 195.0,
  "stop": 186.0,
  "reason_code": "TREND_MOMENTUM_RISK_OK"
}
```

Exit output:

```json
{
  "sym": "AAPL",
  "action": "HOLD",
  "conf": 0.68,
  "reason_code": "TARGET_NOT_REACHED_RISK_OK"
}
```

Keep verbose natural-language reasons out of the hot path. If needed, generate human-readable summaries later from logs, not during every 2-minute trading cycle.

### 7.7 Reason Codes

Use predefined reason codes instead of long explanation text.

Entry reason codes:

```txt
TREND_MOMENTUM_RISK_OK
BEARISH_SIGNAL_RISK_OK
MIXED_SIGNAL_SKIP
HIGH_VOLATILITY_SKIP
UNSAFE_SPREAD_SKIP
LOW_LIQUIDITY_SKIP
INSUFFICIENT_FUNDS_SKIP
QTY_ZERO_SKIP
DRAWDOWN_LIMIT_SKIP
UNCERTAIN_SKIP
```

Exit reason codes:

```txt
TARGET_REACHED
STOP_REACHED
PNL_PROTECT
RISK_DETERIORATED
TARGET_NOT_REACHED_RISK_OK
HOLDING_PERIOD_TOO_LONG
UNCERTAIN_COMPLETE
UNCERTAIN_HOLD
```

---

## 8. Generic LLM Module: `AskLLM`

The system must use one generic class for all LLM calls.

### 8.1 Purpose

`AskLLM` should hide all provider-specific logic.

If later switching from OpenAI to another provider, only `AskLLM` provider internals should change. Entry flow, exit flow, validator, and executor should remain unchanged.

### 8.2 Interface

```python
class AskLLM:
    def __init__(self, provider: BaseLLMProvider, prompt_builder: PromptBuilder, parser: LLMResponseParser):
        self.provider = provider
        self.prompt_builder = prompt_builder
        self.parser = parser

    def ask_json(self, task: str, payload: dict, schema_type: str) -> dict:
        compact_payload = self.prompt_builder.build(task=task, payload=payload)
        raw = self.provider.complete_json(compact_payload, schema_type=schema_type)
        return self.parser.parse_and_validate(raw, schema_type=schema_type)

    def ask_entry_signal(self, payload: dict) -> "EntrySignal":
        data = self.ask_json(task="entry", payload=payload, schema_type="entry")
        return EntrySignal.model_validate(data)

    def ask_exit_signal(self, payload: dict) -> "ExitSignal":
        data = self.ask_json(task="exit", payload=payload, schema_type="exit")
        return ExitSignal.model_validate(data)
```

### 8.3 Provider Interface

```python
class BaseLLMProvider:
    def complete_json(self, prompt: str, schema_type: str) -> str:
        raise NotImplementedError
```

### 8.4 OpenAI Provider

```python
class OpenAIProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str, temperature: float):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature

    def complete_json(self, prompt: str, schema_type: str) -> str:
        # Use OpenAI JSON/schema mode where available.
        # Return raw JSON string.
        ...
```

### 8.5 Migration Rule

To switch LLM provider:

1. Create a new provider class, for example `AnthropicProvider`, `LocalOllamaProvider`, or `MockLLMProvider`.
2. Keep the same `BaseLLMProvider.complete_json()` method.
3. Do not change entry loop, exit loop, validator, executor, or calculator.

### 8.6 Mock LLM for Tests

Create `MockLLMProvider` for tests.

```python
class MockLLMProvider(BaseLLMProvider):
    def __init__(self, fixed_response: dict):
        self.fixed_response = fixed_response

    def complete_json(self, prompt: str, schema_type: str) -> str:
        return json.dumps(self.fixed_response)
```

All unit tests must use `MockLLMProvider`, not real OpenAI calls.

---

## 9. LLM Schemas

### 9.1 Entry Signal Schema

Use Pydantic.

```python
from pydantic import BaseModel, Field
from typing import Literal

class EntrySignal(BaseModel):
    sym: str
    action: Literal["BUY", "SELL", "SKIP"]
    conf: float = Field(ge=0.0, le=1.0)
    qty: int = Field(ge=0)
    target: float | None = None
    stop: float | None = None
    reason_code: str
```

Rules:

```txt
BUY/SELL:
    qty > 0
    target is not None
    stop is not None

SKIP:
    qty = 0
    target can be null
    stop can be null
```

### 9.2 Exit Signal Schema

```python
class ExitSignal(BaseModel):
    sym: str
    action: Literal["HOLD", "COMPLETE"]
    conf: float = Field(ge=0.0, le=1.0)
    reason_code: str
```

---

## 10. Prompt Design

### 10.1 Entry Prompt

Store in `config/prompts.py`.

```txt
You are a conservative trading decision engine.

You receive compact deterministic metrics only.
You must choose one action: BUY, SELL, or SKIP.

Rules:
- Output JSON only.
- Use only the provided payload.
- Do not invent numbers.
- Do not calculate indicators.
- Do not exceed calc.qty_max.
- Prefer SKIP when signal quality is weak, mixed, risky, illiquid, or uncertain.
- If short_allowed=false, do not SELL unless it is a sell-to-close case explicitly provided.
- If qty_max <= 0, action must be SKIP.
- If liq=false, action must be SKIP.
- If spr is unsafe or high, action must be SKIP.

Output exactly:
{
  "sym": "string",
  "action": "BUY|SELL|SKIP",
  "conf": 0.0,
  "qty": 0,
  "target": null,
  "stop": null,
  "reason_code": "string"
}
```

### 10.2 Exit Prompt

```txt
You are a conservative trade exit decision engine.

You receive compact deterministic open-trade status.
You must choose one action: HOLD or COMPLETE.

Rules:
- Output JSON only.
- Use only the provided payload.
- Do not invent numbers.
- COMPLETE if target_hit=true.
- COMPLETE if stop_hit=true.
- COMPLETE if risk has deteriorated.
- HOLD only if risk remains acceptable.

Output exactly:
{
  "sym": "string",
  "action": "HOLD|COMPLETE",
  "conf": 0.0,
  "reason_code": "string"
}
```

---

## 11. Datasource Module

### 11.1 `AlpacaGateway`

Single object responsible for creating Alpaca clients.

```python
class AlpacaGateway:
    def __init__(self, api_key: str, api_secret: str, trading_mode: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.trading_mode = trading_mode
        self.trading_client = ...
        self.stock_data_client = ...
        self.crypto_data_client = ...
```

Responsibilities:

1. Select paper or live trading client.
2. Create market-data clients.
3. Never expose keys in logs.
4. Provide clients to datasource services.

### 11.2 `MarketDataService`

Responsibilities:

```txt
fetch_latest_quote(symbol)
fetch_latest_trade(symbol)
fetch_latest_price(symbol)
fetch_bars(symbol, timeframe, lookback)
fetch_required_entry_data(symbol)
fetch_required_exit_data(symbol)
```

### 11.3 `AccountService`

Responsibilities:

```txt
get_account_snapshot()
get_positions()
get_open_orders()
get_position(symbol)
```

### 11.4 `AssetSelector`

On startup and every hour:

1. Start from a default liquid universe.
2. Fetch recent bars and volume.
3. Compute opportunity score.
4. Return top 20.
5. If asset selection fails, keep previous active list.
6. If no previous list exists, use safe default symbols.

Default stock universe:

```python
DEFAULT_STOCK_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL", "AMD", "NFLX", "AVGO",
    "SPY", "QQQ", "IWM", "DIA", "PLTR", "COIN", "MARA", "SMCI", "INTC", "BABA",
    "JPM", "BAC", "XOM", "CVX", "UNH", "LLY", "WMT", "COST", "DIS", "PYPL"
]
```

Opportunity score:

```txt
score =
    0.30 * normalized_recent_volume
  + 0.25 * normalized_price_momentum
  + 0.20 * normalized_volatility_expansion
  + 0.15 * normalized_dollar_volume
  + 0.10 * normalized_trend_strength
```

---

## 12. Calculator Module

### 12.1 `CalculatorEngine`

```python
class CalculatorEngine:
    def compute_entry_metrics(self, symbol: str, market_data: dict, account: dict, positions: list[dict]) -> dict:
        ...

    def compute_exit_metrics(self, open_order: dict, market_data: dict, position: dict) -> dict:
        ...
```

### 12.2 Required Entry Metrics

Compute internally:

```txt
latest_price
previous_close
return_5m
return_15m
return_1h
return_1d

sma_20
sma_50
ema_12
ema_26
macd
macd_signal
macd_histogram
trend_direction

rsi_14
roc_10
momentum_score

realized_volatility_20
realized_volatility_50
atr_14
volatility_regime

historical_var_95
historical_cvar_95
max_drawdown_60
current_drawdown
sharpe_60
sortino_60
beta_to_spy

latest_volume
avg_volume_20
relative_volume
bid
ask
spread
spread_pct
is_liquid
is_spread_safe

risk_per_trade_amount
stop_loss_distance
suggested_qty
max_affordable_qty
max_risk_allowed_qty
final_calculated_qty
```

### 12.3 Required Exit Metrics

```txt
symbol
side
qty
entry_price
latest_price
target_price
stop_loss_price
unrealized_pnl
unrealized_pnl_pct
holding_minutes
target_hit
stop_hit
trend_now
volatility_regime
```

### 12.4 NaN Rule

Never send `NaN`, `Infinity`, or `-Infinity` to LLM, validator, storage, or logs.

Use:

```txt
None for unavailable values
0 only when mathematically correct
SKIP-safe flags when data is insufficient
```

---

## 13. Validator Module

Validator is the final safety gate before execution.

### 13.1 Entry Validation

Reject if any rule fails:

```txt
Schema:
- Pydantic schema valid.
- action in BUY/SELL/SKIP.
- conf in [0,1].
- qty integer >= 0.

SKIP:
- Never execute.
- Log to signal log only.

Account:
- account is active.
- trading is not blocked.
- buying power is sufficient.
- cash is sufficient for BUY.
- daily loss limit not breached.
- portfolio drawdown limit not breached.

Asset:
- asset is tradable.
- asset is not halted.
- latest price is fresh.
- spread_pct <= MAX_SPREAD_PCT.
- avg volume >= MIN_AVG_DAILY_VOLUME.

Risk:
- qty <= final_calculated_qty.
- notional <= MAX_POSITION_PCT_OF_EQUITY.
- max loss <= MAX_RISK_PER_TRADE_PCT.
- risk/reward >= MIN_RISK_REWARD_RATIO.
- target and stop are logical:
    BUY: stop < entry < target
    SELL: target < entry < stop
- no duplicate open order for symbol.
- no duplicate open position unless config allows scaling.
- open positions count < MAX_OPEN_POSITIONS.
```

### 13.2 Exit Validation

For v1, exit is simpler but still deterministic:

```txt
- open order exists locally.
- Alpaca position exists for symbol.
- qty does not exceed current position qty.
- exit side is opposite of entry side.
- latest price is fresh.
- account is not blocked.
```

If the LLM says `HOLD`, do not execute.

If target or stop is already hit, the deterministic validator may force `COMPLETE` even if LLM says `HOLD`.

---

## 14. Executor Module

### 14.1 `TradeExecutor`

```python
class TradeExecutor:
    def execute_entry(self, validated_signal: EntrySignal, context: dict) -> dict:
        ...

    def execute_exit(self, open_order: dict, exit_signal: ExitSignal, context: dict) -> dict:
        ...
```

### 14.2 Order Mapping

Entry:

```txt
BUY -> Alpaca side = buy
SELL -> Alpaca side = sell
```

Exit:

```txt
If entry_side=buy, exit side=sell.
If entry_side=sell, exit side=buy.
```

Initial version:

```txt
order_type = market
time_in_force = day for stocks
time_in_force = gtc for crypto if supported
```

### 14.3 Idempotency

Generate client order ID:

```txt
client_order_id = entry-{symbol}-{action}-{utc_timestamp}-{short_uuid}
client_order_id = exit-{symbol}-{utc_timestamp}-{short_uuid}
```

Before submitting:

1. Check local open orders under lock.
2. Check Alpaca open orders.
3. Reject duplicate order for same symbol and same intent.
4. Submit under `execution_lock`.

---

## 15. Storage Module

Use CSV for v1.

Files:

```txt
data/open_orders.csv
data/past_orders.csv
data/signal_logs.csv
data/rejected_signals.csv
```

### 15.1 `CsvStore`

Use `portalocker` for file-level locking plus in-process `RLock`.

```python
class CsvStore:
    def append_row(self, file_path: Path, row: dict) -> None:
        ...

    def read_rows(self, file_path: Path) -> list[dict]:
        ...

    def rewrite_rows_atomic(self, file_path: Path, rows: list[dict]) -> None:
        ...
```

Atomic write rule:

1. Write to temporary file.
2. Flush.
3. Replace original file using atomic rename.

### 15.2 `open_orders.csv`

```csv
local_trade_id,alpaca_order_id,client_order_id,symbol,asset_class,entry_side,qty,entry_order_type,entry_status,entry_price_estimate,target_price,stop_loss_price,max_loss_amount,confidence,reason_code,opened_at,last_checked_at,status
```

### 15.3 `past_orders.csv`

```csv
local_trade_id,entry_alpaca_order_id,exit_alpaca_order_id,symbol,asset_class,entry_side,exit_side,qty,entry_price,exit_price,target_price,stop_loss_price,gross_pnl,pnl_pct,opened_at,closed_at,holding_minutes,entry_reason_code,exit_reason_code,status
```

### 15.4 `signal_logs.csv`

```csv
timestamp,flow,symbol,action,confidence,qty,target,stop,reason_code,validator_status,validator_reason
```

### 15.5 `rejected_signals.csv`

```csv
timestamp,flow,symbol,raw_action,reason_code,rejection_reason,payload_hash
```

---

## 16. Service Flows

## 16.1 Startup Flow

On service init:

```txt
1. Load `.env`.
2. Validate exactly 4 allowed env values.
3. Initialize `AppConfig`.
4. Initialize `AppState`.
5. Initialize `AlpacaGateway`.
6. Initialize datasource services.
7. Initialize calculators.
8. Initialize `AskLLM`.
9. Initialize validators.
10. Initialize executor.
11. Initialize CSV files.
12. Reconcile local open orders with Alpaca.
13. Fetch first top-20 active asset list.
14. Start independent threads.
```

If startup validation fails, stop cleanly.

---

## 16.2 Asset Refresh Loop

Runs:
- immediately on startup
- every 1 hour

Pseudo-code:

```python
class AssetRefreshLoop(BaseLoop):
    interval_seconds = 3600

    def run_once(self):
        new_assets = asset_selector.get_top_20_assets()

        if not new_assets:
            logger.warning("Asset refresh failed. Keeping previous list.")
            return

        with app_state.asset_list_lock:
            app_state.active_assets = new_assets
            app_state.last_asset_refresh_utc = utc_now()
```

---

## 16.3 Entry Opportunity Loop

Runs every 2 minutes.

This loop must not wait for the open-order monitor loop.

Pseudo-code:

```python
class EntryOpportunityLoop(BaseLoop):
    interval_seconds = 120

    def run_once(self):
        if app_state.pause_new_entries:
            logger.warning("New entries paused.")
            return

        with app_state.asset_list_lock:
            symbols = list(app_state.active_assets)

        for symbol in symbols:
            try:
                self.process_symbol(symbol)
            except Exception as e:
                logger.exception(f"Entry processing failed for {symbol}: {e}")

    def process_symbol(self, symbol: str):
        account = account_service.get_account_snapshot()
        positions = account_service.get_positions()
        market_data = market_data_service.fetch_required_entry_data(symbol)

        full_metrics = calculator.compute_entry_metrics(symbol, market_data, account, positions)
        llm_payload = compact_summary.build_entry_summary(full_metrics, account)

        entry_signal = ask_llm.ask_entry_signal(llm_payload)

        validation = signal_validator.validate_entry(
            signal=entry_signal,
            metrics=full_metrics,
            account=account,
            positions=positions
        )

        storage.signal_logs.append_entry_signal(entry_signal, validation)

        if not validation.validated:
            storage.rejected_signals.append(entry_signal, validation.reason)
            return

        with app_state.execution_lock:
            execution_result = executor.execute_entry(validation.signal, validation.context)

        with app_state.open_orders_lock:
            storage.open_orders.append_from_execution(execution_result)
```

Important rules:

1. Continue to next symbol if one fails.
2. Do not crash the loop because of one bad asset.
3. Use timeouts for Alpaca and OpenAI calls.
4. Use retry only for transient errors.
5. Use compact LLM payload only.
6. If LLM fails, treat as `SKIP`.

---

## 16.4 Open Order Monitor Loop

Runs every 2 minutes.

This loop must not wait for the entry opportunity loop.

Pseudo-code:

```python
class OpenOrderMonitorLoop(BaseLoop):
    interval_seconds = 120

    def run_once(self):
        with app_state.open_orders_lock:
            open_orders = storage.open_orders.get_open_orders_copy()

        for open_order in open_orders:
            try:
                self.process_open_order(open_order)
            except Exception as e:
                logger.exception(f"Exit processing failed for {open_order['symbol']}: {e}")

    def process_open_order(self, open_order: dict):
        symbol = open_order["symbol"]

        market_data = market_data_service.fetch_required_exit_data(symbol)
        position = account_service.get_position(symbol)

        exit_metrics = calculator.compute_exit_metrics(open_order, market_data, position)

        # Deterministic fast path:
        # If target or stop is hit, do not waste LLM tokens.
        if exit_metrics["target_hit"] or exit_metrics["stop_hit"]:
            exit_signal = ExitSignal(
                sym=symbol,
                action="COMPLETE",
                conf=1.0,
                reason_code="TARGET_REACHED" if exit_metrics["target_hit"] else "STOP_REACHED"
            )
        else:
            llm_payload = compact_summary.build_exit_summary(exit_metrics)
            exit_signal = ask_llm.ask_exit_signal(llm_payload)

        validation = signal_validator.validate_exit(exit_signal, open_order, exit_metrics)

        if exit_signal.action == "HOLD" and validation.validated:
            storage.open_orders.update_last_checked(symbol, utc_now())
            return

        if not validation.validated:
            storage.rejected_signals.append(exit_signal, validation.reason)
            return

        with app_state.execution_lock:
            execution_result = executor.execute_exit(open_order, exit_signal, validation.context)

        with app_state.open_orders_lock:
            storage.open_orders.mark_closed(open_order["local_trade_id"])
            storage.past_orders.append_from_exit(open_order, execution_result, exit_metrics)
```

Token-saving rule:

```txt
If target hit or stop hit, do not call LLM.
Close deterministically.
```

---

## 16.5 Reconciliation Loop

Runs every 10 minutes.

Responsibilities:

```txt
1. Read local open_orders.csv.
2. Fetch Alpaca positions.
3. Fetch Alpaca open orders.
4. Detect mismatch.
5. If dangerous mismatch exists:
   - set app_state.pause_new_entries = True
   - log reconciliation warning
6. Do not auto-fix dangerous mismatch in v1.
```

Dangerous mismatch examples:

```txt
Local says open, Alpaca has no position and no open order.
Alpaca has position, local file has no open record.
Quantity mismatch.
Duplicate open order for same symbol.
```

---

## 17. Risk Constants

Store in `config/risk_limits.py`.

```python
MAX_RISK_PER_TRADE_PCT = 0.01
MAX_POSITION_PCT_OF_EQUITY = 0.05
MAX_DAILY_LOSS_PCT = 0.03
MAX_PORTFOLIO_DRAWDOWN_PCT = 0.10
MIN_RISK_REWARD_RATIO = 1.5
MAX_SPREAD_PCT = 0.002
MIN_AVG_DAILY_VOLUME = 1_000_000
MAX_OPEN_POSITIONS = 5
MAX_TRADES_PER_DAY = 20
ALLOW_SHORT_SELLING = False
ALLOW_POSITION_SCALING = False
STALE_PRICE_SECONDS = 180
```

Safety default:

```txt
When uncertain, SKIP.
When data is stale, SKIP.
When account data is missing, SKIP.
When validation fails, reject.
```

---

## 18. Strategy Defaults for v1

MVP should support:

```txt
Entry actions:
- BUY
- SKIP

SELL as new short entry:
- disabled by default

SELL allowed only as:
- sell-to-close existing long position
```

After MVP is stable, optionally add:

```txt
short selling
crypto
limit orders
bracket orders
websocket data
database storage
dashboard
backtesting
multi-strategy voting
```

---

## 19. Error Handling

All external calls need:

```txt
timeout
retry with exponential backoff
structured logging
safe fallback
```

Retry only transient errors:

```txt
429 rate limit
500 server error
502 bad gateway
503 unavailable
504 timeout
network timeout
temporary websocket issue
```

Do not retry:

```txt
invalid symbol
insufficient buying power
invalid qty
asset not tradable
account blocked
schema validation failure
validator rejection
```

LLM fallback:

```txt
If LLM fails in entry flow -> SKIP.
If LLM fails in exit flow -> HOLD unless deterministic target/stop is hit.
If target/stop is hit -> COMPLETE without LLM.
```

---

## 20. Logging

Create structured logs for:

```txt
service_start
service_stop
asset_refresh_started
asset_refresh_completed
entry_cycle_started
entry_cycle_completed
exit_cycle_started
exit_cycle_completed
market_data_fetch
calculator_result_summary
llm_payload_size
llm_signal
validator_approved
validator_rejected
order_submit_started
order_submit_success
order_submit_failed
order_completed
csv_write
reconciliation_warning
thread_error
system_error
```

Never log:

```txt
ALPACA_API_KEY
ALPACA_API_SECRET
OPENAI_API_KEY
full raw LLM prompts in production
raw broker auth headers
```

For LLM logs, store:

```txt
payload_hash
payload_char_count
schema_type
response_action
reason_code
```

---

## 21. Testing Plan

### 21.1 Unit Tests

Build tests for:

```txt
env validation
calculator formulas
compact summary generation
NaN removal
Pydantic LLM schemas
AskLLM with MockLLMProvider
validator rejection cases
order mapping
CSV append/read/rewrite
thread-safe locks
```

### 21.2 Integration Tests

Use mocked Alpaca and mocked LLM.

Test:

```txt
startup flow
entry loop one-cycle run
exit loop one-cycle run
asset refresh loop
reconciliation mismatch handling
```

### 21.3 No Live Tests by Default

Tests must not place real Alpaca orders.

Default tests must use:

```txt
TRADING_MODE=PAPER
MockAlpacaGateway
MockLLMProvider
temporary CSV directory
```

---

## 22. Implementation Phases for Coding Agent

### Phase 1 — Skeleton and Config

Build:

```txt
project structure
.env validation with only 4 allowed env variables
AppConfig
AppState
logger
CSV initialization
main.py
```

Acceptance:

```txt
python main.py starts in PAPER mode
invalid env fails cleanly
CSV files created with headers
```

---

### Phase 2 — Thread Framework

Build:

```txt
BaseLoop
ThreadManager
AssetRefreshLoop placeholder
EntryOpportunityLoop placeholder
OpenOrderMonitorLoop placeholder
ReconciliationLoop placeholder
HeartbeatLoop
shutdown_event handling
same-job overlap prevention
```

Acceptance:

```txt
All loops can start and stop cleanly
Entry and exit loops run independently
One loop failure does not stop other loops
```

---

### Phase 3 — Alpaca Datasource

Build:

```txt
AlpacaGateway
MarketDataService
AccountService
AssetSelector
paper/live mode selection
```

Acceptance:

```txt
Can fetch account snapshot
Can fetch latest price
Can fetch bars
Can fetch positions
Can build top-20 asset list
```

---

### Phase 4 — Calculators and Compact Payloads

Build:

```txt
IndicatorCalculator
RiskCalculator
LiquidityCalculator
PositionSizer
PnLCalculator
CalculatorEngine
CompactSummaryBuilder
```

Acceptance:

```txt
Full metrics are computed
Compact LLM payload is small
No NaN/Infinity reaches LLM
Target/stop hit is detected deterministically
```

---

### Phase 5 — AskLLM

Build:

```txt
BaseLLMProvider
OpenAIProvider
MockLLMProvider
AskLLM
PromptBuilder
TokenBudgeter
LLMResponseParser
EntrySignal schema
ExitSignal schema
```

Acceptance:

```txt
AskLLM can return EntrySignal from compact payload
AskLLM can return ExitSignal from compact payload
Provider can be swapped without changing loops
Malformed JSON is safely rejected
Oversized payload is rejected before API call
```

---

### Phase 6 — Validator

Build:

```txt
SignalValidator
SchemaValidator
AccountValidator
RiskValidator
DuplicateTradeValidator
entry validation
exit validation
```

Acceptance:

```txt
Oversized qty rejected
Unsafe spread rejected
Insufficient funds rejected
Duplicate symbol rejected
Forced exit works when target/stop hit
```

---

### Phase 7 — Executor and Storage

Build:

```txt
OrderMapper
OrderSubmitter
TradeExecutor
CsvStore with portalocker
OpenOrderStore
PastOrderStore
SignalLogStore
RejectedSignalStore
```

Acceptance:

```txt
Approved paper entry submits Alpaca paper order
open_orders.csv is updated safely
Exit order creates past_orders.csv row
Atomic rewrite works
```

---

### Phase 8 — Full Flow Integration

Build:

```txt
startup reconciliation
hourly asset refresh
2-min entry scanner
2-min open order monitor
10-min reconciliation
heartbeat logs
```

Acceptance:

```txt
Service runs continuously
Entry and exit loops do not block each other
Shared CSV reads/writes are safe
LLM calls are compact and schema-bound
Paper trading works end-to-end
```

---

### Phase 9 — Tests and Hardening

Build:

```txt
pytest suite
mock Alpaca
mock LLM
fault injection
rate-limit retry test
CSV lock test
thread failure test
```

Acceptance:

```txt
pytest passes
No test places live orders
No secrets are logged
```

---

## 23. Final Build Instruction for Coding Agent

Build in this exact order:

```txt
1. Create project structure.
2. Implement config and env validation.
3. Implement AppState and thread-safe BaseLoop.
4. Implement CSV storage with file locks.
5. Implement mocked datasource and mocked LLM first.
6. Implement calculators and compact summaries.
7. Implement AskLLM abstraction and schemas.
8. Implement validator.
9. Implement executor.
10. Implement entry loop.
11. Implement open-order monitor loop.
12. Implement asset refresh and reconciliation loops.
13. Replace mocks with Alpaca/OpenAI providers.
14. Run in PAPER mode only.
15. Add tests and hardening.
```

No trade can be submitted unless:

```txt
LLM signal is valid JSON
Pydantic schema passes
Validator approves
Account status is safe
Asset is tradable
Risk limits are satisfied
No duplicate order exists
Executor maps to a valid Alpaca order payload
TRADING_MODE is explicitly PAPER or REAL
```

When uncertain:

```txt
Entry flow -> SKIP
Exit flow -> HOLD unless target/stop hit
Validator -> REJECT
Executor -> DO NOTHING
```

---

## 24. Notes for Future Improvements

After v1 is stable:

```txt
1. Replace CSV with SQLite/PostgreSQL.
2. Use Alpaca websocket stream for faster prices.
3. Add bracket orders.
4. Add backtesting.
5. Add dashboard.
6. Add multi-strategy voting.
7. Add model/provider switch in AskLLM.
8. Add crypto carefully.
9. Add short selling only after explicit risk controls.
10. Add audit report generation.
```
