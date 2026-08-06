from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def normalize_datetime(value: Any) -> datetime | None:
    """Return a timezone-aware UTC datetime for legacy stored timestamps.

    Naive datetimes are treated as UTC to preserve backward compatibility
    with older stored records that omitted timezone information.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

