"""
app/core/exceptions.py

Custom exception hierarchy for the trading service.
Catching broad `Exception` is acceptable at loop boundaries only.
"""


class TradingServiceError(Exception):
    """Base exception for all trading service errors."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class ConfigurationError(TradingServiceError):
    """Raised when environment variables or config files are invalid."""


class MissingEnvVarError(ConfigurationError):
    """Raised when a required environment variable is absent."""


class InvalidEnvVarError(ConfigurationError):
    """Raised when an environment variable has an illegal value."""


class ForbiddenEnvVarError(ConfigurationError):
    """Raised when an env var that must NOT be in .env is found there."""


# ---------------------------------------------------------------------------
# Data / Market
# ---------------------------------------------------------------------------

class MarketDataError(TradingServiceError):
    """Raised when market data cannot be fetched or is stale."""


class StalePriceError(MarketDataError):
    """Raised when the latest price is older than STALE_PRICE_SECONDS."""


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------

class CalculatorError(TradingServiceError):
    """Raised when a calculator produces an unusable result."""


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

class LLMError(TradingServiceError):
    """Base LLM error."""


class LLMPayloadTooLargeError(LLMError):
    """Raised when a payload exceeds the configured character budget."""


class LLMResponseParseError(LLMError):
    """Raised when LLM output is not valid JSON or fails schema validation."""


class LLMProviderError(LLMError):
    """Raised on transient provider-side errors (rate limit, server error)."""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class ValidationError(TradingServiceError):
    """Base validation error."""


class SchemaValidationError(ValidationError):
    """Raised when Pydantic schema validation fails."""


class AccountValidationError(ValidationError):
    """Raised when account state makes a trade unsafe."""


class RiskValidationError(ValidationError):
    """Raised when a signal violates a risk limit."""


class DuplicateTradeError(ValidationError):
    """Raised when a duplicate open order is detected."""


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

class ExecutionError(TradingServiceError):
    """Base execution error."""


class OrderSubmissionError(ExecutionError):
    """Raised when Alpaca rejects an order submission."""


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

class StorageError(TradingServiceError):
    """Raised when CSV read/write fails."""
