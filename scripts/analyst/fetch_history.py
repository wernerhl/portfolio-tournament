#!/usr/bin/env python3
"""
fetch_history.py — Task B1 of the free-analyst-data order (7 October 2026): the free analyst history that the
price provider already holds, downloaded once for every name and stored raw.

For every ticker in the universe (data/universe.txt: S&P 500 members and the midcaps, plus the held names, the
board, the tiers and the names under review — scripts/entry_state.universe_and_cards):
  - Ticker.upgrades_downgrades        rating changes since 2011/2012: firm, old grade, new grade, action, and the
                                      current and prior price target with the target action
  - Ticker.get_earnings_dates(100)    the last 100 earnings dates (back to 2002 for the oldest names) with the
                                      consensus EPS estimate, the reported EPS and the surprise
  - Ticker.history(period="max")      the daily bars with dividends and splits (auto_adjust=False), kept as the
                                      split table and a month-end table (split-adjusted close, dividend-adjusted
                                      close, 20-session average dollar volume); the daily bars themselves stay out
                                      of the repository for size (data/source/prices_daily.parquet is the served
                                      close store). The splits convert the nominal price targets of the past to
                                      today's share basis, and dollar volume uses split-adjusted prices only.

Rate: at most one request per second to the provider (a global throttle across the three calls), one retry per
ticker after a pause. Every file is written once, with the download date in its name; a second download on the
same date gets a run suffix (-2, -3). Nothing here is ever rewritten.

Outputs (data/analyst/history/):
  upgrades_downgrades_<date>.parquet   ticker, grade_date_utc, firm, to_grade, from_grade, action, pt_action,
                                       pt_current, pt_prior
  earnings_dates_<date>.parquet        ticker, earnings_date_et (naive, America/New_York), eps_estimate,
                                       reported_eps, surprise_pct
  splits_<date>.parquet                ticker, date, ratio
  monthly_prices_<date>.parquet        ticker, month_end, close (split-adjusted), adj_close (dividend-adjusted),
                                       dollar_volume_20 (mean of close x volume over the last 20 sessions),
                                       sessions, first_bar
  _meta_<date>.json                    versions, universe, counts, failures with reasons, timing, request count

Usage:  python scripts/analyst/fetch_history.py [--tickers MU,LMT] [--out data/analyst/history]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
REPO = HERE.parent.parent
DATA = REPO / "data"
OUT = DATA / "analyst" / "history"
MIN_INTERVAL_S = 1.0          # the provider sees at most one request per second
warnings.filterwarnings("ignore")


def log(m: str) -> None:
    print(f"[fetch_history] {m}", flush=True)


class Throttle:
    """One request per second across every provider call of this process."""
    def __init__(self, interval: float = MIN_INTERVAL_S):
        self.interval, self.last, self.n = interval, 0.0, 0

    def wait(self) -> None:
        gap = time.monotonic() - self.last
        if gap < self.interval:
            time.sleep(self.interval - gap)
        self.last = time.monotonic(); self.n += 1


def universe(tickers_arg: str | None) -> list[str]:
    if tickers_arg:
        return [t.strip().upper() for t in tickers_arg.split(",") if t.strip()]
    import entry_state as es
    allt, _cards = es.universe_and_cards()
    return allt


def ratings_frame(tk: str, df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or not len(df):
        return pd.DataFrame()
    out = pd.DataFrame({
        "ticker": tk,
        "grade_date_utc": pd.to_datetime(df.index).tz_localize(None) if getattr(df.index, "tz", None) is None else pd.to_datetime(df.index).tz_convert("UTC").tz_localize(None),
        "firm": df.get("Firm", pd.Series(index=df.index, dtype=object)).astype(object).values,
        "to_grade": df.get("ToGrade", pd.Series(index=df.index, dtype=object)).astype(object).values,
        "from_grade": df.get("FromGrade", pd.Series(index=df.index, dtype=object)).astype(object).values,
        "action": df.get("Action", pd.Series(index=df.index, dtype=object)).astype(object).values,
        "pt_action": df.get("priceTargetAction", pd.Series(index=df.index, dtype=object)).astype(object).values,
        "pt_current": pd.to_numeric(df.get("currentPriceTarget", pd.Series(index=df.index, dtype=float)), errors="coerce").values,
        "pt_prior": pd.to_numeric(df.get("priorPriceTarget", pd.Series(index=df.index, dtype=float)), errors="coerce").values,
    })
    return out.sort_values("grade_date_utc").reset_index(drop=True)


def earnings_frame(tk: str, df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or not len(df):
        return pd.DataFrame()
    idx = pd.to_datetime(df.index)
    idx = idx.tz_convert("America/New_York").tz_localize(None) if idx.tz is not None else idx
    out = pd.DataFrame({
        "ticker": tk, "earnings_date_et": idx,
        "eps_estimate": pd.to_numeric(df.get("EPS Estimate"), errors="coerce").values,
        "reported_eps": pd.to_numeric(df.get("Reported EPS"), errors="coerce").values,
        "surprise_pct": pd.to_numeric(df.get("Surprise(%)"), errors="coerce").values,
    })
    return out.sort_values("earnings_date_et").reset_index(drop=True)


def history_frames(tk: str, h: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    if h is None or not len(h):
        return pd.DataFrame(), pd.DataFrame()
    h = h.copy()
    h.index = pd.to_datetime(h.index).tz_localize(None) if getattr(h.index, "tz", None) is not None else pd.to_datetime(h.index)
    h = h[~h.index.duplicated(keep="last")].sort_index()
    sp = h["Stock Splits"] if "Stock Splits" in h.columns else pd.Series(dtype=float)
    splits = pd.DataFrame({"ticker": tk, "date": sp[sp > 0].index, "ratio": sp[sp > 0].values}) if len(sp) else pd.DataFrame()
    close = pd.to_numeric(h["Close"], errors="coerce")
    adj = pd.to_numeric(h["Adj Close"], errors="coerce") if "Adj Close" in h.columns else close
    vol = pd.to_numeric(h["Volume"], errors="coerce")
    dv20 = (close * vol).rolling(20, min_periods=10).mean()
    me = h.groupby(h.index.to_period("M")).tail(1).index          # the last bar of each calendar month
    monthly = pd.DataFrame({
        "ticker": tk, "month_end": me,
        "close": close.loc[me].values, "adj_close": adj.loc[me].values, "dollar_volume_20": dv20.loc[me].values,
        "sessions": h.groupby(h.index.to_period("M")).size().values,
        "first_bar": h.index.min(),
    })
    return splits, monthly


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default=None)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--daily-dump", default=None, help="optional parquet of the daily bars (kept outside the repository)")
    a = ap.parse_args()
    import yfinance as yf
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    stamp, k = today, 1
    while any((out / f"{n}_{stamp}.parquet").exists() for n in ("upgrades_downgrades", "earnings_dates", "splits", "monthly_prices")) or (out / f"_meta_{stamp}.json").exists():
        k += 1; stamp = f"{today}-{k}"                           # never rewrite: a second download of the day gets a suffix
    tickers = universe(a.tickers)
    log(f"{len(tickers)} tickers; files stamped {stamp}; one request per second")
    th = Throttle()
    R, E, S, M, D = [], [], [], [], []
    failed: dict[str, str] = {}
    counts = {"ratings": 0, "earnings": 0, "history": 0}
    t0 = time.time()
    for i, tk in enumerate(tickers, 1):
        t = yf.Ticker(tk)
        for attempt in (1, 2):
            errs = []
            try:
                th.wait(); r = ratings_frame(tk, t.upgrades_downgrades)
                if len(r): R.append(r); counts["ratings"] += 1
            except Exception as e:  # noqa: BLE001
                msg = f"{type(e).__name__}: {str(e)[:120]}"
                if "No upgrade/downgrade history" not in msg:
                    errs.append("ratings " + msg)
            try:
                th.wait(); e_ = earnings_frame(tk, t.get_earnings_dates(limit=100))
                if len(e_): E.append(e_); counts["earnings"] += 1
            except Exception as e:  # noqa: BLE001
                errs.append(f"earnings {type(e).__name__}: {str(e)[:120]}")
            try:
                th.wait(); h = t.history(period="max", auto_adjust=False, actions=True)
                s_, m_ = history_frames(tk, h)
                if len(m_):
                    M.append(m_); counts["history"] += 1
                    if len(s_): S.append(s_)
                    if a.daily_dump:
                        hh = h.copy(); hh["ticker"] = tk; D.append(hh[["ticker", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]])
            except Exception as e:  # noqa: BLE001
                errs.append(f"history {type(e).__name__}: {str(e)[:120]}")
            if not errs:
                break
            if attempt == 1:
                time.sleep(5.0)
            else:
                failed[tk] = "; ".join(errs)
        if i % 25 == 0 or i == len(tickers):
            log(f"{i}/{len(tickers)} · ratings {counts['ratings']} · earnings {counts['earnings']} · history {counts['history']} · "
                f"failed {len(failed)} · {th.n} requests in {time.time() - t0:.0f}s")
    frames = {"upgrades_downgrades": R, "earnings_dates": E, "splits": S, "monthly_prices": M}
    written = {}
    for name, lst in frames.items():
        df = pd.concat(lst, ignore_index=True) if lst else pd.DataFrame()
        p = out / f"{name}_{stamp}.parquet"
        df.to_parquet(p, index=False)
        written[name] = {"file": p.name, "rows": int(len(df)), "tickers": int(df["ticker"].nunique()) if len(df) else 0}
    if a.daily_dump and D:
        dd = pd.concat(D); dd.index.name = "date"; dd.to_parquet(a.daily_dump)
    meta = {
        "task": "B1 of the free-analyst-data order (7 October 2026): the provider's free analyst history, stored raw, never rewritten",
        "downloaded_on": stamp, "started_at": datetime.fromtimestamp(t0).astimezone().isoformat(timespec="seconds"),
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"), "elapsed_s": round(time.time() - t0),
        "provider": "yfinance", "yfinance_version": yf.__version__, "pandas_version": pd.__version__,
        "calls": {"upgrades_downgrades": "Ticker.upgrades_downgrades", "earnings_dates": "Ticker.get_earnings_dates(limit=100)",
                  "history": "Ticker.history(period='max', auto_adjust=False, actions=True) -> splits + month-end table"},
        "rate": "at most one request per second (global throttle)", "requests": th.n,
        "universe": {"n": len(tickers), "source": "scripts/entry_state.universe_and_cards (data/universe.txt + held + board + tiers + review)"},
        "written": written, "counts": counts, "failed": failed,
        "timestamps": {"grade_date_utc": "naive UTC (the provider's epochGradeDate)", "earnings_date_et": "naive America/New_York",
                       "month_end": "the last bar of each calendar month"},
    }
    (out / f"_meta_{stamp}.json").write_text(json.dumps(meta, indent=1, default=str))
    log(f"done: {written} · failed {len(failed)} {list(failed)[:8]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
