"""
config/strategy_params.py

Strategy-specific parameters that control how calculations
and filters work. Never read from .env.
"""

# ---------------------------------------------------------------------------
# Indicator Lookback Periods
# ---------------------------------------------------------------------------

SMA_SHORT_PERIOD: int = 20
SMA_LONG_PERIOD: int = 50
EMA_FAST_PERIOD: int = 12
EMA_SLOW_PERIOD: int = 26
MACD_SIGNAL_PERIOD: int = 9
RSI_PERIOD: int = 14
ATR_PERIOD: int = 14
ROC_PERIOD: int = 10

# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------

REALIZED_VOL_SHORT_PERIOD: int = 20  # days for short realized volatility
REALIZED_VOL_LONG_PERIOD: int = 50   # days for long realized volatility
MAX_DRAWDOWN_LOOKBACK: int = 60       # days for max-drawdown calculation
SHARPE_LOOKBACK: int = 60             # days for Sharpe / Sortino
HIGH_VOLATILITY_THRESHOLD: float = 0.40  # annualised vol above which to SKIP

# ---------------------------------------------------------------------------
# Entry Criteria
# ---------------------------------------------------------------------------

MIN_MOMENTUM_SCORE: float = 0.3       # minimum calculator momentum score to consider
MIN_CONFIDENCE_TO_EXECUTE: float = 0.55  # minimum LLM confidence to let validator approve

# ---------------------------------------------------------------------------
# Bars / Timeframes Fetched per Asset
# ---------------------------------------------------------------------------

BARS_TIMEFRAME: str = "1Min"          # Alpaca TimeFrame string
BARS_LOOKBACK: int = 390              # number of bars to fetch (~1 trading day of 1-min bars)

# ---------------------------------------------------------------------------
# Risk Multipliers (ATR Based)
# ---------------------------------------------------------------------------

STOP_LOSS_ATR_MULT: float = 2.0
TAKE_PROFIT_ATR_MULT: float = 4.0

# ---------------------------------------------------------------------------
# Exit / PnL Risk Context
# ---------------------------------------------------------------------------

# Used by PnLRiskCalculator to contextualize open-position P&L for the exit LLM.
EXIT_ATR_PERIOD: int = 14
EXIT_TRAILING_ATR_MULT: float = 3.0
EXIT_PROFIT_PROTECTION_TRIGGER_PCT: float = 0.01
EXIT_BREAKEVEN_PROFIT_TRIGGER_PCT: float = 0.005
EXIT_MAX_PROFIT_GIVEBACK_RATIO: float = 0.45
EXIT_LOSS_CONTROL_PCT: float = -0.01

# ---------------------------------------------------------------------------
# Asset Selector
# ---------------------------------------------------------------------------

ASSET_SELECTOR_TOP_N: int = 20        # keep top-N from the scored universe
