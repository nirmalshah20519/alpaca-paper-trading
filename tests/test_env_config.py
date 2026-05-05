"""
tests/test_env_config.py

Tests for AppConfig environment variable loading and validation.

Rules under test:
  - Only approved env vars are allowed.
  - TRADING_MODE must be PAPER or REAL.
  - Missing required vars raise MissingEnvVarError.
  - Forbidden extra vars in .env raise ForbiddenEnvVarError.
  - TRADING_MODE with illegal value raises InvalidEnvVarError.
  - Keys are never stored in plain-text repr.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from app.core.config import AppConfig
from app.core.exceptions import (
    MissingEnvVarError,
    InvalidEnvVarError,
    ForbiddenEnvVarError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_env(tmp_path: Path, content: str) -> Path:
    """Write a .env file and return its path."""
    env_file = tmp_path / ".env"
    env_file.write_text(content, encoding="utf-8")
    return env_file


def _reset_singleton() -> None:
    """Clear the AppConfig singleton between tests."""
    AppConfig._instance = None


# ---------------------------------------------------------------------------
# Fixture — clean env vars before each test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Remove allowed env vars from the real process environment."""
    for key in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "OPENAI_API_KEY", "TRADING_MODE", "USEGPT"):
        monkeypatch.delenv(key, raising=False)
    _reset_singleton()
    yield
    _reset_singleton()


# ---------------------------------------------------------------------------
# Valid loading
# ---------------------------------------------------------------------------

class TestValidEnvLoading:

    def test_paper_mode_loads_successfully(self, tmp_path):
        env = _write_env(tmp_path, (
            "ALPACA_API_KEY=fake_key\n"
            "ALPACA_API_SECRET=fake_secret\n"
            "OPENAI_API_KEY=fake_oai\n"
            "TRADING_MODE=PAPER\n"
        ))
        cfg = AppConfig.load(env)
        assert cfg.trading_mode == "PAPER"
        assert cfg.is_paper is True

    def test_real_mode_loads_successfully(self, tmp_path):
        env = _write_env(tmp_path, (
            "ALPACA_API_KEY=fake_key\n"
            "ALPACA_API_SECRET=fake_secret\n"
            "OPENAI_API_KEY=fake_oai\n"
            "TRADING_MODE=REAL\n"
        ))
        cfg = AppConfig.load(env)
        assert cfg.trading_mode == "REAL"
        assert cfg.is_paper is False

    def test_trading_mode_case_insensitive(self, tmp_path):
        """TRADING_MODE=paper (lowercase) should still work — normalised to uppercase."""
        env = _write_env(tmp_path, (
            "ALPACA_API_KEY=key\n"
            "ALPACA_API_SECRET=secret\n"
            "OPENAI_API_KEY=oai\n"
            "TRADING_MODE=paper\n"
        ))
        cfg = AppConfig.load(env)
        assert cfg.trading_mode == "PAPER"

    def test_singleton_returns_same_instance(self, tmp_path):
        env = _write_env(tmp_path, (
            "ALPACA_API_KEY=k\n"
            "ALPACA_API_SECRET=s\n"
            "OPENAI_API_KEY=o\n"
            "TRADING_MODE=PAPER\n"
        ))
        cfg1 = AppConfig.load(env)
        cfg2 = AppConfig.instance()
        assert cfg1 is cfg2

    def test_repr_does_not_expose_secrets(self, tmp_path):
        env = _write_env(tmp_path, (
            "ALPACA_API_KEY=super_secret_key\n"
            "ALPACA_API_SECRET=super_secret_val\n"
            "OPENAI_API_KEY=openai_key\n"
            "TRADING_MODE=PAPER\n"
        ))
        cfg = AppConfig.load(env)
        r = repr(cfg)
        assert "super_secret_key" not in r
        assert "super_secret_val" not in r
        assert "openai_key" not in r
        assert "PAPER" in r

    def test_usegpt_false_does_not_require_openai_key(self, tmp_path):
        env = _write_env(tmp_path, (
            "ALPACA_API_KEY=fake_key\n"
            "ALPACA_API_SECRET=fake_secret\n"
            "TRADING_MODE=PAPER\n"
            "USEGPT=FALSE\n"
        ))
        cfg = AppConfig.load(env)
        assert cfg.use_gpt is False
        assert cfg.openai_api_key == ""

    def test_usegpt_defaults_to_true(self, tmp_path):
        env = _write_env(tmp_path, (
            "ALPACA_API_KEY=fake_key\n"
            "ALPACA_API_SECRET=fake_secret\n"
            "OPENAI_API_KEY=fake_oai\n"
            "TRADING_MODE=PAPER\n"
        ))
        cfg = AppConfig.load(env)
        assert cfg.use_gpt is True


