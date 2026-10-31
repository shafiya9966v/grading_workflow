"""Small time helpers so every timestamp is created and parsed the same way.

Rule: all stored timestamps are UTC, formatted like 2026-03-14T18:29:00Z.
Due dates are authored in India time (IST) and converted to UTC here.
"""
from datetime import date, datetime, timezone

import config


def ist_to_utc(d: date, hour: int, minute: int = 0) -> datetime:
    """A wall-clock time on date d in India (IST) -> timezone-aware UTC datetime."""
    local = datetime(d.year, d.month, d.day, hour, minute, tzinfo=config.IST)
    return local.astimezone(timezone.utc)


def to_ts(dt: datetime) -> str:
    """Format an aware datetime as the stored UTC string."""
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return dt.astimezone(timezone.utc).strftime(config.TIMESTAMP_FORMAT)


def parse_ts(text: str) -> datetime:
    """Parse a stored UTC string back into an aware datetime."""
    return datetime.strptime(text, config.TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)


if __name__ == "__main__":
    due = ist_to_utc(date(2026, 3, 14), config.DUE_LOCAL_HOUR, config.DUE_LOCAL_MINUTE)
    print("23:59 IST on 2026-03-14 ->", to_ts(due))   # expect 2026-03-14T18:29:00Z
    assert to_ts(due) == "2026-03-14T18:29:00Z"
    assert parse_ts(to_ts(due)) == due
    print("timeutil OK")