#!/usr/bin/env python3
"""
snapshot_estimates.py — the nightly snapshot of current analyst estimates (free-analyst-data order, 7 October
2026, task C). Consensus estimates have no free dated history; from today the repository owns one.

For every ticker in the universe (data/universe.txt plus the held, board, tier and review names), the provider's
current analysis tables — eps_trend (consensus EPS now and 7, 30, 60, 90 days ago), eps_revisions (up and down
revision counts over 7 and 30 days), earnings_estimate and revenue_estimate (mean, low, high, number of analysts,
year-ago value, growth) for the current and next quarter and the current and next fiscal year; recommendations
(the counts by rating over the last four months); analyst_price_targets (current price, low, high, mean, median).

One file per session: data/analyst/snapshots/YYYY-MM-DD.json, keyed by the session the nightly publishes
(PUBLISH_SESSION, else the last completed session), compact JSON, IMMUTABLE. One writer per day, the options
snapshot's guard (order 5-Oct-2026, 2.2): with --check-origin, `git fetch origin main` first and exit "already
written" if origin/main holds the day's file; the local file is never rewritten; the pull goes to a temporary
file and is moved into place once complete. The nightly's commit step keeps origin's version on a conflict, so
the first writer wins there too.

Rate: at most one request per second to the provider. The three module groups are fetched in one quoteSummary
request per name where the installed yfinance exposes that path (earningsTrend, recommendationTrend,
financialData), else through the public properties (three requests per name); the file records which.

The first snapshot (no earlier file) is flagged first_run: its 7-, 30-, 60- and 90-day-ago consensus values are
one extra dated observation per horizon in the derived history (scripts/analyst/build_revisions.py), marked
provider-reported; every later file contributes its current values as observed.

Outcome (stdout, and outcome= in $GITHUB_OUTPUT): written | already_written | provider_error | market_closed.

Usage:  python scripts/analyst/snapshot_estimates.py [--check-origin] [--tickers MU,LMT] [--session YYYY-MM-DD]
                                                      [--min-coverage 0.5] [--out data/analyst/snapshots]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
REPO = HERE.parent.parent
DATA = REPO / "data"
SNAPS = DATA / "analyst" / "snapshots"
MIN_INTERVAL_S = 1.0
PERIODS = ("0q", "+1q", "0y", "+1y")
warnings.filterwarnings("ignore")


def log(m: str) -> None:
    print(f"[snapshot_estimates] {m}", flush=True)


def set_outcome(outcome: str, note: str) -> None:
    log(f"outcome={outcome}: {note}")
    p = os.environ.get("GITHUB_OUTPUT")
    if p:
        with open(p, "a") as fh:
            fh.write(f"outcome={outcome}\n")


class Throttle:
    def __init__(self, interval: float = MIN_INTERVAL_S):
        self.interval, self.last, self.n = interval, 0.0, 0

    def wait(self) -> None:
        gap = time.monotonic() - self.last
        if gap < self.interval:
            time.sleep(self.interval - gap)
        self.last = time.monotonic(); self.n += 1


def _num(v):
    """A plain number or None (the provider's formatted dicts, NaN and strings never reach the file)."""
    if isinstance(v, dict):
        v = v.get("raw")
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return int(x) if x.is_integer() and abs(x) < 1e12 else round(x, 6)


# ── the combined fetch (one request) ─────────────────────────────────────────────────────────
def fetch_combined(t) -> dict | None:
    """The raw quoteSummary result for the three modules, through yfinance's own fetcher (crumb and cookie
    handled there). None when this yfinance has no such path."""
    an = getattr(t, "_analysis", None)
    f = getattr(an, "_fetch", None)
    if f is None:
        return None
    res = f(["earningsTrend", "recommendationTrend", "financialData"])
    if not res:
        raise RuntimeError("empty quoteSummary response")
    try:
        r0 = res["quoteSummary"]["result"][0]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"unexpected quoteSummary shape: {type(e).__name__}") from e
    return r0


