#!/usr/bin/env python3
"""
fetch_sectors.py — the provider's current sector label for every name with bars (third follow-up of 7 October
2026, H3: the sector decomposition of the candidate-list result, DIAGNOSTIC).

Labels come from the canonical fundamentals where the dashboard already holds them (data/canonical/fundamentals.json)
and from the provider's company profile (yfinance Ticker.info: sector, industry) for the rest, at most one request a
second, stored raw and write-once as data/analyst/history/sectors_<date>.parquet (ticker, sector, industry, source).
Today's label is applied to every year by the diagnostic: Alphabet and Meta carry Communication Services also before
the 2018 reclassification (recorded in the diagnostic's output).

Usage:  python scripts/analyst/fetch_sectors.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_panel as bp   # noqa: E402

REPO = HERE.parent.parent
HIST = REPO / "data" / "analyst" / "history"
MIN_INTERVAL_S = 1.0


def log(m: str) -> None:
    print(f"[fetch_sectors] {m}", flush=True)


def main() -> int:
    import yfinance as yf
    names = sorted(set(bp.read_all("monthly_prices", bp.all_stamps())["ticker"]))
    canon = {tk.upper(): v for tk, v in (json.loads((REPO / "data" / "canonical" / "fundamentals.json").read_text()).get("tickers") or {}).items()}
    rows, last, nreq, failed = [], 0.0, 0, []
    for t in names:
        c = canon.get(t) or {}
        if c.get("sector"):
            rows.append({"ticker": t, "sector": c["sector"], "industry": c.get("industry"), "source": "canonical fundamentals"})
            continue
        gap = time.monotonic() - last
        if gap < MIN_INTERVAL_S:
            time.sleep(MIN_INTERVAL_S - gap)
        last = time.monotonic(); nreq += 1
        try:
            info = yf.Ticker(t).info or {}
            rows.append({"ticker": t, "sector": info.get("sector"), "industry": info.get("industry"), "source": "provider profile"})
        except Exception as e:  # noqa: BLE001
            failed.append((t, type(e).__name__)); rows.append({"ticker": t, "sector": None, "industry": None, "source": f"failed: {type(e).__name__}"})
        if nreq % 50 == 0:
            log(f"{nreq} profile requests, {len(rows)} names")
    df = pd.DataFrame(rows)
    today = datetime.now().strftime("%Y-%m-%d"); stamp, k = today, 1
    while (HIST / f"sectors_{stamp}.parquet").exists():
        k += 1; stamp = f"{today}-{k}"
    df.to_parquet(HIST / f"sectors_{stamp}.parquet", index=False)
    (HIST / f"_meta_sectors_{stamp}.json").write_text(json.dumps({"downloaded_on": stamp, "names": len(df), "with_sector": int(df["sector"].notna().sum()),
                                                                 "from_canonical": int((df["source"] == "canonical fundamentals").sum()), "profile_requests": nreq,
                                                                 "failed": failed, "yfinance": yf.__version__, "rate": "at most one request a second"}, indent=1))
    log(f"wrote sectors_{stamp}.parquet: {len(df)} names, {int(df['sector'].notna().sum())} with a sector ({nreq} profile requests, {len(failed)} failed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
