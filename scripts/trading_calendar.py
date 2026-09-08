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


def now_et(now: datetime | None = None) -> datetime:
    """Current time in America/New_York. Test override: env NOW_ET_OVERRIDE
    ('YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM') — lets SEPT AUDIT [2.3] verify the
    non-trading-day gate without waiting for a holiday."""
    import os
    from zoneinfo import ZoneInfo
    ov = os.environ.get("NOW_ET_OVERRIDE")
    if ov:
        try:
            return datetime.fromisoformat(ov).replace(tzinfo=ZoneInfo("America/New_York"))
        except ValueError:
            pass
    return (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))


def require_trading_day(job: str) -> str:
    """SEPT AUDIT [2]: the gate for EVERY job that writes data/. On a
    non-trading ET day it prints the standard line and exits 0 — writing
    nothing. Returns the ET date when trading. `--allow-non-trading` on argv
    bypasses it for manual analysis runs (never passed in CI)."""
    import sys
    d = now_et().strftime("%Y-%m-%d")
    if not is_trading_day(d) and "--allow-non-trading" not in sys.argv:
        print(f"[{job}] market closed, nothing to do ({d})", flush=True)
        sys.exit(0)
    return d


def served_meta(cadence: str = "daily", session_date: str | None = None,
                as_of: str | None = None) -> dict:
    """SEPT AUDIT [5]: declared dates for served JSON. Daily files carry
    session_date (the completed session the data represents); static /
    on_change / weekly files carry cadence + as_of so a stale-badge check can
    tell them apart from stale daily files."""
    et = now_et()
    meta = {"cadence": cadence, "computed_at": et.isoformat(timespec="seconds")}
    if cadence == "daily":
        meta["session_date"] = session_date or last_trading_session()
    else:
        meta["as_of"] = as_of or et.strftime("%Y-%m-%d")
    return meta


def last_completed_session(now: datetime | None = None) -> str:
    """Most recent COMPLETED NYSE session as of `now`, in ET: today if it is a
    trading day and the clock is past 16:15 ET (close + 15 min), otherwise the
    previous trading day. Reconciliation memo 8-Sept, decision 3: publishing
    keys on THIS session, never on the wall-clock calendar date — a cron
    throttled past 00:00 UTC publishes Friday's session instead of refusing."""
    from zoneinfo import ZoneInfo
    et = now.astimezone(ZoneInfo("America/New_York")) if (now is not None and now.tzinfo) else now_et()
    d = et.date()
    if not (is_trading_day(d) and (et.hour, et.minute) >= (16, 15)):
        d = date.fromisoformat(prev_trading_day(d))
    return d.isoformat()


def last_trading_session(now: datetime | None = None) -> str:
    """Most recent COMPLETED session as of `now`. Delegates to
    last_completed_session (ET, close + 15 min) so every caller — the daily
    job's guard, validation, served_meta — agrees on the session."""
    return last_completed_session(now)


def _last_trading_session_legacy(now: datetime | None = None) -> str:
    """Pre-memo UTC heuristic (~21:30 UTC); kept only for reference."""
    import os
    if now is None and os.environ.get("NOW_ET_OVERRIDE"):
        now = now_et().astimezone(timezone.utc)
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
