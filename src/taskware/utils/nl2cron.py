from __future__ import annotations

import re
from typing import Optional, Tuple, List, Dict
import difflib

# Minimal NL -> cron converter for common phrases
# Supported examples:
# - "every day at 9 am" -> "0 9 * * *"
# - "every monday at 6 pm" -> "0 18 * * 1"
# - "every 15 minutes" -> "*/15 * * * *"
# - "every hour" -> "0 * * * *"
# - "daily at 02:30" -> "30 2 * * *"
# - "weekly on sunday at 07:00" -> "0 7 * * 0"

WEEKDAYS = {
    "sunday": 0, "sun": 0, "sundays": 0,
    "monday": 1, "mon": 1, "mondays": 1,
    "tuesday": 2, "tue": 2, "tues": 2, "tuesdays": 2,
    "wednesday": 3, "wed": 3, "wednesdays": 3,
    "thursday": 4, "thu": 4, "thur": 4, "thurs": 4, "thursdays": 4,
    "friday": 5, "fri": 5, "fridays": 5,
    "saturday": 6, "sat": 6, "saturdays": 6,
}

# Example phrases used for close-match suggestions
EXAMPLE_PHRASES = [
    "every day at 9 am",
    "every monday at 6 pm",
    "every 15 minutes",
    "every minute",
    "each minute",
    "every hour",
    "daily at 02:30",
    "weekly on sunday at 07:00",
    "biweekly on wednesday at 6 pm",
    "every other week on sat at 8 am",
    "every two weeks on monday at 5 pm",
    "monthly on the 15th at 9 am",
]


def _parse_time(text: str) -> Optional[tuple[int, int]]:
    text = text.strip().lower()
    # Special keywords
    if text == "noon":
        return 12, 0
    if text == "midnight":
        return 0, 0
    # HH:MM 24h
    m = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2))
        if 0 <= h < 24 and 0 <= mi < 60:
            return h, mi
        return None
    # 12h am/pm (also accept single-letter a/p)
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(a|p|am|pm)$", text)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2) or 0)
        ap = m.group(3)
        if ap == "a":
            ap = "am"
        elif ap == "p":
            ap = "pm"
        if not (1 <= h <= 12 and 0 <= mi < 60):
            return None
        if ap == "pm" and h != 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        return h, mi
    return None


def _nl_to_cron_core(s: str) -> Optional[str]:
    # every N minutes
    m = re.match(r"^every\s+(\d{1,2})\s+minutes?$", s)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 59:
            return f"*/{n} * * * *"

    # every minute / each minute
    if s in ("every minute", "each minute"):
        return "* * * * *"

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


def _cron_to_extras(cron: str) -> Dict[str, object]:
    extras: Dict[str, object] = {}
    try:
        minute, hour, dom, mon, dow = cron.strip().split()
        if minute.isdigit():
            extras["minute"] = int(minute)
        if hour.isdigit():
            extras["hour"] = int(hour)
        if dom.isdigit():
            extras["day_of_month"] = int(dom)
        if dow.isdigit():
            wd = int(dow)
            if 0 <= wd <= 6:
                extras["weekday"] = wd
        elif ',' in dow:
            lst: List[int] = []
            for tok in dow.split(','):
                tok = tok.strip()
                if tok.isdigit():
                    v = int(tok)
                    if 0 <= v <= 6:
                        lst.append(v)
            if lst:
                extras["weekdays"] = lst
    except Exception:
        pass
    return extras


def nl_to_cron_with_suggestions(text: str, max_suggestions: int = 3) -> Tuple[Optional[str], List[str]]:
    """Return (cron, suggestions). cron is None if unparsed; suggestions are close example phrases."""
    s = re.sub(r"\s+", " ", text.strip().lower())
    if not s:
        return None, []
    cron = _nl_to_cron_core(s)
    if cron is not None:
        return cron, []
    sugg = difflib.get_close_matches(s, EXAMPLE_PHRASES, n=max_suggestions, cutoff=0.5)
    return None, sugg


def nl_to_cron(text: str) -> Optional[str]:
    """Backward-compatible simple API that returns only cron or None."""
    cron, _ = nl_to_cron_with_suggestions(text)
    return cron