def from_combined(r0: dict) -> dict:
    periods = {}
    for tr in ((r0.get("earningsTrend") or {}).get("trend") or []):
        p = tr.get("period")
        if p not in PERIODS:
            continue
        ee, re_, et, er = tr.get("earningsEstimate") or {}, tr.get("revenueEstimate") or {}, tr.get("epsTrend") or {}, tr.get("epsRevisions") or {}
        periods[p] = {
            "end": tr.get("endDate"),
            "eps": {"current": _num(et.get("current")), "d7": _num(et.get("7daysAgo")), "d30": _num(et.get("30daysAgo")),
                    "d60": _num(et.get("60daysAgo")), "d90": _num(et.get("90daysAgo"))},
            "rev": {"up7": _num(er.get("upLast7days")), "up30": _num(er.get("upLast30days")),
                    "down30": _num(er.get("downLast30days")), "down7": _num(er.get("downLast7Days"))},
            "eps_est": {"avg": _num(ee.get("avg")), "low": _num(ee.get("low")), "high": _num(ee.get("high")),
                        "n": _num(ee.get("numberOfAnalysts")), "year_ago": _num(ee.get("yearAgoEps")), "growth": _num(ee.get("growth"))},
            "rev_est": {"avg": _num(re_.get("avg")), "low": _num(re_.get("low")), "high": _num(re_.get("high")),
                        "n": _num(re_.get("numberOfAnalysts")), "year_ago": _num(re_.get("yearAgoRevenue")), "growth": _num(re_.get("growth"))},
        }
    recs = [{"period": x.get("period"), "strongBuy": _num(x.get("strongBuy")), "buy": _num(x.get("buy")), "hold": _num(x.get("hold")),
             "sell": _num(x.get("sell")), "strongSell": _num(x.get("strongSell"))}
            for x in ((r0.get("recommendationTrend") or {}).get("trend") or [])]
    fd = r0.get("financialData") or {}
    targets = {"current": _num(fd.get("currentPrice")), "low": _num(fd.get("targetLowPrice")), "high": _num(fd.get("targetHighPrice")),
               "mean": _num(fd.get("targetMeanPrice")), "median": _num(fd.get("targetMedianPrice")),
               "n_opinions": _num(fd.get("numberOfAnalystOpinions")), "rec_mean": _num(fd.get("recommendationMean")),
               "rec_key": fd.get("recommendationKey")}
    return {"periods": periods, "recommendations": recs, "targets": targets}


# ── the public-property fallback (three requests) ───────────────────────────────────────────
def from_properties(t, th: Throttle) -> dict:
    import pandas as pd

    def row(df, p):
        return df.loc[p] if df is not None and len(df) and p in df.index else pd.Series(dtype=object)

    th.wait(); et = t.eps_trend                     # eps_trend, eps_revisions, earnings_estimate, revenue_estimate share one fetch
    er, ee, re_ = t.eps_revisions, t.earnings_estimate, t.revenue_estimate
    periods = {}
    for p in PERIODS:
        a, b, c, d = row(et, p), row(er, p), row(ee, p), row(re_, p)
        if not len(a) and not len(c):
            continue
        periods[p] = {
            "end": None,
            "eps": {"current": _num(a.get("current")), "d7": _num(a.get("7daysAgo")), "d30": _num(a.get("30daysAgo")),
                    "d60": _num(a.get("60daysAgo")), "d90": _num(a.get("90daysAgo"))},
            "rev": {"up7": _num(b.get("upLast7days")), "up30": _num(b.get("upLast30days")),
                    "down30": _num(b.get("downLast30days")), "down7": _num(b.get("downLast7Days"))},
            "eps_est": {"avg": _num(c.get("avg")), "low": _num(c.get("low")), "high": _num(c.get("high")),
                        "n": _num(c.get("numberOfAnalysts")), "year_ago": _num(c.get("yearAgoEps")), "growth": _num(c.get("growth"))},
            "rev_est": {"avg": _num(d.get("avg")), "low": _num(d.get("low")), "high": _num(d.get("high")),
                        "n": _num(d.get("numberOfAnalysts")), "year_ago": _num(d.get("yearAgoRevenue")), "growth": _num(d.get("growth"))},
        }
    th.wait(); rc = t.recommendations
    recs = []
    if rc is not None and len(rc):
        for _, x in rc.iterrows():
            recs.append({"period": x.get("period"), "strongBuy": _num(x.get("strongBuy")), "buy": _num(x.get("buy")),
                         "hold": _num(x.get("hold")), "sell": _num(x.get("sell")), "strongSell": _num(x.get("strongSell"))})
    th.wait(); pt = t.analyst_price_targets or {}
    targets = {"current": _num(pt.get("current")), "low": _num(pt.get("low")), "high": _num(pt.get("high")),
               "mean": _num(pt.get("mean")), "median": _num(pt.get("median")), "n_opinions": None, "rec_mean": None, "rec_key": None}
    return {"periods": periods, "recommendations": recs, "targets": targets}


def usable(rec: dict) -> bool:
    """A record counts as captured when at least one period carries a consensus EPS or an estimate count."""
    for p in rec.get("periods", {}).values():
        if (p.get("eps") or {}).get("current") is not None or (p.get("eps_est") or {}).get("n"):
            return True
    return bool((rec.get("targets") or {}).get("mean"))


# ── git (the one-writer guard) ───────────────────────────────────────────────────────────────
def git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


def origin_has(session: str) -> bool:
    return git("cat-file", "-e", f"origin/main:data/analyst/snapshots/{session}.json").returncode == 0


