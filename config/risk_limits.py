"""
config/risk_limits.py

Hard risk constants used by validators and calculators.
These must never be read from .env.
"""

# Maximum fraction of equity to risk on a single trade (1 %)
MAX_RISK_PER_TRADE_PCT: float = 0.01

# Maximum fraction of equity that a single position can represent (5 %)
MAX_POSITION_PCT_OF_EQUITY: float = 0.05

# Stop trading for the day if day P&L loss exceeds this fraction of equity (3 %)
MAX_DAILY_LOSS_PCT: float = 0.03

# Pause new entries if overall portfolio drawdown exceeds this fraction (10 %)
MAX_PORTFOLIO_DRAWDOWN_PCT: float = 0.10

# Minimum acceptable risk-to-reward ratio
MIN_RISK_REWARD_RATIO: float = 1.5

# Maximum allowed bid-ask spread as fraction of price (0.2 %)
MAX_SPREAD_PCT: float = 0.002

# Maximum allowed crypto bid-ask spread as fraction of price (0.5 %)
MAX_CRYPTO_SPREAD_PCT: float = 0.005

# Minimum 20-day average daily volume (shares) for a symbol to be tradable
MIN_AVG_DAILY_VOLUME: int = 1_000_000

# Minimum average daily dollar volume for crypto symbols.
# Crypto bar volume is in base units, not shares, so use notional volume.
MIN_CRYPTO_DAILY_DOLLAR_VOLUME: float = 1_000_000.0

# Dynamic risk/liquidity controls (account-aware).
# Trade budget is derived from account state and then clamped to this range.
DYNAMIC_TRADE_BUDGET_PCT_OF_BUYING_POWER: float = 0.02
DYNAMIC_TRADE_BUDGET_MIN_DOLLARS: float = 50.0
DYNAMIC_TRADE_BUDGET_MAX_DOLLARS: float = 2_000.0

# Dynamic liquidity floors scale with trade budget and are clamped.
DYNAMIC_CRYPTO_LIQUIDITY_MULTIPLIER: float = 500.0
DYNAMIC_CRYPTO_LIQUIDITY_MIN_DOLLARS: float = 50_000.0
DYNAMIC_CRYPTO_LIQUIDITY_MAX_DOLLARS: float = 5_000_000.0

DYNAMIC_STOCK_LIQUIDITY_MULTIPLIER: float = 500.0
DYNAMIC_STOCK_LIQUIDITY_MIN_SHARES: int = 200_000
DYNAMIC_STOCK_LIQUIDITY_MAX_SHARES: int = 5_000_000

# Maximum number of simultaneously open positions
MAX_OPEN_POSITIONS: int = 5

# Maximum trades submitted in a single calendar day
MAX_TRADES_PER_DAY: int = 20

# Allow opening short positions (sell-to-open)?
ALLOW_SHORT_SELLING: bool = False

# Allow adding to an existing open position?
ALLOW_POSITION_SCALING: bool = False

# Number of seconds before a price quote is considered stale
STALE_PRICE_SECONDS: int = 180
