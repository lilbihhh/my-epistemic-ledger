"""Clocks shared by ledger tests so timestamps stay repeatable."""

from datetime import datetime, timedelta, timezone

START = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


def ticking_clock(start: datetime = START):
    """Return a clock that moves forward one second on every call."""
    ticks = {"count": 0}

    def clock() -> datetime:
        stamp = start + timedelta(seconds=ticks["count"])
        ticks["count"] += 1
        return stamp

    return clock
