#!/usr/bin/env python3
"""build_earnings_calendar.py — earnings dates into the event calendar (order 16-Sept-2026, item 3.2).

"review_by for each is the next earnings date plus fourteen days, taken from the event
calendar module; the auto-log records each earnings date against these entries." The macro
calendar (build_event_calendar.py) carries no earnings dates, so this job adds them: for the
held names, the tickers of the register's sub-thesis claims and the members of ai_infra, the
provider's next earnings date (yfinance Ticker.calendar, "Earnings Date") is merged into
data/event_calendar.json as an EARNINGS event with its source and retrieval date. One upcoming
entry per ticker; a changed date replaces the old upcoming entry (the replacement is logged
in the event's `history`); past entries stay. Nothing else in the file is touched.

Refresh rule: a ticker is refetched when it has no upcoming entry, its entry is older than
REFRESH_DAYS, or its date has passed. --force refetches everything. Provider failures leave
the existing entry in place and are reported.

Usage:  python scripts/build_earnings_calendar.py [--force] [--tickers MU,GEV] [--allow-non-trading]
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATA = REPO / "data"
CAL = DATA / "event_calendar.json"
REFRESH_DAYS = 7
SOURCE_URL = "https://finance.yahoo.com/quote/{tk}/  (yfinance Ticker.calendar, 'Earnings Date')"
sys.path.insert(0, str(HERE))
from trading_calendar import now_et  # noqa: E402


def log(m: str) -> None:
    print(f"[build_earnings_calendar] {m}", flush=True)


def tickers_of_interest() -> list[str]:
    out: set[str] = set()
    hp = DATA / "holdings.json"
    if hp.exists():
        out |= {str(h["ticker"]).upper() for h in json.load(open(hp)).get("holdings", []) if (h.get("shares") or 0) > 0}
    cp = DATA / "thesis_claims.json"
    if cp.exists():
        for c in json.load(open(cp)).get("claims", []):
            out |= {str(t).upper() for t in (c.get("tickers") or [])}
    rp = DATA / "thesis_registry.json"
    if rp.exists():
        reg = json.load(open(rp))
        out |= set(reg["theses"].get("ai_infra", {}).get("members", {}).keys())
    return sorted(out)


def fetch_next_earnings(tk: str):
    import yfinance as yf
    cal = yf.Ticker(tk).calendar
    d = cal.get("Earnings Date") if isinstance(cal, dict) else None
    if not d:
        return None
    ds = sorted(str(x)[:10] for x in d)
    return ds[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--tickers", default="")
    ap.add_argument("--allow-non-trading", action="store_true")
    args = ap.parse_args()
    cal = json.load(open(CAL))
    events = cal.get("events", [])
    today = now_et().date()
    retrieved = now_et().isoformat(timespec="seconds")
    tks = [t.strip().upper() for t in args.tickers.split(",") if t.strip()] or tickers_of_interest()
    upcoming = {e["ticker"]: e for e in events if e.get("type") == "EARNINGS" and e.get("ticker") and e.get("date", "") >= today.isoformat()}
    changed, failed, kept = [], [], []
    for tk in tks:
        cur = upcoming.get(tk)
        stale = (cur is None or args.force or
                 (date.fromisoformat(str(cur.get("retrieved_at", "1970-01-01"))[:10]) + timedelta(days=REFRESH_DAYS) < today))
        if not stale:
            kept.append(tk); continue
        try:
            nxt = fetch_next_earnings(tk)
        except Exception as e:
            failed.append(f"{tk}: {type(e).__name__}"); continue
        if not nxt:
            failed.append(f"{tk}: no earnings date from the provider"); continue
        if cur and cur["date"] == nxt:
            cur["retrieved_at"] = retrieved; kept.append(tk); continue
        ev = {"date": nxt, "type": "EARNINGS", "ticker": tk, "name": f"Earnings · {tk}", "label": tk,
              "source_url": SOURCE_URL.format(tk=tk), "retrieved_at": retrieved,
              "provenance": "provider earnings calendar (yfinance Ticker.calendar); the date is the provider's, "
                            "estimated until the company confirms it"}
        if cur:
            ev["history"] = (cur.get("history") or []) + [{"date": cur["date"], "retrieved_at": cur.get("retrieved_at"), "replaced": retrieved}]
            events.remove(cur)
        events.append(ev); upcoming[tk] = ev; changed.append(f"{tk} {nxt}" + (f" (was {cur['date']})" if cur else ""))
    events.sort(key=lambda e: (e["date"], e["type"], e.get("label", "")))
    cal["events"] = events
    cal["earnings_note"] = ("EARNINGS events: provider earnings calendar per ticker for the held names, the register's claim "
                            "tickers and the ai_infra members; one upcoming entry per ticker, refreshed weekly; "
                            "written by scripts/build_earnings_calendar.py")
    with open(CAL, "w") as f:
        json.dump(cal, f, indent=2)
    log(f"{len(tks)} tickers · added/changed {len(changed)} · kept {len(kept)} · failed {len(failed)}")
    for c in changed: log(f"  {c}")
    for f_ in failed: log(f"  FAILED {f_}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
