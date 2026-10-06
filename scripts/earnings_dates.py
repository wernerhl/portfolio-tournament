#!/usr/bin/env python3
"""
earnings_dates.py — the next earnings date per name, across sources, with conflicts shown
(Execution Order: Revision of the Entry-State Indicator and Related Fixes, 6 October 2026, section 5).

Sources per name:
  provider       the price provider's earnings dates (yfinance get_earnings_dates; time-stamped)
  provider_cal   the provider's calendar endpoint (yfinance Ticker.calendar; a date or an estimated window)
  curated        data/earnings_date_sources.json: the company's investor-relations announcement (kind ir) and
                 dates seen in the press (kind press), each with its source

When two sources give different next dates the record is flagged (conflict) and both are shown. The company's
investor-relations announcement decides once it is published; otherwise the provider's dated stamp. Lockheed
Martin on 6 Oct: provider 22 Oct, the Wall Street Journal 27 Oct, investor relations (1 Oct release) 22 Oct.

Refresh: the card names (held, board, tiers, review) every run; the rest of the universe when its record is
older than --max-age-days, at most --batch per run. Writes data/earnings_dates.json, read by entry_state.py.

Usage:  python scripts/earnings_dates.py [--tickers LMT,INCY] [--batch 80]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
REPO = HERE.parent
DATA = REPO / "data"
OUT = DATA / "earnings_dates.json"
CURATED = DATA / "earnings_date_sources.json"
HORIZON_DAYS = 120


def log(m: str) -> None:
    print(f"[earnings_dates] {m}", flush=True)


def provider_dates(tk: str, today: date) -> list[dict]:
    import yfinance as yf
    out = []
    t = yf.Ticker(tk)
    try:
        ed = t.get_earnings_dates(limit=8)
        if ed is not None and not ed.empty:
            for ts in pd.to_datetime(ed.index):
                tsn = ts.tz_convert("America/New_York") if ts.tzinfo else ts
                if today < tsn.date() <= today + timedelta(days=HORIZON_DAYS):
                    out.append({"date": str(tsn.date()), "kind": "provider", "source": "price provider (yfinance earnings dates)",
                                "time_et": tsn.strftime("%H:%M"), "time_of_day": "after_close" if tsn.hour >= 12 else "before_open"})
    except Exception as e:  # noqa: BLE001
        log(f"{tk}: provider dates {type(e).__name__}")
    try:
        cal = t.calendar
        ds = cal.get("Earnings Date") if isinstance(cal, dict) else None
        ds = sorted(d for d in (ds or []) if today < d <= today + timedelta(days=HORIZON_DAYS))
        if ds:
            out.append({"date": str(ds[0]), "kind": "provider_cal", "window_end": str(ds[-1]) if len(ds) > 1 else None,
                        "source": "price provider calendar (yfinance)" + (f", estimated window {ds[0]} to {ds[-1]}" if len(ds) > 1 else "")})
    except Exception as e:  # noqa: BLE001
        log(f"{tk}: provider calendar {type(e).__name__}")
    return out


def resolve(tk: str, sources: list[dict], today: date) -> dict:
    """The deciding date and any conflict among the sources' next dates (within the horizon)."""
    nxt = [s for s in sources if s.get("date") and today < date.fromisoformat(s["date"]) <= today + timedelta(days=HORIZON_DAYS)]
    if not nxt:
        return {"date": None, "sources": sources, "conflict": False}
    # a calendar window that contains another source's date is not a disagreement
    def same(a, b):
        if a["date"] == b["date"]:
            return True
        for x, y in ((a, b), (b, a)):
            if x.get("window_end") and x["date"] <= y["date"] <= x["window_end"]:
                return True
        return False
    distinct = []
    for s in nxt:
        if not any(same(s, d) for d in distinct):
            distinct.append(s)
    ir = [s for s in nxt if s.get("kind") == "ir"]
    prov = [s for s in nxt if s.get("kind") == "provider"]
    pick = (ir or prov or sorted(nxt, key=lambda s: s["date"]))[0]
    decided = ("the company's investor-relations announcement" if ir else "the price provider" if prov else pick.get("source"))
    conflict = len(distinct) > 1
    short = lambda s: {"provider": "price provider", "provider_cal": "provider calendar", "ir": "investor relations"}.get(s.get("kind"), s.get("short") or s.get("source", "")[:40])
    text = None
    if conflict:
        seen, parts = set(), []
        for s in nxt:
            lab = f"{short(s)} {date.fromisoformat(s['date']).strftime('%d %b')}"
            if lab not in seen:
                seen.add(lab); parts.append(lab)
        text = "; ".join(parts) + (f" — decided by investor relations: {date.fromisoformat(pick['date']).strftime('%d %b')}" if ir else "")
    return {"date": pick["date"], "time_of_day": pick.get("time_of_day"), "time_et": pick.get("time_et"),
            "decided_by": decided, "conflict": conflict, "conflict_text": text, "sources": nxt}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="")
    ap.add_argument("--batch", type=int, default=80)
    ap.add_argument("--max-age-days", type=int, default=7)
    a = ap.parse_args()
    import entry_state as es
    from trading_calendar import now_et
    today = now_et().date()
    allt, cards = es.universe_and_cards()
    card_set = set(cards["held"]) | set(cards["board"]) | set(cards["tiers"]) | set(cards.get("review", []))
    curated = (json.loads(CURATED.read_text()).get("names") or {}) if CURATED.exists() else {}
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    names = prev.get("names", {})
    if a.tickers:
        todo = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
    else:
        stale = lambda tk: (tk not in names or not names[tk].get("retrieved_at")
                            or date.fromisoformat(names[tk]["retrieved_at"][:10]) < today - timedelta(days=a.max_age_days)
                            or (names[tk].get("date") or "9999") <= today.isoformat())
        others = sorted([t for t in allt if t not in card_set and stale(t)], key=lambda t: (names.get(t) or {}).get("retrieved_at") or "")
        todo = sorted(card_set) + others[:a.batch]
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    for tk in todo:
        cur = [dict(s, kind=s.get("kind", "press")) for s in curated.get(tk, [])]
        names[tk] = {**resolve(tk, provider_dates(tk, today) + cur, today), "retrieved_at": now}
    for tk, srcs in curated.items():                         # a curated name not fetched this run still re-resolves
        if tk in names and tk not in todo:
            prov = [s for s in names[tk].get("sources", []) if s.get("kind", "").startswith("provider")]
            names[tk] = {**resolve(tk, prov + [dict(s) for s in srcs], today), "retrieved_at": names[tk].get("retrieved_at")}
    keep = {tk: v for tk, v in names.items() if tk in set(allt)}
    conflicts = {tk: v["conflict_text"] for tk, v in keep.items() if v.get("conflict")}
    payload = {"cadence": "daily", "as_of": today.isoformat(), "computed_at": now,
               "order": "Execution Order: Revision of the Entry-State Indicator (6 October 2026), section 5",
               "rule": "the company's investor-relations announcement decides once published; otherwise the provider's dated stamp; a disagreement among sources is flagged and every source shown",
               "refreshed_this_run": len(todo), "conflicts": conflicts, "names": keep}
    OUT.write_text(json.dumps(payload, indent=1, default=str))
    log(f"{len(keep)} names ({len(todo)} refreshed); {len(conflicts)} conflicts: {dict(list(conflicts.items())[:6])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
