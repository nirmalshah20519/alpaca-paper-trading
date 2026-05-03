"""
config/settings.py

Non-secret, version-controlled application settings.
All model names, symbols, intervals, thresholds go here — never in .env.
"""

# ---------------------------------------------------------------------------
# Asset Universe
# ---------------------------------------------------------------------------

DEFAULT_STOCK_UNIVERSE: list[str] = [
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL", "AMD", "NFLX", "AVGO",
    "SPY",  "QQQ",  "IWM",  "DIA",  "PLTR", "COIN", "MARA", "SMCI", "INTC", "BABA",
    "JPM",  "BAC",  "XOM",  "CVX",  "UNH",  "LLY",  "WMT",  "COST", "DIS",  "PYPL",
]

DEFAULT_CRYPTO_UNIVERSE: list[str] = [
    "BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "SHIB/USD",
    "AVAX/USD", "LINK/USD", "UNI/USD", "LTC/USD", "BCH/USD"
]

# Maximum symbols to keep in the active trading list
MAX_ACTIVE_SYMBOLS: int = 20
ASSET_SELECTOR_TOP_N: int = 20

# Risk Management
MAX_DOLLAR_PER_TRADE: float = 200.0
STOCK_CLOSE_BUFFER_MINUTES: int = 15

# ---------------------------------------------------------------------------
# Loop Intervals (seconds)
# ---------------------------------------------------------------------------

ASSET_REFRESH_INTERVAL_SECONDS: int = 3_600   # 1 hour
ENTRY_INTERVAL_SECONDS: int = 120              # 2 minutes
MONITOR_INTERVAL_SECONDS: int = 120           # 2 minutes
RECONCILIATION_INTERVAL_SECONDS: int = 600      # 10 minutes
HEARTBEAT_INTERVAL_SECONDS: int = 60            # 1 minute

# ---------------------------------------------------------------------------
# CSV Storage Paths
# ---------------------------------------------------------------------------

DATA_DIR: str = "data"
OPEN_ORDERS_CSV: str = "data/open_orders.csv"
PAST_ORDERS_CSV: str = "data/past_orders.csv"
SIGNAL_LOGS_CSV: str = "data/signal_logs.csv"
REJECTED_SIGNALS_CSV: str = "data/rejected_signals.csv"
SERVICE_STATE_JSON: str = "data/service_state.json"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR: str = "logs"
LOG_FILE: str = "logs/trading_service.log"
LOG_ROTATION: str = "10 MB"
LOG_RETENTION: str = "7 days"
LOG_LEVEL: str = "DEBUG"

# ---------------------------------------------------------------------------
# Opportunity Score Weights (used by AssetSelector)
# ---------------------------------------------------------------------------

SCORE_WEIGHT_VOLUME: float = 0.30
SCORE_WEIGHT_MOMENTUM: float = 0.25
SCORE_WEIGHT_VOLATILITY_EXPANSION: float = 0.20
SCORE_WEIGHT_DOLLAR_VOLUME: float = 0.15
SCORE_WEIGHT_TREND_STRENGTH: float = 0.10
