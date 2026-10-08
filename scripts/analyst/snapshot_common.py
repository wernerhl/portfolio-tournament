#!/usr/bin/env python3
"""
snapshot_common.py — the availability date of an analyst-estimate snapshot (follow-up orders of 7 October 2026,
F4 and G5).

A snapshot file is named for the session the nightly publishes and is captured after that session's close, or as
late as 06:41 ET on the next day. Analysts publish revisions after the close, overnight and before the open, so
the information in a file named for session d need not have existed at the close of d. `available_from` is the
first trading session at whose close the information existed: the capture's own ET date when that date is a
trading day AND the capture came before its close (16:00 ET, or 13:00 ET on an early-close day); otherwise the
next trading session. So a capture at 15:50 ET on d is available for d; one at 17:30 ET on d only from the next
session; one at 04:31 ET on d+1 from d+1; a Saturday capture from Monday.

Readers derive the date from `captured_at` on every read (snapshot_available_from). The field stored in each
immutable file stays as written; where it differs from the derived date the referee reports
INFO analyst:available_from_restated (the first files, written under the F4 rule, differ).
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from trading_calendar import is_trading_day   # noqa: E402

ET = ZoneInfo("America/New_York")
# NYSE early closes (13:00 ET): the day after Thanksgiving and Christmas Eve when it is a weekday, and 3 July when
# Independence Day falls on a weekday. Kept in step with the exchange's published calendar.
EARLY_CLOSE = {
    date(2025, 7, 3), date(2025, 11, 28), date(2025, 12, 24),
    date(2026, 11, 27), date(2026, 12, 24),
    date(2027, 11, 26),
}


def close_time(d: date) -> tuple[int, int]:
    return (13, 0) if d in EARLY_CLOSE else (16, 0)


def available_from(captured_at: str | datetime) -> str:
    """The first trading session (ISO date) at whose close the capture's information existed."""
    t = datetime.fromisoformat(captured_at) if isinstance(captured_at, str) else captured_at
    if t.tzinfo is None:
        t = t.replace(tzinfo=ET)
    t = t.astimezone(ET)
    d = t.date()
    if is_trading_day(d) and (t.hour, t.minute) < close_time(d):
        return d.isoformat()
    d = d + timedelta(days=1)
    while not is_trading_day(d):
        d = d + timedelta(days=1)
    return d.isoformat()


def snapshot_available_from(snapshot: dict) -> str:
    """Derived from captured_at on every read (G5); the stored field is never used for a date."""
    return available_from(snapshot["captured_at"])


def stored_differs(snapshot: dict) -> bool:
    """True when the file's stored available_from differs from the derived one (reported, never rewritten)."""
    s = snapshot.get("available_from")
    return bool(s) and str(s)[:10] != snapshot_available_from(snapshot)


def usable_for(snapshot: dict, as_of: str | date) -> bool:
    """True when the snapshot's information existed at the close of `as_of`."""
    d = as_of if isinstance(as_of, str) else as_of.isoformat()
    return snapshot_available_from(snapshot) <= d[:10]
