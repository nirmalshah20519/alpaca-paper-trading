"""
app/utils/time_utils.py

Datetime helpers. All timestamps in the service are UTC ISO-8601 strings.
"""

from datetime import datetime, timezone


def utc_now() -> str:
    """Return current UTC time as an ISO-8601 string with microseconds."""
    return datetime.now(tz=timezone.utc).isoformat()


def utc_now_dt() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(tz=timezone.utc)
