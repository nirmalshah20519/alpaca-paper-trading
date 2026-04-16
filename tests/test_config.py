"""Configuration tests."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_parse_watchlist() -> None:
    settings = Settings(
        enable_startup_broker_validation=False,
        watchlist="aapl, msft, spy",
    )
    assert settings.watchlist == ["AAPL", "MSFT", "SPY"]


def test_settings_reject_non_paper_base_url() -> None:
    with pytest.raises(ValidationError):
        Settings(
            enable_startup_broker_validation=False,
            alpaca_api_base_url="https://api.alpaca.markets",
        )
