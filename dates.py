"""
dates.py – CivicAI / URBANFIX Centralized Date & Time Utilities

Standards:
- Storage: UTC timestamps in database (ISO-8601 / SQLite standard YYYY-MM-DD HH:MM:SS).
- Display Timezone: Asia/Kolkata (Indian Standard Time, IST = UTC+05:30).
- Date Display Format: DD Mon YYYY, e.g. "07 Nov 2026".
- Time Display Format: 12-hour format with AM/PM, e.g. "10:10 AM".
- Datetime Display Format: "07 Nov 2026, 10:10 AM".
- Resilience: Gracefully handles None, empty strings, missing values, and invalid formats.
"""

from datetime import datetime, timezone, timedelta, date
from typing import Any
import logging

logger = logging.getLogger(__name__)

# ── Timezone Definition (Asia/Kolkata / IST = UTC+05:30) ──────────────────────
try:
    from zoneinfo import ZoneInfo
    try:
        IST = ZoneInfo("Asia/Kolkata")
    except Exception:
        IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
except ImportError:
    IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


def now_utc() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def now_ist() -> datetime:
    """Return current timezone-aware IST datetime."""
    return datetime.now(IST)


def parse_to_utc(val: Any) -> datetime | None:
    """
    Safely parse any date/time representation into a timezone-aware UTC datetime.

    Supports:
      - None / empty string -> returns None
      - datetime objects (naive assumed UTC; aware converted to UTC)
      - date objects (converted to midnight UTC)
      - numeric timestamps (seconds since epoch)
      - ISO-8601 strings (with or without 'T', 'Z', or timezone offset)
      - SQLite standard format 'YYYY-MM-DD HH:MM:SS'
      - Date-only strings 'YYYY-MM-DD'
    """
    if val is None:
        return None

    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)

    if isinstance(val, date):
        return datetime(val.year, val.month, val.day, tzinfo=timezone.utc)

    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc)
        except Exception:
            return None

    s = str(val).strip()
    if not s or s.lower() in ("none", "null", "-", "undefined", "n/a"):
        return None

    # Handle trailing 'Z'
    clean_s = s
    if clean_s.endswith("Z") or clean_s.endswith("z"):
        clean_s = clean_s[:-1] + "+00:00"

    # 1. Try Python ISO parser
    try:
        dt = datetime.fromisoformat(clean_s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    # 2. Try common format patterns
    patterns = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
    ]
    for pattern in patterns:
        try:
            dt = datetime.strptime(s, pattern)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    logger.debug("Failed to parse date/time value: %r", val)
    return None


def to_ist(val: Any) -> datetime | None:
    """Parse input and convert to timezone-aware IST datetime."""
    dt_utc = parse_to_utc(val)
    if dt_utc is None:
        return None
    return dt_utc.astimezone(IST)


def format_date(val: Any, default: str = "-") -> str:
    """
    Format a date/time value to IST date string: 'DD Mon YYYY' (e.g. '07 Nov 2026').

    Returns default if val is missing or invalid.
    """
    dt_ist = to_ist(val)
    if dt_ist is None:
        return default
    return dt_ist.strftime("%d %b %Y")


def format_time(val: Any, default: str = "-") -> str:
    """
    Format a date/time value to IST time string: 12-hour with AM/PM (e.g. '10:10 AM').

    Returns default if val is missing or invalid.
    """
    dt_ist = to_ist(val)
    if dt_ist is None:
        return default
    return dt_ist.strftime("%I:%M %p")


def format_datetime(val: Any, default: str = "-") -> str:
    """
    Format a date/time value to IST datetime: '07 Nov 2026, 10:10 AM'.

    Returns default if val is missing or invalid.
    """
    dt_ist = to_ist(val)
    if dt_ist is None:
        return default
    return dt_ist.strftime("%d %b %Y, %I:%M %p")


def ist_date_range_to_utc(start_date: str | None, end_date: str | None) -> tuple[str | None, str | None]:
    """
    Convert user-selected calendar dates (YYYY-MM-DD in IST) into UTC timestamp
    strings covering the full day from 00:00:00 IST to 23:59:59 IST.

    Example:
      start_date '2026-11-07' -> '2026-11-06 18:30:00' (UTC)
      end_date   '2026-11-07' -> '2026-11-07 18:29:59' (UTC)
    """
    start_utc_str: str | None = None
    end_utc_str: str | None = None

    if start_date and str(start_date).strip():
        s = str(start_date).strip()
        try:
            d = datetime.strptime(s, "%Y-%m-%d").date()
            dt_ist_start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=IST)
            start_utc_str = dt_ist_start.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    if end_date and str(end_date).strip():
        s = str(end_date).strip()
        try:
            d = datetime.strptime(s, "%Y-%m-%d").date()
            dt_ist_end = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=IST)
            end_utc_str = dt_ist_end.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    return start_utc_str, end_utc_str
