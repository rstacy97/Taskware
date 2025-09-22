from __future__ import annotations

import re
from typing import Optional

# Minimal NL -> cron converter for common phrases
# Supported examples:
# - "every day at 9 am" -> "0 9 * * *"
# - "every monday at 6 pm" -> "0 18 * * 1"
# - "every 15 minutes" -> "*/15 * * * *"
# - "every hour" -> "0 * * * *"
# - "daily at 02:30" -> "30 2 * * *"
# - "weekly on sunday at 07:00" -> "0 7 * * 0"

WEEKDAYS = {
    "sunday": 0,
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
}


def _parse_time(text: str) -> Optional[tuple[int, int]]:
    text = text.strip().lower()
    # HH:MM 24h
    m = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2))
        if 0 <= h < 24 and 0 <= mi < 60:
            return h, mi
        return None
    # 12h am/pm
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", text)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2) or 0)
        ap = m.group(3)
        if not (1 <= h <= 12 and 0 <= mi < 60):
            return None
        if ap == "pm" and h != 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        return h, mi
    return None


def nl_to_cron(text: str) -> Optional[str]:
    """Convert a small subset of natural language scheduling to a cron expression.
    Returns None if it cannot parse.
    """
    s = re.sub(r"\s+", " ", text.strip().lower())

    # every N minutes
    m = re.match(r"^every\s+(\d{1,2})\s+minutes?$", s)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 59:
            return f"*/{n} * * * *"

    # every hour
    if s in ("every hour", "hourly"):
        return "0 * * * *"

    # daily at HH:MM or h am/pm
    m = re.match(r"^(every\s+day\s+at|daily\s+at)\s+(.+)$", s)
    if m:
        tm = _parse_time(m.group(2))
        if tm:
            h, mi = tm
            return f"{mi} {h} * * *"

    # every <weekday> at <time>
    m = re.match(r"^every\s+([a-z]+)\s+at\s+(.+)$", s)
    if m:
        wd = m.group(1)
        tm = _parse_time(m.group(2))
        if wd in WEEKDAYS and tm:
            h, mi = tm
            return f"{mi} {h} * * {WEEKDAYS[wd]}"

    # weekly on <weekday> at <time>
    m = re.match(r"^weekly\s+on\s+([a-z]+)\s+at\s+(.+)$", s)
    if m:
        wd = m.group(1)
        tm = _parse_time(m.group(2))
        if wd in WEEKDAYS and tm:
            h, mi = tm
            return f"{mi} {h} * * {WEEKDAYS[wd]}"

    return None
