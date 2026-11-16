"""Time utilities — pure functions so decay math is testable without mocks."""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta

# ISO-8601 date or datetime, e.g. 2026-11-16 or 2026-11-16T14:30:00
_TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)?$")


def now() -> datetime:
    """Current UTC time, timezone-aware."""
    return datetime.now(timezone.utc)


def now_iso() -> str:
    """Current UTC time as an ISO-8601 second-resolution string."""
    return now().strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(value: str) -> datetime:
    """Parse an ISO-8601 date or datetime (naive treated as UTC).

    Accepts an optional trailing 'Z'. Raises ValueError on malformed input.
    """
    if not value:
        raise ValueError("empty timestamp")
    if not _TS_RE.match(value):
        raise ValueError("malformed timestamp: %r" % value)
    text = value[:-1] if value.endswith("Z") else value
    if "T" in text:
        if "." in text:
            dt = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%f")
        else:
            dt = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")
    else:
        dt = datetime.strptime(text, "%Y-%m-%d")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def days_between(a: datetime, b: datetime) -> float:
    """Signed fractional days from a to b (positive = b after a)."""
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    return (b - a).total_seconds() / 86400.0


def fmt_date(value: str) -> str:
    """Normalize an ISO timestamp to 'YYYY-MM-DD' for display."""
    return parse_ts(value).strftime("%Y-%m-%d")
