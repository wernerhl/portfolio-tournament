"""Canonical market-data artifact (#92 / remediation plan 4.1).

ONE fundamentals fetch for both repositories. The screener consumes
data/canonical/fundamentals.json + data/source/prices_daily.parquet from this
repo (both public) instead of running its own 535-name yfinance fetch — the
double-fetch is what produced the 2026-07-29 incident (Yahoo rate-limited the
screener's runner, 113/535 names lost, publish correctly rejected).

Contract:
- Universe: data/canonical/universe.txt (committed; union of tournament
  universe, screener universe/midcaps, and the book).
- Range checks applied ONCE at source: out-of-range values become null and
  carry a flag; consumers keep their own checks as defense in depth.
- provenance carries session_date (from the freshly refreshed prices parquet),
  built_at, coverage, and the failed-ticker list — consumers enforce
  freshness/coverage on their side and fall back to direct fetch loudly.
- Best-effort in update_daily: a canonical failure must never block the
  tournament's own outputs; the screener's freshness assert catches staleness.

Fields include totalDebt/totalCash/ebitda/operatingCashflow ahead of the
leverage module (#93) so it lands on data already flowing.
"""
from __future__ import annotations
import json, sys, time
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

REPO = Path(__file__).resolve().parent.parent
CANON = REPO / "data" / "canonical"
CANON.mkdir(parents=True, exist_ok=True)

FIELDS = [
    "marketCap", "forwardPE", "trailingPE", "priceToBook", "revenueGrowth",
    "grossMargins", "operatingMargins", "profitMargins", "returnOnEquity",
    "returnOnAssets", "debtToEquity", "freeCashflow", "totalRevenue",
    "earningsGrowth", "currentPrice", "fiftyDayAverage", "twoHundredDayAverage",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "sector", "industry", "shortName",
    "beta", "dividendYield",
    # ahead of the leverage module (#93):
    "totalDebt", "totalCash", "ebitda", "operatingCashflow",
]


def range_check(tk: str, rec: dict) -> list[str]:
    """Null out-of-range values at the source; return flags. Bounds mirror the
    screener's [2] checks so the class of bug dies here, once."""
    flags = []
    pe = rec.get("forwardPE")
    if pe is not None and not (3.0 <= pe <= 150.0):
        flags.append(f"fwd_pe_out_of_range({round(pe,1)})")
        rec["forwardPE"] = None
    for m in ("grossMargins", "operatingMargins", "profitMargins"):
        v = rec.get(m)
        if v is not None and not (-2.0 <= v <= 2.0):
            flags.append(f"{m}_out_of_range({round(v,2)})")
            rec[m] = None
    dte = rec.get("debtToEquity")
    if dte is not None and not (0.0 <= dte <= 2000.0):
        flags.append(f"debtToEquity_out_of_range({round(dte,1)})")
        rec["debtToEquity"] = None
    return flags


