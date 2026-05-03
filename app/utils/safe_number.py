"""
app/utils/safe_number.py

Helpers to sanitise numeric values before they reach the LLM,
validators, or CSV storage.

Rules (from plan §12.4):
  - Never send NaN, Infinity, or -Infinity downstream.
  - Return None for unavailable values.
  - Return 0 only when mathematically correct.
"""

import math
from typing import Optional


def safe_float(value: object, default: Optional[float] = None) -> Optional[float]:
    """
    Convert *value* to a clean Python float.

    Returns *default* if the value is NaN, Infinity, -Infinity, or not
    numeric at all.
    """
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return f


def safe_int(value: object, default: Optional[int] = None) -> Optional[int]:
    """
    Convert *value* to a clean Python int.

    Returns *default* on any failure.
    """
    f = safe_float(value)
    if f is None:
        return default
    return int(f)
