"""Read only retry timing headers, never persist a Provider error body."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from math import isfinite


class RetryWindowTooLong(ValueError):
    pass


def provider_retry_at(error: Exception, now: datetime) -> datetime | None:
    response = getattr(error, 'response', None)
    if response is None:
        return None
    raw = response.headers.get('retry-after')
    milliseconds = response.headers.get('retry-after-ms')
    if raw is None and milliseconds is None:
        return None
    try:
        if raw is not None:
            try:
                seconds = float(raw)
            except ValueError:
                when = parsedate_to_datetime(raw)
                if when.tzinfo is None:
                    return None
                seconds = (when.astimezone(UTC) - now).total_seconds()
        else:
            seconds = float(milliseconds) / 1000
    except (ValueError, TypeError, OverflowError):
        return None
    if not isfinite(seconds) or seconds <= 0:
        return None
    if seconds > 86400:
        # Do not shorten the Provider's cooldown into an automatic early retry.
        raise RetryWindowTooLong('memory_learning_retry_window_unavailable')
    return now + timedelta(seconds=seconds)