# ---------------------------------------------------------------------------
# Invalid env rejection
# ---------------------------------------------------------------------------

class TestInvalidEnvRejection:

    def test_missing_api_key_raises(self, tmp_path):
        env = _write_env(tmp_path, (
            # ALPACA_API_KEY intentionally omitted
            "ALPACA_API_SECRET=s\n"
            "OPENAI_API_KEY=o\n"
            "TRADING_MODE=PAPER\n"
        ))
        with pytest.raises(MissingEnvVarError, match="ALPACA_API_KEY"):
            AppConfig.load(env)

    def test_missing_api_secret_raises(self, tmp_path):
        env = _write_env(tmp_path, (
            "ALPACA_API_KEY=k\n"
            "OPENAI_API_KEY=o\n"
            "TRADING_MODE=PAPER\n"
        ))
        with pytest.raises(MissingEnvVarError, match="ALPACA_API_SECRET"):
            AppConfig.load(env)

    def test_missing_openai_key_raises(self, tmp_path):
        env = _write_env(tmp_path, (
            "ALPACA_API_KEY=k\n"
            "ALPACA_API_SECRET=s\n"
            "TRADING_MODE=PAPER\n"
        ))
        with pytest.raises(MissingEnvVarError, match="OPENAI_API_KEY"):
            AppConfig.load(env)

    def test_missing_trading_mode_raises(self, tmp_path):
        env = _write_env(tmp_path, (
            "ALPACA_API_KEY=k\n"
            "ALPACA_API_SECRET=s\n"
            "OPENAI_API_KEY=o\n"
        ))
        with pytest.raises(MissingEnvVarError, match="TRADING_MODE"):
            AppConfig.load(env)

    def test_invalid_trading_mode_raises(self, tmp_path):
        env = _write_env(tmp_path, (
            "ALPACA_API_KEY=k\n"
            "ALPACA_API_SECRET=s\n"
            "OPENAI_API_KEY=o\n"
            "TRADING_MODE=LIVE\n"   # not allowed
        ))
        with pytest.raises(InvalidEnvVarError, match="LIVE"):
            AppConfig.load(env)

    def test_forbidden_extra_key_raises(self, tmp_path):
        env = _write_env(tmp_path, (
            "ALPACA_API_KEY=k\n"
            "ALPACA_API_SECRET=s\n"
            "OPENAI_API_KEY=o\n"
            "TRADING_MODE=PAPER\n"
            "LLM_MODEL=gpt-4o-mini\n"   # forbidden — must be in config/*.py
        ))
        with pytest.raises(ForbiddenEnvVarError, match="LLM_MODEL"):
            AppConfig.load(env)

    def test_multiple_forbidden_keys_raises(self, tmp_path):
        env = _write_env(tmp_path, (
            "ALPACA_API_KEY=k\n"
            "ALPACA_API_SECRET=s\n"
            "OPENAI_API_KEY=o\n"
            "TRADING_MODE=PAPER\n"
            "MAX_OPEN_POSITIONS=3\n"
            "SYMBOLS=AAPL,TSLA\n"
        ))
        with pytest.raises(ForbiddenEnvVarError):
            AppConfig.load(env)

    def test_instance_before_load_raises(self):
        _reset_singleton()
        with pytest.raises(RuntimeError, match="AppConfig has not been loaded"):
            AppConfig.instance()

    def test_empty_env_file_raises(self, tmp_path):
        env = _write_env(tmp_path, "")
        with pytest.raises(MissingEnvVarError):
            AppConfig.load(env)

    def test_invalid_usegpt_raises(self, tmp_path):
        env = _write_env(tmp_path, (
            "ALPACA_API_KEY=k\n"
            "ALPACA_API_SECRET=s\n"
            "OPENAI_API_KEY=o\n"
            "TRADING_MODE=PAPER\n"
            "USEGPT=MAYBE\n"
        ))
        with pytest.raises(InvalidEnvVarError, match="USEGPT"):
            AppConfig.load(env)
