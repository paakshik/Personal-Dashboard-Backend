from datetime import datetime, timedelta, timezone
import math
from typing import Any


def todoist_expires_at(expires_in: Any) -> datetime | None:
    """Convert Todoist's expires_in duration to an absolute aware UTC datetime.

    Todoist may omit expiration for legacy long-lived access tokens. In that
    case this returns None rather than storing a duration in a timestamp column.
    """
    if expires_in is None or isinstance(expires_in, bool):
        return None
    try:
        seconds = float(expires_in)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    try:
        return datetime.now(timezone.utc) + timedelta(seconds=seconds)
    except (OverflowError, ValueError):
        return None


def normalize_aware_utc(value: Any) -> datetime | None:
    """Accept a datetime for persistence, normalizing naive values to UTC.

    Numeric values are deliberately rejected here; callers must convert the
    provider duration with :func:`todoist_expires_at` first.
    """
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise TypeError("expires_at must be a datetime or None")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
