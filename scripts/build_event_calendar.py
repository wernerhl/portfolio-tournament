"""
Generate data/event_calendar.json — scheduled macro events 2024-2027.

These are CONDITIONING markers only — they tell us when the vol regime read
is conditional on a print, NOT directions. NEVER use these for tilts.

Categories:
  - NFP: first Friday of each month (BLS)
  - CPI: ~2nd Tuesday (BLS publishes mid-month for prior month; approx OK)
  - FOMC: hardcoded official meeting calendar
  - TREASURY: 10Y note + 30Y bond auctions (approx mid-month dates)

Output: data/event_calendar.json
  { "events": [ {"date": "YYYY-MM-DD", "type": "NFP"|"CPI"|"FOMC"|"TREASURY",
                 "name": "Nonfarm Payrolls" | ... } ] }
"""
from __future__ import annotations
import json, calendar
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT  = REPO / "data" / "event_calendar.json"

# ── FOMC official meeting dates (Day-2 statement release) ─────────────
# Published at federalreserve.gov/monetarypolicy/fomccalendars.htm
FOMC = [
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
    "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-16",
    "2027-07-28", "2027-09-22", "2027-11-03", "2027-12-15",
]


def first_friday(y: int, m: int) -> date:
    """First Friday of (year, month) — used for NFP release."""
    d = date(y, m, 1)
    # weekday(): Mon=0 ... Fri=4
    return d + timedelta(days=(4 - d.weekday()) % 7)


def nth_weekday(y: int, m: int, weekday: int, n: int) -> date:
    """Nth occurrence of a weekday (0=Mon) in (year, month)."""
    d = date(y, m, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def main():
    events = []

    # NFP — first Friday of every month, 2024-2027
    for y in range(2024, 2028):
        for m in range(1, 13):
            d = first_friday(y, m)
            events.append({"date": d.isoformat(), "type": "NFP",
                           "name": "Nonfarm Payrolls",
                           "label": "NFP"})

    # CPI — ~2nd Tuesday of every month (BLS approximate; actual dates vary
    # by 1-3 days but second-Tuesday catches >80% of releases in the window
    # where vol reactions are most visible). Acceptable for a conditioning
    # marker; precision matters for trading on the print, not for tagging.
    for y in range(2024, 2028):
        for m in range(1, 13):
            d = nth_weekday(y, m, weekday=1, n=2)   # Tuesday=1
            events.append({"date": d.isoformat(), "type": "CPI",
                           "name": "Consumer Price Index",
                           "label": "CPI"})

    # FOMC — from hardcoded list
    for d_str in FOMC:
        events.append({"date": d_str, "type": "FOMC",
                       "name": "FOMC Statement",
                       "label": "FOMC"})

    # Treasury auctions — major ones only (10Y note + 30Y bond),
    # historically 2nd-week dates. We tag both Tuesday + Wednesday of
    # the 2nd full week as auction days; granular precision isn't worth
    # the maintenance burden vs the conditioning value.
    for y in range(2024, 2028):
        for m in range(1, 13):
            d10 = nth_weekday(y, m, weekday=1, n=2)   # 2nd Tuesday → 10Y note
            d30 = nth_weekday(y, m, weekday=2, n=2)   # 2nd Wed     → 30Y bond
            events.append({"date": d10.isoformat(), "type": "TREASURY",
                           "name": "10Y Note Auction", "label": "10Y"})
            events.append({"date": d30.isoformat(), "type": "TREASURY",
                           "name": "30Y Bond Auction", "label": "30Y"})

    # Sort + dedup
    events.sort(key=lambda e: (e["date"], e["type"]))
    payload = {
        "version": "1.0",
        "note": ("Scheduled macro events 2024-2027. CONDITIONING markers only — "
                 "vol reaction may be larger than usual around these days, but "
                 "this file encodes ZERO directional information. Pre-FOMC drift "
                 "is published, crowded, and decayed; do not add tilts."),
        "events": events,
    }
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=2)
    by_type = {}
    for e in events:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
    print(f"saved {OUT}  ({len(events)} events)")
    for k, n in sorted(by_type.items()):
        print(f"  {k:10s} {n}")


if __name__ == "__main__":
    main()