def fetch_one(tk: str) -> dict | None:
    """Per-name fallback ladder (2026-08-06): Yahoo's quoteSummary endpoint
    (.info) broke server-side for a growing symbol shard — 3 names on 07-29,
    73 by 08-05, megacaps included (MU, AMD, JPM, PG). fast_info is a
    DIFFERENT endpoint and stayed healthy. Ladder:
      1. .info with marketCap            -> full record
      2. .info partial (no marketCap)    -> merge fast_info mcap/price, flag 'fundamentals_partial'
      3. .info dead, fast_info alive     -> minimal record, flag 'fundamentals_degraded'
      4. both dead                       -> None (genuinely unreachable)
    Degraded names stay SCORED downstream (missing fields hit the same
    neutral defaults as any absent metric) instead of vanishing and tripping
    the named-seven publish block — availability without silent substitution:
    every partial record carries its flag and provenance counts them."""
    info = {}
    try:
        info = yf.Ticker(tk).info or {}
    except Exception:
        info = {}

    rec = {f: info.get(f) for f in FIELDS}
    rec["currentPrice"] = info.get("currentPrice") or info.get("regularMarketPrice")
    ladder_flag = None

    if not info.get("marketCap"):
        try:
            fi = yf.Ticker(tk).fast_info
            mcap = fi.get("marketCap") if hasattr(fi, "get") else getattr(fi, "market_cap", None)
            if mcap is None and hasattr(fi, "get"):
                mcap = fi.get("market_cap")
            px = (fi.get("lastPrice") if hasattr(fi, "get") else None) or \
                 (fi.get("last_price") if hasattr(fi, "get") else None)
            if mcap:
                rec["marketCap"] = float(mcap)
                if rec.get("currentPrice") is None and px:
                    rec["currentPrice"] = float(px)
                ladder_flag = ("fundamentals_partial" if any(
                    info.get(k) is not None for k in ("grossMargins", "forwardPE", "revenueGrowth"))
                    else "fundamentals_degraded")
        except Exception:
            pass

    if not rec.get("marketCap"):
        return None

    # String fields are '' not None — yfinance omits them for some names,
    # and downstream .lower()/slicing must never see None.
    for s in ("sector", "industry", "shortName"):
        rec[s] = rec.get(s) or ("" if s != "shortName" else tk)
    rec["flags"] = range_check(tk, rec)
    if ladder_flag:
        rec["flags"].append(ladder_flag)
    return rec


def fetch(tickers: list[str], retry_pass: bool = False) -> tuple[dict, list[str]]:
    out, failed = {}, []
    for i, tk in enumerate(tickers):
        if i % 50 == 0 and i > 0 and not retry_pass:
            print(f"    ... {i}/{len(tickers)} ({len(failed)} failed)")
            time.sleep(2)
        if retry_pass:
            time.sleep(4)
        rec = fetch_one(tk)
        if rec is None:
            failed.append(tk)
        else:
            out[tk] = rec
    return out, failed


def main() -> int:
    uni_file = CANON / "universe.txt"
    if not uni_file.exists():
        print("ERROR: data/canonical/universe.txt missing")
        return 1
    universe = sorted({t.strip() for t in uni_file.read_text().split() if t.strip()})
    print(f"Canonical build: {len(universe)} tickers")

    prices = pd.read_parquet(REPO / "data" / "source" / "prices_daily.parquet")
    prices.index = pd.to_datetime(prices.index)
    session_date = str(prices.index[-1].date())

    recs, failed = fetch(universe)
    if failed:
        print(f"  Retry pass for {len(failed)} (30s backoff)...")
        time.sleep(30)
        rec2, failed = fetch(failed, retry_pass=True)
        recs.update(rec2)

    n_flags = sum(len(r["flags"]) for r in recs.values())
    n_partial = sum(1 for r in recs.values()
                    if any(f in ("fundamentals_partial", "fundamentals_degraded")
                           for f in r["flags"]))
    coverage = 100.0 * len(recs) / len(universe)
    provenance = {
        "n_partial_or_degraded": n_partial,
        "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "session_date": session_date,
        "source": "yfinance",
        "n_requested": len(universe),
        "n_ok": len(recs),
        "coverage_pct": round(coverage, 1),
        "failed": sorted(failed),
        "flags_count": n_flags,
        "prices_ref": "data/source/prices_daily.parquet",
        "prices_last_date": session_date,
        "prices_n_tickers": int(prices.shape[1]),
    }
    with open(CANON / "fundamentals.json", "w") as f:
        json.dump({"provenance": provenance, "tickers": recs}, f,
                  separators=(",", ":"), allow_nan=False, default=lambda o: None)

    print(f"  canonical: {len(recs)}/{len(universe)} ok ({coverage:.1f}%), "
          f"{n_flags} range flags, session {session_date}, failed: {sorted(failed)[:8]}")
    if coverage < 60.0:
        print("ERROR: canonical coverage < 60% — refusing to overwrite a good artifact")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
