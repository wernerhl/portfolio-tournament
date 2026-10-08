#!/usr/bin/env python3
"""
snapshot_common.py — the availability date of an analyst-estimate snapshot (follow-up order of 7 October 2026, F4).

A snapshot file is named for the session the nightly publishes and can be captured as late as 06:41 ET on the next
day. Analysts publish revisions overnight and before the open, so a file named for session d can hold information
that did not exist at the close of d. Each snapshot therefore carries `available_from`: the first trading session
whose close is at or after the capture — the capture's own ET date when that is a trading day (a capture at
17:30 ET on d is available for d; a capture at 04:31 ET on d+1 only from d+1), else the next trading day. The
revisions builder and the registered test use a snapshot only for dates at or after `available_from`. Files
written before the field existed (the first snapshot, 2026-10-06) get it derived from `captured_at`.
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


def available_from(captured_at: str | datetime) -> str:
    """The first trading session (ISO date) whose close is at or after the capture time."""
    t = datetime.fromisoformat(captured_at) if isinstance(captured_at, str) else captured_at
    if t.tzinfo is None:
        t = t.replace(tzinfo=ET)
    d = t.astimezone(ET).date()
    while not is_trading_day(d):
        d = d + timedelta(days=1)
    return d.isoformat()


def snapshot_available_from(snapshot: dict) -> str:
    """The field when the file carries it, else derived from captured_at (files written before F4)."""
    if snapshot.get("available_from"):
        return str(snapshot["available_from"])[:10]
    return available_from(snapshot["captured_at"])


def usable_for(snapshot: dict, as_of: str | date) -> bool:
    """True when the snapshot's information existed at the close of `as_of`."""
    d = as_of if isinstance(as_of, str) else as_of.isoformat()
    return snapshot_available_from(snapshot) <= d[:10]
