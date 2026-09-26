#!/usr/bin/env python3
"""build_earnings_reactions.py — per-name earnings dates and reaction history (item 1.3).

For every analyzed name (held, screen board top 40; the index ETFs have no earnings): the
next earnings date from the provider's earnings calendar with source and retrieval date,
and the historical earnings-day reaction series from the price store — close on the last
session before the release to close on the first session after — for every release in the
last six years. A release timed after the close (hour ≥ 12 on the provider's stamp) reacts
from that session's close to the next session's; one timed before the open reacts from the
prior session's close to that session's.

Writes data/options/earnings_reactions.json (weekly refresh per name; provider failures keep
the existing record and are reported). The exceedance against the implied move is computed
by the lens, which is where the chain lives.

Usage:  python scripts/options/build_earnings_reactions.py [--force] [--tickers MU,GEV] [--allow-non-trading]
"""
from __future__ import annotations
import argparse
import json
import sys
import warnings
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import options_common as oc
from trading_calendar import last_completed_session, now_et, require_trading_day

warnings.filterwarnings("ignore")
OUT = oc.OPT / "earnings_reactions.json"
YEARS = 6
REFRESH_DAYS = 7
SOURCE = "provider earnings calendar (yfinance Ticker.get_earnings_dates); dates are the provider's, estimated until confirmed"


def log(m: str) -> None:
    print(f"[earnings_reactions] {m}", flush=True)


def fetch_dates(tk: str) -> list[pd.Timestamp]:
    import yfinance as yf
    ed = yf.Ticker(tk).get_earnings_dates(limit=60)
    if ed is None or ed.empty:
        return []
    idx = pd.to_datetime(ed.index)
    idx = idx.tz_localize(None) if getattr(idx, "tz", None) is not None else idx
    return sorted(set(idx))


def reactions(dates: list[pd.Timestamp], closes: pd.Series, session: pd.Timestamp) -> list[dict]:
    out = []
    lo = session - pd.DateOffset(years=YEARS)
    c = closes.dropna()
    for d in dates:
        if d > session or d < lo:
            continue
        day = d.normalize(); after_close = d.hour >= 12
        if after_close:
            pre, post = c.loc[:day], c.loc[day + pd.Timedelta(days=1):]
        else:
            pre, post = c.loc[:day - pd.Timedelta(days=1)], c.loc[day:]
        if not len(pre) or not len(post):
            continue
        out.append({"date": str(day.date()), "time_of_day": "after_close" if after_close else "before_open",
                    "pre_date": str(pre.index[-1].date()), "post_date": str(post.index[0].date()),
                    "reaction": round(float(post.iloc[0] / pre.iloc[-1] - 1.0), 5)})
    return out


def stats(rx: list[dict]) -> dict:
    a = np.array([abs(r["reaction"]) for r in rx])
    if not len(a):
        return {"n": 0}
    last8 = a[-8:]
    return {"n": int(len(a)), "mean_abs": round(float(a.mean()), 5), "median_abs": round(float(np.median(a)), 5),
            "max_abs": round(float(a.max()), 5), "max_date": rx[int(a.argmax())]["date"],
            "n_last8": int(len(last8)), "median_abs_last8": round(float(np.median(last8)), 5),
            "mean_abs_last8": round(float(last8.mean()), 5)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--tickers", default="")
    ap.add_argument("--allow-non-trading", action="store_true")
    ap.add_argument("--print", dest="do_print", action="store_true")
    args = ap.parse_args()
    require_trading_day("earnings_reactions")
    session = pd.Timestamp(last_completed_session())
    now = now_et(); today = now.date(); retrieved = now.isoformat(timespec="seconds")
    uni = oc.analyzed_universe()
    tks = [t.strip().upper() for t in args.tickers.split(",") if t.strip()] or [t for t, r in uni.items() if r != ["index"]]
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    names = dict(prev.get("names", {}))
    cl, prov = oc.closes(tks, str(session.date()), years=YEARS + 1)
    fetched, kept, failed = [], [], []
    for tk in tks:
        cur = names.get(tk)
        fresh = (cur and not args.force and cur.get("retrieved_at")
                 and date.fromisoformat(cur["retrieved_at"][:10]) + timedelta(days=REFRESH_DAYS) >= today
                 and (cur.get("next") or {}).get("date", "9999") >= today.isoformat())
        if fresh:
            kept.append(tk); continue
        try:
            dates = fetch_dates(tk)
        except Exception as e:
            failed.append(f"{tk}: {type(e).__name__}"); continue
        if not dates:
            failed.append(f"{tk}: no earnings dates from the provider"); continue
        fut = [d for d in dates if d > session]
        nxt = fut[0] if fut else None
        rx = reactions(dates, cl[tk], session) if tk in cl.columns else []
        names[tk] = {
            "next": ({"date": str(nxt.date()), "time_of_day": "after_close" if nxt.hour >= 12 else "before_open",
                      "provider_stamp": nxt.isoformat()} if nxt is not None else None),
            "history": rx, "stats": stats(rx),
            "source": SOURCE, "retrieved_at": retrieved, "history_years": YEARS,
        }
        fetched.append(tk)
    payload = {"cadence": "daily", "session_date": str(session.date()), "as_of": today.isoformat(),
               "computed_at": retrieved, "history_years": YEARS,
               "reaction_rule": ("close on the last session before the release to close on the first session after; "
                                 "after-close releases (provider stamp hour ≥ 12) react close(D)→close(D+1), before-open "
                                 "releases close(D−1)→close(D)"),
               "closes_provenance": prov, "names": names,
               "note": "descriptive; the market's priced move and the past reactions are compared by the lens; no recommendation"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2))
    log(f"{len(tks)} names · fetched {len(fetched)} · kept {len(kept)} · failed {len(failed)} → {OUT.relative_to(oc.REPO)}")
    for f_ in failed:
        log(f"  FAILED {f_}")
    if "--print" in sys.argv:
        for tk in tks:
            n = names.get(tk, {}); s = n.get("stats", {}); nx = n.get("next") or {}
            log(f"  {tk:5} next {nx.get('date')} {nx.get('time_of_day', '')} · n {s.get('n')} median|r| {s.get('median_abs')} max {s.get('max_abs')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
