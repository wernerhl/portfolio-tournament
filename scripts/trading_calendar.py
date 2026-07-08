"""
trading_calendar.py — ONE trading calendar for every job (JULY AUDIT FIX 5).

The repo previously disagreed with itself about which days exist:
regime_daily.csv contained 2026-07-03 (NYSE closed, July 4 observed) built
from a business-day reindex + ffill, while tournament.json correctly skipped
it. Every job now imports this module; no job writes a row on a non-trading
day, and CI asserts every published date ∈ calendar.

NYSE full-closure holidays, hardcoded 2025-2027 (verify annually).
For dates before 2025 use is_weekday() only — historical rows come from
actual exchange data and never contained phantoms until reindexing; the
source-level fix (filter to real price-bar dates) covers deep history.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta, timezone

NYSE_HOLIDAYS = {
    # 2025
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
    "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
    # 2026 (July 4 falls Saturday → observed Friday 2026-07-03)
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    # 2027 (Juneteenth Sat → observed 06-18; July 4 Sun → observed 07-05;
    #       Christmas Sat → observed 12-24)
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}

CALENDAR_START = "2025-01-01"
CALENDAR_END   = "2027-12-31"


def _iso(d) -> str:
    if isinstance(d, str):
        return d[:10]
    if isinstance(d, (datetime, date)):
        return d.strftime("%Y-%m-%d")
    return str(d)[:10]


def is_weekday(d) -> bool:
    s = _iso(d)
    return date.fromisoformat(s).weekday() < 5


def is_trading_day(d) -> bool:
    """Weekday and not an NYSE holiday. Outside the hardcoded 2025-2027
    window, falls back to weekday-only (documented limitation)."""
    s = _iso(d)
    if not is_weekday(s):
        return False
    if CALENDAR_START <= s <= CALENDAR_END:
        return s not in NYSE_HOLIDAYS
    return True


def prev_trading_day(d) -> str:
    cur = date.fromisoformat(_iso(d)) - timedelta(days=1)
    while not is_trading_day(cur):
        cur -= timedelta(days=1)
    return cur.isoformat()


def last_trading_session(now: datetime | None = None) -> str:
    """Most recent COMPLETED session as of `now` (UTC). Before ~21:30 UTC a
    weekday's close doesn't exist yet."""
    now = now or datetime.now(timezone.utc)
    d = now.date()
    complete_today = (now.hour > 21 or (now.hour == 21 and now.minute >= 30))
    if not (is_trading_day(d) and complete_today):
        d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d.isoformat()


def filter_trading_days(index_like) -> list:
    """Filter an iterable of dates to trading days (calendar window aware)."""
    return [d for d in index_like if is_trading_day(d)]
