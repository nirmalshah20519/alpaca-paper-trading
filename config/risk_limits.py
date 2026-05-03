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

# Minimum 20-day average daily volume (shares) for a symbol to be tradable
MIN_AVG_DAILY_VOLUME: int = 1_000_000

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
