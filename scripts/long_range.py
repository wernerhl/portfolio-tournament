#!/usr/bin/env python3
"""
long_range.py — the long-term ceiling flag and the distances to the 5-year and all-time closing highs
(Execution Order: Revision of the Entry-State Indicator and Related Fixes, 6 October 2026, section 3).

The entry rules look back 40 sessions and 200 days, so they cannot see a price level that has stopped a stock for
years. For every analyzed name, from its full daily close history (split-adjusted as charted; yfinance
auto_adjust=False, period max):

  yearly highs   the closing high of each calendar year in the lookback (the current year and the eleven before it;
                 data/entry_state_config.json, ceiling.lookback_note), each with the decline that followed: the
                 lowest close within 63 sessions after it (for a high fewer than 63 sessions old, the decline so far)
  ceilings       every pair of yearly highs within 5% of each other, at least six months apart, each followed by a
                 decline of at least 10%: the ceiling is the higher of the two (overlapping pairs merge, keeping the
                 highest level of the cluster). It stands from its latest member high; a close above it since then
                 lifts it ("broken", with the date), as the order lifts the cap on a close above the ceiling
  5-year high    the highest close in the last 1,260 sessions, with its date
  all-time high  the highest close on record, with its date

The flag itself (a close within 15% below a ceiling caps the state at WATCH) is applied by entry_state.py
against each day's close. History is refetched for a name when its record is older than --max-age-days (7), at
most --batch names per run (the nightly's time budget), all names with --all.

Writes data/long_range.json.  Usage:  python scripts/long_range.py [--all] [--tickers INCY,LMT] [--batch 120]
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
OUT = DATA / "long_range.json"
CONFIG = DATA / "entry_state_config.json"


def log(m: str) -> None:
    print(f"[long_range] {m}", flush=True)


def fetch_max(tickers: list[str]) -> dict[str, pd.Series]:
    import yfinance as yf
    out = {}
    for i in range(0, len(tickers), 40):
        batch = tickers[i:i + 40]
        try:
            d = yf.download(batch, period="max", progress=False, auto_adjust=False, group_by="ticker", threads=True)
        except Exception as e:  # noqa: BLE001
            log(f"batch {i}: {type(e).__name__}: {e}"); continue
        for tk in batch:
            try:
                x = (d[tk] if isinstance(d.columns, pd.MultiIndex) else d)["Close"].dropna()
            except KeyError:
                continue
            if len(x):
                x.index = pd.to_datetime(x.index).tz_localize(None)
                out[tk] = x.astype(float)
    return out


def analyze(c: pd.Series, cfg: dict, today: date | None = None) -> dict:
    """Yearly highs, ceilings, the 5-year and all-time highs from a close series (ascending, split-adjusted)."""
    ce = cfg["ceiling"]
    c = c.dropna().sort_index()
    today = today or c.index[-1].date()
    y0 = today.year - ce["lookback_calendar_years"]
    yearly = []
    for y in range(y0, today.year + 1):
        s = c[(c.index.year == y)]
        if not len(s):
            continue
        dt = s.idxmax(); hi = float(s.max())
        after = c[c.index > dt].iloc[:ce["decline_window_sessions"]]
        dec = float(after.min() / hi - 1) if len(after) else 0.0
        yearly.append({"year": y, "date": str(dt.date()), "close": round(hi, 2), "decline": round(dec, 4),
                       "decline_complete": bool(len(after) >= ce["decline_window_sessions"])})
    pairs = []
    for i in range(len(yearly)):
        for j in range(i + 1, len(yearly)):
            a, b = yearly[i], yearly[j]
            if abs(a["close"] - b["close"]) / max(a["close"], b["close"]) > ce["cluster_pct"]:
                continue
            if (date.fromisoformat(b["date"]) - date.fromisoformat(a["date"])).days < ce["min_separation_days"]:
                continue
            if a["decline"] > -ce["decline_pct"] or b["decline"] > -ce["decline_pct"]:
                continue
            pairs.append((a, b))
    # merge pairs that share a yearly high into one ceiling at the cluster's highest level
    clusters: list[dict] = []
    for a, b in pairs:
        hit = next((cl for cl in clusters if a["date"] in cl["dates"] or b["date"] in cl["dates"]), None)
        if hit is None:
            hit = {"dates": set(), "members": []}; clusters.append(hit)
        for m in (a, b):
            if m["date"] not in hit["dates"]:
                hit["dates"].add(m["date"]); hit["members"].append(m)
    ceilings = []
    for cl in clusters:
        mem = sorted(cl["members"], key=lambda m: m["date"])
        level = max(m["close"] for m in mem)
        formed = mem[-1]["date"]                         # the ceiling stands from its latest rejection
        after = c[c.index > pd.Timestamp(formed)]
        above = after[after > level]
        # "caps the state at WATCH until the price closes above the ceiling": a close above it since it formed lifts it
        ceilings.append({"level": level, "formed": formed,
                         "max_close_since_formed": round(float(after.max()), 2) if len(after) else None,
                         "broken": str(above.index[0].date()) if len(above) else None,
                         "pair": [{"date": m["date"], "close": m["close"], "decline": m["decline"]} for m in mem]})
    ceilings.sort(key=lambda x: x["level"])
    last5 = c.iloc[-1260:]
    return {
        "as_of": str(c.index[-1].date()), "history_from": str(c.index[0].date()), "lookback_from_year": y0,
        "yearly_highs": yearly, "ceilings": ceilings,
        "high_5y": {"date": str(last5.idxmax().date()), "close": round(float(last5.max()), 2)},
        "ath": {"date": str(c.idxmax().date()), "close": round(float(c.max()), 2)},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--tickers", default="")
    ap.add_argument("--batch", type=int, default=120)
    ap.add_argument("--max-age-days", type=int, default=7)
    a = ap.parse_args()
    import entry_state as es
    cfg = json.loads(CONFIG.read_text())
    allt, _cards = es.universe_and_cards()
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    names = prev.get("names", {})
    if a.tickers:
        todo = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
    elif a.all:
        todo = list(allt)                                   # every name, regardless of age
    else:
        stale = lambda tk: (tk not in names or not names[tk].get("fetched_at")
                            or date.fromisoformat(names[tk]["fetched_at"][:10]) < date.today() - timedelta(days=a.max_age_days))
        todo = [t for t in allt if stale(t)]
        todo.sort(key=lambda t: (names.get(t) or {}).get("fetched_at") or "")     # never-fetched first, then oldest
        todo = todo[:a.batch]
    log(f"{len(todo)} names to refresh (of {len(allt)})")
    got = fetch_max(todo) if todo else {}
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    for tk, c in got.items():
        try:
            names[tk] = {**analyze(c, cfg), "fetched_at": now}
        except Exception as e:  # noqa: BLE001
            log(f"{tk}: {type(e).__name__}: {e}")
    missing = sorted(set(todo) - set(got))
    keep = {tk: v for tk, v in names.items() if tk in set(allt)}
    payload = {"cadence": "daily", "as_of": max((v.get("as_of") or "") for v in keep.values()) if keep else None,
               "computed_at": now, "order": "Execution Order: Revision of the Entry-State Indicator (6 October 2026), section 3",
               "rule": cfg["ceiling"]["rule"], "lookback_note": cfg["ceiling"]["lookback_note"],
               "prices": "split-adjusted daily closes as charted (yfinance auto_adjust=False, full history)",
               "refreshed_this_run": len(got), "not_fetched": missing, "names": keep}
    OUT.write_text(json.dumps(payload, indent=1))
    n_ceil = sum(1 for v in keep.values() if v.get("ceilings"))
    log(f"{len(keep)} names on record ({len(got)} refreshed, {len(missing)} not fetched); {n_ceil} with at least one ceiling")
    return 0


if __name__ == "__main__":
    sys.exit(main())