def universe(tickers_arg: str | None) -> list[str]:
    if tickers_arg:
        return [t.strip().upper() for t in tickers_arg.split(",") if t.strip()]
    import entry_state as es
    allt, _ = es.universe_and_cards()
    return allt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-origin", action="store_true", help="fetch origin/main and refuse to write a session it already holds")
    ap.add_argument("--tickers", default=None)
    ap.add_argument("--session", default=None)
    ap.add_argument("--min-coverage", type=float, default=0.5, help="below this share of the universe nothing is written (a later run may capture the day)")
    ap.add_argument("--out", default=str(SNAPS))
    a = ap.parse_args()
    from trading_calendar import last_completed_session, now_et
    import yfinance as yf
    out = Path(a.out)
    now = now_et()
    session = a.session or os.environ.get("PUBLISH_SESSION") or last_completed_session(now)
    path = out / f"{session}.json"
    if path.exists():
        set_outcome("already_written", f"{path.relative_to(REPO) if path.is_relative_to(REPO) else path} exists; immutable, nothing fetched"); return 0
    if a.check_origin:
        git("fetch", "-q", "origin", "main")
        if origin_has(session):
            set_outcome("already_written", f"the {session} snapshot is already on origin/main; nothing fetched"); return 0
    tickers = universe(a.tickers)
    earlier = sorted(p.name[:10] for p in out.glob("20??-??-??.json")) if out.exists() else []
    first_run = not earlier
    th = Throttle()
    names, failed, modes = {}, {}, {"combined": 0, "properties": 0}
    t0 = time.time()
    for i, tk in enumerate(tickers, 1):
        t = yf.Ticker(tk)
        rec, err = None, None
        for attempt in (1, 2):
            try:
                th.wait()
                r0 = fetch_combined(t)
                if r0 is not None:
                    rec = from_combined(r0); modes["combined"] += 1
                else:
                    rec = from_properties(t, th); modes["properties"] += 1
                err = None
                break
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {str(e)[:120]}"
                if attempt == 1:
                    try:                                  # the public path as the second attempt
                        rec = from_properties(t, th); modes["properties"] += 1; err = None; break
                    except Exception as e2:  # noqa: BLE001
                        err = f"{err}; properties {type(e2).__name__}: {str(e2)[:80]}"
                        time.sleep(3.0)
        if rec is not None and usable(rec):
            names[tk] = rec
        else:
            failed[tk] = err or "no analysis data for this name"
        if i % 50 == 0 or i == len(tickers):
            log(f"{i}/{len(tickers)} · captured {len(names)} · failed {len(failed)} · {th.n} requests in {time.time() - t0:.0f}s")
    coverage = len(names) / len(tickers) if tickers else 0.0
    if coverage < a.min_coverage:
        set_outcome("provider_error", f"only {len(names)} of {len(tickers)} names captured ({coverage:.0%} < {a.min_coverage:.0%}); nothing written")
        return 2
    payload = {
        "session": session, "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "order": "free-analyst-data order (7 October 2026), task C: nightly snapshot of current estimates",
        "immutable": True, "first_run": first_run,
        "first_run_note": ("the 7-, 30-, 60- and 90-day-ago consensus values of this first file are one extra dated observation per "
                           "horizon in the derived history, marked provider-reported" if first_run else None),
        "provider": "yfinance", "yfinance_version": yf.__version__, "fetch_mode": modes, "requests": th.n,
        "elapsed_s": round(time.time() - t0), "rate": "at most one request per second",
        "universe": {"n": len(tickers), "source": "scripts/entry_state.universe_and_cards"},
        "captured": len(names), "coverage": round(coverage, 4), "failed": failed,
        "fields": {"periods": "0q current quarter, +1q next quarter, 0y current fiscal year, +1y next fiscal year; end = the period's end date",
                   "eps": "consensus EPS now (current) and 7/30/60/90 days ago as the provider reports them (d7, d30, d60, d90)",
                   "rev": "number of analysts revising up or down over the last 7 and 30 days",
                   "eps_est / rev_est": "mean, low, high, number of analysts (n), the year-ago value and the implied growth",
                   "recommendations": "counts by rating for the current month (0m) and the three before",
                   "targets": "current price and the low, high, mean and median price targets; n_opinions and rec_mean where the combined fetch supplies them"},
        "names": names,
    }
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / f".incoming-{session}.json.tmp"
    body = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    tmp.write_text(body)
    if path.exists():                                     # written by another process meanwhile: never overwrite
        tmp.unlink(); set_outcome("already_written", f"{path.name} appeared while pulling; the pull is discarded"); return 0
    os.replace(tmp, path)
    sha = hashlib.sha256(body.encode()).hexdigest()
    set_outcome("written", f"{path.name}: {len(names)} of {len(tickers)} names ({coverage:.1%}), {len(body) // 1024} KB, sha256 {sha[:12]}, "
                           f"mode {modes}, {th.n} requests in {time.time() - t0:.0f}s{' (first run)' if first_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