def _ordinal_to_int(tok: str) -> Optional[int]:
    # supports 1st..31st
    m = re.match(r"^(\d{1,2})(st|nd|rd|th)$", tok)
    if not m:
        return None
    v = int(m.group(1))
    if 1 <= v <= 31:
        return v
    return None


def nl_to_cron_and_extras(text: str, max_suggestions: int = 3) -> Tuple[Optional[str], Dict[str, object], List[str]]:
    """Advanced NL parser returning (cron, extras, suggestions).
    extras may include keys like {"biweekly": True} used by the UI/backend.
    """
    s = re.sub(r"\s+", " ", text.strip().lower())
    extras: Dict[str, object] = {}
    if not s:
        return None, extras, []

    # biweekly: variants "biweekly", "every other week", "every two weeks"
    m = re.match(r"^(biweekly|every\s+other\s+week|every\s+two\s+weeks)\s+on\s+([a-z]+)\s+at\s+(.+)$", s)
    if m:
        wd = m.group(2)
        tm = _parse_time(m.group(3))
        if wd in WEEKDAYS and tm:
            h, mi = tm
            extras["biweekly"] = True
            # anchor optional; backend will default to today if missing
            cron = f"{mi} {h} * * {WEEKDAYS[wd]}"
            extras.update(_cron_to_extras(cron))
            return cron, extras, []

    # monthly: "monthly on the 15th at 9 am" or "on the 1st of the month at 07:30"
    m = re.match(r"^monthly\s+on\s+the\s+([0-9]{1,2}(?:st|nd|rd|th))\s+at\s+(.+)$", s)
    if m:
        dom = _ordinal_to_int(m.group(1))
        tm = _parse_time(m.group(2))
        if dom and tm:
            h, mi = tm
            cron = f"{mi} {h} {dom} * *"
            extras.update(_cron_to_extras(cron))
            return cron, extras, []

    m = re.match(r"^on\s+the\s+([0-9]{1,2}(?:st|nd|rd|th))\s+of\s+the\s+month\s+at\s+(.+)$", s)
    if m:
        dom = _ordinal_to_int(m.group(1))
        tm = _parse_time(m.group(2))
        if dom and tm:
            h, mi = tm
            return f"{mi} {h} {dom} * *", extras, []

    # fall back to core and suggestions
    cron = _nl_to_cron_core(s)
    if cron is not None:
        extras.update(_cron_to_extras(cron))
        return cron, extras, []
    # Combined weekdays with time: "every monday, wednesday and thursday at 5 pm" (and "every other ...")
    m = re.match(r"^every\s+(other\s+)?(.+?)\s+at\s+(.+)$", s)
    if m:
        every_other = bool(m.group(1))
        days = m.group(2)
        tm = _parse_time(m.group(3))
        if tm:
            norm = re.sub(r"\band\b", ",", days)
            parts = [p.strip() for p in norm.split(',') if p.strip()]
            wds: List[int] = []
            for p in parts:
                tok = p.lower()
                if tok in WEEKDAYS:
                    wds.append(WEEKDAYS[tok])
            if wds:
                h, mi = tm
                dowfield = ",".join(str(v) for v in wds)
                cron = f"{mi} {h} * * {dowfield}"
                if every_other:
                    extras["biweekly"] = True
                extras.update(_cron_to_extras(cron))
                return cron, extras, []
    # Recognize weekday-only phrases (single or multiple), e.g.,
    # "every monday" or "every monday, wednesday and thursday"
    # and biweekly variant: "every other saturday and sunday"
    m = re.match(r"^every\s+(other\s+)?(.+)$", s)
    if m:
        every_other = bool(m.group(1))
        tail = m.group(2)
        # Extract weekdays list from tail (comma and 'and' separated)
        # Normalize separators to commas, then split
        norm = re.sub(r"\band\b", ",", tail)
        parts = [p.strip() for p in norm.split(',') if p.strip()]
        wds: List[int] = []
        for p in parts:
            tok = p.lower()
            if tok in WEEKDAYS:
                wds.append(WEEKDAYS[tok])
        if wds:
            if len(wds) == 1:
                extras["weekday"] = wds[0]
            else:
                extras["weekdays"] = wds
            if every_other:
                extras["biweekly"] = True
            return None, extras, []
    sugg = difflib.get_close_matches(s, EXAMPLE_PHRASES, n=max_suggestions, cutoff=0.5)
    return None, extras, sugg
