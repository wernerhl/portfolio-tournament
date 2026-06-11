"""
Generate data/event_calendar.json — scheduled macro events 2024-2027.

AUDIT FIX 1 (2026-06-11): dates now come from OFFICIAL release schedules, not
inferred weekday rules. The old "second Tuesday" CPI rule was wrong by a day
(May-2026 CPI released Wed 2026-06-10, not Tue 06-09), which mis-tagged spikes
and contaminated the event-day validation subsample.

Sources (retrieved 2026-06-11 via web.archive.org snapshots of the official
BLS schedule pages + Federal Reserve FOMC calendar):
  CPI:  https://www.bls.gov/schedule/news_release/cpi.htm
  NFP:  https://www.bls.gov/schedule/news_release/empsit.htm  (Employment Situation)
  FOMC: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
  TSY:  https://www.treasurydirect.gov/auctions/upcoming/ (pattern: monthly
        refunding 3Y Tue / 10Y Wed / 30Y Thu of the second full week)

2027 BLS schedules are not yet published — those months are PATTERN ESTIMATES
and flagged as such in provenance. Each event stores
{date, type, name, label, source_url, retrieved_at, provenance}.

These are CONDITIONING markers only. ZERO directional information. Pre-FOMC
drift is published, crowded, and decayed; do not add tilts.
"""
from __future__ import annotations
import json
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT  = REPO / "data" / "event_calendar.json"

RETRIEVED_AT = "2026-06-11"
SRC_CPI  = "https://www.bls.gov/schedule/news_release/cpi.htm"
SRC_NFP  = "https://www.bls.gov/schedule/news_release/empsit.htm"
SRC_FOMC = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
SRC_TSY  = "https://www.treasurydirect.gov/auctions/upcoming/"

# ── OFFICIAL CPI release dates (BLS schedule pages, archived) ──────────
# 2025 reflects ACTUALS including the Oct-Nov 2025 shutdown disruptions
# (September-2025 data released 10-24; October-2025 data release skipped).
OFFICIAL_CPI = {
    2024: ["2024-01-11","2024-02-13","2024-03-12","2024-04-10","2024-05-15","2024-06-12",
            "2024-07-11","2024-08-14","2024-09-11","2024-10-10","2024-11-13","2024-12-11"],
    2025: ["2025-01-15","2025-02-12","2025-03-12","2025-04-10","2025-05-13","2025-06-11",
            "2025-07-15","2025-08-12","2025-09-11","2025-10-24","2025-12-18"],
    2026: ["2026-01-13","2026-02-13","2026-03-11","2026-04-10","2026-05-12","2026-06-10",
            "2026-07-14","2026-08-12","2026-09-11","2026-10-14","2026-11-10","2026-12-10"],
}

# ── OFFICIAL Employment Situation (NFP) release dates ──────────────────
OFFICIAL_NFP = {
    2024: ["2024-01-05","2024-02-02","2024-03-08","2024-04-05","2024-05-03","2024-06-07",
            "2024-07-05","2024-08-02","2024-09-06","2024-10-04","2024-11-01","2024-12-06"],
    2025: ["2025-01-10","2025-02-07","2025-03-07","2025-04-04","2025-05-02","2025-06-06",
            "2025-07-03","2025-08-01","2025-09-05","2025-11-20","2025-12-16"],
    2026: ["2026-01-09","2026-02-11","2026-03-06","2026-04-03","2026-05-08","2026-06-05",
            "2026-07-02","2026-08-07","2026-09-04","2026-10-02","2026-11-06","2026-12-04"],
}

# ── OFFICIAL FOMC decision (statement, day-2) dates ────────────────────
FOMC = [
    "2024-01-31","2024-03-20","2024-05-01","2024-06-12",
    "2024-07-31","2024-09-18","2024-11-07","2024-12-18",
    "2025-01-29","2025-03-19","2025-05-07","2025-06-18",
    "2025-07-30","2025-09-17","2025-10-29","2025-12-10",
    "2026-01-28","2026-03-18","2026-04-29","2026-06-17",
    "2026-07-29","2026-09-16","2026-10-28","2026-12-09",
    "2027-01-27","2027-03-17","2027-04-28","2027-06-16",
    "2027-07-28","2027-09-22","2027-11-03","2027-12-15",
]


