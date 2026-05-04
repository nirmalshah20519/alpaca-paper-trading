"""
app/core/config.py

AppConfig — loads, validates, and exposes the four allowed env variables.

Rules from the plan (§1 Hard Environment Constraint):
  - Only ALPACA_API_KEY, ALPACA_API_SECRET, OPENAI_API_KEY, TRADING_MODE
    may appear in .env.
  - TRADING_MODE must be "PAPER" or "REAL".
  - No model names, thresholds, symbols, or risk limits may come from .env.

Call `AppConfig.load()` once at startup. Use `AppConfig.instance()` to
retrieve the singleton afterwards.
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import dotenv_values

from app.core.exceptions import (
    MissingEnvVarError,
    InvalidEnvVarError,
    ForbiddenEnvVarError,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_ENV_KEYS: frozenset[str] = frozenset(
    {"ALPACA_API_KEY", "ALPACA_API_SECRET", "OPENAI_API_KEY", "TRADING_MODE", "USEGPT"}
)

ALLOWED_TRADING_MODES: frozenset[str] = frozenset({"PAPER", "REAL"})


# ---------------------------------------------------------------------------
# AppConfig
# ---------------------------------------------------------------------------

class AppConfig:
    """
    Immutable configuration loaded from .env on startup.

    Attributes
    ----------
    alpaca_api_key : str
    alpaca_api_secret : str
    openai_api_key : str
    trading_mode : str  — either "PAPER" or "REAL"
    is_paper : bool     — True when trading_mode == "PAPER"
    use_gpt : bool      — True to use OpenAI, False for local LFM
    """

    _instance: AppConfig | None = None

    def __init__(
        self,
        alpaca_api_key: str,
        alpaca_api_secret: str,
        openai_api_key: str,
        trading_mode: str,
    ) -> None:
        self.alpaca_api_key = alpaca_api_key
        self.alpaca_api_secret = alpaca_api_secret
        self.openai_api_key = openai_api_key
        self.trading_mode = trading_mode
        self.is_paper: bool = trading_mode == "PAPER"
        self.use_gpt: bool = True

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, env_path: str | Path = ".env") -> "AppConfig":
        """
        Load and validate the .env file.

        Parameters
        ----------
        env_path : path to the .env file (default: ".env" in cwd).

        Returns
        -------
        AppConfig singleton.

        Raises
        ------
        MissingEnvVarError      — a required key is absent.
        InvalidEnvVarError      — TRADING_MODE has an illegal value.
        ForbiddenEnvVarError    — .env contains keys that must not be there.
        """
        env_path = Path(env_path)

        # Read the .env file without polluting os.environ so that later
        # lookups via os.getenv still reflect only what is really set.
        file_values: dict[str, str | None] = {}
        if env_path.exists():
            file_values = dotenv_values(env_path)

        # Merge with process environment (process env wins over file)
        merged: dict[str, str] = {}
        for key in ALLOWED_ENV_KEYS:
            val = os.environ.get(key) or file_values.get(key) or ""
            merged[key] = val.strip()

        # Detect forbidden extra keys in the .env file only (not in process env)
        forbidden = set(file_values.keys()) - ALLOWED_ENV_KEYS
        if forbidden:
            raise ForbiddenEnvVarError(
                f"The following keys are not allowed in .env: {sorted(forbidden)}. "
                "All non-secret config must live in config/*.py"
            )

        # Validate required keys are present and non-empty
        for key in ALLOWED_ENV_KEYS:
            if not merged[key]:
                raise MissingEnvVarError(
                    f"Required environment variable '{key}' is missing or empty. "
                    f"Add it to .env or set it in the process environment."
                )

        # Validate TRADING_MODE
        mode = merged["TRADING_MODE"].upper()
        if mode not in ALLOWED_TRADING_MODES:
            raise InvalidEnvVarError(
                f"TRADING_MODE='{mode}' is invalid. "
                f"Allowed values: {sorted(ALLOWED_TRADING_MODES)}"
            )

        instance = cls(
            alpaca_api_key=merged["ALPACA_API_KEY"],
            alpaca_api_secret=merged["ALPACA_API_SECRET"],
            openai_api_key=merged["OPENAI_API_KEY"],
            trading_mode=mode,
        )
        instance.use_gpt = merged["USEGPT"].upper() != "FALSE"
        cls._instance = instance
        return instance

    # ------------------------------------------------------------------
    # Singleton accessor
    # ------------------------------------------------------------------

    @classmethod
    def instance(cls) -> "AppConfig":
        """Return the loaded singleton. Call `load()` first."""
        if cls._instance is None:
            raise RuntimeError(
                "AppConfig has not been loaded yet. Call AppConfig.load() first."
            )
        return cls._instance

    # ------------------------------------------------------------------
    # Repr (safe — never exposes secrets)
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"AppConfig("
            f"trading_mode={self.trading_mode!r}, "
            f"alpaca_api_key='***', "
            f"openai_api_key='***'"
            f")"
        )
