"""
app/utils/logger.py

Centralised loguru-based logger for the trading service.
Import `logger` from here everywhere. Never use print().

Rules:
  - API keys are never logged.
  - Raw LLM prompts are debug-only, behind a guard.
  - All threads share the same logger instance.
"""

import sys
from pathlib import Path
from loguru import logger

from config.settings import LOG_DIR, LOG_FILE, LOG_LEVEL, LOG_ROTATION, LOG_RETENTION


def setup_logger() -> None:
    """Configure loguru handlers. Call once at startup before threads start."""

    # On Windows the default console encoding is cp1252 which can't handle
    # many Unicode chars. Reconfigure stdout to UTF-8 where supported (Python 3.7+).
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except AttributeError:
        pass  # Not available in all environments; safe to ignore.

    # Remove the default stderr handler so we can add a formatted one.
    logger.remove()

    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "{message}"
    )

    # --- Console handler ---
    logger.add(
        sys.stdout,
        format=log_format,
        level=LOG_LEVEL,
        colorize=True,
        enqueue=True,   # thread-safe async queue
    )

    # --- File handler ---
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    logger.add(
        LOG_FILE,
        format=log_format,
        level=LOG_LEVEL,
        rotation=LOG_ROTATION,
        retention=LOG_RETENTION,
        enqueue=True,
        encoding="utf-8",
    )

    logger.info("Logger initialised. level={} file={}", LOG_LEVEL, LOG_FILE)


# Re-export so callers can do: from app.utils.logger import logger
__all__ = ["logger", "setup_logger"]