def first_friday(y: int, m: int) -> date:
    d = date(y, m, 1)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def nth_weekday(y: int, m: int, weekday: int, n: int) -> date:
    d = date(y, m, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def main():
    events = []

    # CPI — official 2024-2026; 2027 pattern estimate (≈2nd Wednesday)
    for y, dates in OFFICIAL_CPI.items():
        for d in dates:
            events.append({"date": d, "type": "CPI", "name": "Consumer Price Index",
                            "label": "CPI", "source_url": SRC_CPI,
                            "retrieved_at": RETRIEVED_AT, "provenance": "official"})
    for m in range(1, 13):
        d = nth_weekday(2027, m, weekday=2, n=2)   # Wednesday=2
        events.append({"date": d.isoformat(), "type": "CPI", "name": "Consumer Price Index",
                        "label": "CPI", "source_url": SRC_CPI, "retrieved_at": RETRIEVED_AT,
                        "provenance": "pattern_estimate (BLS 2027 schedule not yet published)"})

    # NFP — official 2024-2026; 2027 first-Friday pattern
    for y, dates in OFFICIAL_NFP.items():
        for d in dates:
            events.append({"date": d, "type": "NFP", "name": "Nonfarm Payrolls",
                            "label": "NFP", "source_url": SRC_NFP,
                            "retrieved_at": RETRIEVED_AT, "provenance": "official"})
    for m in range(1, 13):
        d = first_friday(2027, m)
        events.append({"date": d.isoformat(), "type": "NFP", "name": "Nonfarm Payrolls",
                        "label": "NFP", "source_url": SRC_NFP, "retrieved_at": RETRIEVED_AT,
                        "provenance": "pattern_estimate (BLS 2027 schedule not yet published)"})

    # FOMC — official list
    for d in FOMC:
        events.append({"date": d, "type": "FOMC", "name": "FOMC Statement",
                        "label": "FOMC", "source_url": SRC_FOMC,
                        "retrieved_at": RETRIEVED_AT, "provenance": "official"})

    # Treasury — monthly refunding pattern: 3Y Tue / 10Y Wed / 30Y Thu of the
    # second full week. Pattern-based (TreasuryDirect publishes only a rolling
    # window of exact dates).
    for y in range(2024, 2028):
        for m in range(1, 13):
            d3  = nth_weekday(y, m, weekday=1, n=2)   # 2nd Tuesday  → 3Y note
            d10 = nth_weekday(y, m, weekday=2, n=2)   # 2nd Wednesday → 10Y note
            d30 = nth_weekday(y, m, weekday=3, n=2)   # 2nd Thursday → 30Y bond
            for d, lbl, name in [(d3, "3Y", "3Y Note Auction"),
                                  (d10, "10Y", "10Y Note Auction"),
                                  (d30, "30Y", "30Y Bond Auction")]:
                events.append({"date": d.isoformat(), "type": "TREASURY", "name": name,
                                "label": lbl, "source_url": SRC_TSY,
                                "retrieved_at": RETRIEVED_AT,
                                "provenance": "refunding weekday pattern"})

    events.sort(key=lambda e: (e["date"], e["type"], e["label"]))

    # ── HARD ASSERTS (fail CI on calendar regression) ───────────────────
    by = {}
    for e in events:
        by.setdefault((e["date"], e["type"]), []).append(e)
    assert ("2026-06-10", "CPI") in by, "ASSERT FAIL: May-2026 CPI must be 2026-06-10 (BLS official)"
    assert ("2026-06-09", "CPI") not in by, "ASSERT FAIL: stale 2026-06-09 CPI entry present"
    assert ("2026-06-05", "NFP") in by, "ASSERT FAIL: June NFP must be 2026-06-05"
    assert ("2026-06-17", "FOMC") in by, "ASSERT FAIL: 2026-06-17 FOMC decision missing"
    import datetime as _dt
    for e in events:
        wd = _dt.date.fromisoformat(e["date"]).weekday()
        assert wd < 5, f"ASSERT FAIL: weekend event {e['date']} {e['type']}"
    print("  hard asserts: May-2026 CPI=06-10 ✓ · June NFP=06-05 ✓ · FOMC 06-17 ✓ · all weekdays ✓")

    payload = {
        "version": "2.0",
        "rebuilt_at": RETRIEVED_AT,
        "note": ("Scheduled macro events 2024-2027 from OFFICIAL release schedules "
                  "(2027 BLS = pattern estimate). CONDITIONING markers only — these "
                  "encode ZERO directional information. Pre-FOMC drift is published, "
                  "crowded, and decayed; do not add tilts."),
        "events": events,
    }
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=2)
    by_type = {}
    for e in events:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
    print(f"  saved {OUT}  ({len(events)} events)")
    for k, n in sorted(by_type.items()):
        print(f"    {k:10s} {n}")


if __name__ == "__main__":
    main()
