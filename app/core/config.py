"""Typed application settings loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import AnyUrl, Field, SecretStr, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration for the paper-trading MVP."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "alpaca-paper-agent"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    trading_mode: Literal["paper"] = "paper"
    enable_startup_broker_validation: bool = True
    enable_stream_worker: bool = True
    enable_paper_execution: bool = False
    reconcile_interval_seconds: int = 60
    alpaca_api_timeout_seconds: float = 10.0
    risk_max_position_notional: float = 2500.0
    risk_max_gross_exposure_pct: float = 1.0
    risk_max_net_exposure_pct: float = 1.0
    risk_max_open_positions: int = 10
    risk_max_strategy_exposure_pct: float = 0.4
    risk_max_symbol_exposure_pct: float = 0.2
    risk_cooldown_after_exit_minutes: int = 30
    risk_side_flip_cooldown_minutes: int = 60
    risk_max_daily_turnover_pct: float = 2.0
    risk_daily_loss_breaker_pct: float = 0.03
    risk_min_stop_distance_pct: float = 0.005
    risk_min_reward_risk_ratio: float = 1.5
    portfolio_total_budget_pct: float = 1.0
    portfolio_symbol_budget_pct: float = 0.2
    portfolio_strategy_budget_pct: float = 0.4
    portfolio_sector_bucket_limit: int = 4
    strategy_max_proposals_per_cycle: int = 10
    execution_stale_order_minutes: int = 30

    database_url: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/alpaca_paper_agent"
    redis_url: str = "redis://redis:6379/0"

    alpaca_api_key: SecretStr | None = None
    alpaca_api_secret: SecretStr | None = None
    alpaca_api_base_url: AnyUrl = "https://paper-api.alpaca.markets"
    alpaca_market_data_url: AnyUrl = "https://data.alpaca.markets"
    watchlist: list[str] = Field(default_factory=lambda: ["AAPL", "MSFT", "SPY", "QQQ"])

    @field_validator("watchlist", mode="before")
    @classmethod
    def parse_watchlist(cls, value: object) -> object:
        """Accept watchlists as comma-separated strings or lists."""
        if isinstance(value, str):
            return [item.strip().upper() for item in value.split(",") if item.strip()]
        return value

    @field_validator("alpaca_api_base_url")
    @classmethod
    def ensure_paper_url(cls, value: AnyUrl) -> AnyUrl:
        """Reject non-paper API endpoints to keep the MVP paper-only."""
        if "paper-api.alpaca.markets" not in str(value):
            raise ValueError("ALPACA_API_BASE_URL must point to the Alpaca paper endpoint.")
        return value

    @computed_field
    @property
    def masked_alpaca_key(self) -> str:
        """Return a masked key value for logs."""
        if self.alpaca_api_key is None:
            return "missing"
        raw = self.alpaca_api_key.get_secret_value()
        return f"{raw[:4]}...{raw[-4:]}" if len(raw) >= 8 else "configured"

    def validate_trading_safety(self) -> None:
        """Enforce non-negotiable paper-mode startup rules."""
        if self.trading_mode != "paper":
            raise ValueError("This service only supports paper trading mode.")
        if self.alpaca_api_key is None or self.alpaca_api_secret is None:
            raise ValueError("Alpaca paper credentials must be configured.")


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()
