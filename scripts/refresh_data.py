"""
Targeted data refresh — re-fetches just the parquet files needed to extend the
tournament backtest. Skips Phase 1's quarterly + technicals + fundamentals
(those don't materially change in a few days and aren't read by backtest.py).

Updates in place in data/source/:
  prices_daily.parquet      — extends history through latest available date
  returns_daily.parquet     — recomputed from prices
  fred_indicators.parquet   — refreshes the 22 FRED series
  vol_indicators.parquet    — refreshes 12 vol/macro Yahoo series
  vol_derived.parquet       — recomputed from vol_indicators
  sector_etfs.parquet       — refreshes 17 sector/style ETFs

Usage:
  export FRED_API_KEY=...
  python scripts/refresh_data.py
"""
from __future__ import annotations
import os, sys, time, warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

REPO   = Path(__file__).resolve().parent.parent
SOURCE = REPO / "data" / "source"

T0 = time.time()
def log(msg): print(f"[{time.time()-T0:6.1f}s] {msg}", flush=True)


def download_close(tickers, start, end=None) -> pd.DataFrame:
    """Returns DataFrame of close prices, columns=tickers, index=date."""
    end = end or datetime.now()
    out = {}
    BATCH = 50
    failed = []
    for i in range(0, len(tickers), BATCH):
        batch = tickers[i:i+BATCH]
        try:
            data = yf.download(batch, start=start, end=end, progress=False, auto_adjust=True, threads=True)
            if data is None or data.empty: continue
            closes = data["Close"]
            if isinstance(closes, pd.Series):
                out[batch[0]] = closes
            else:
                for t in closes.columns:
                    s = closes[t].dropna()
                    if not s.empty: out[t] = s
        except Exception as e:
            failed.extend(batch)
            log(f"  warn batch {i}: {e}")
    if failed:
        log(f"  {len(failed)} tickers failed: {failed[:10]}...")
    return pd.DataFrame(out)


def main():
    # ---- PRICES (universe from existing prices_daily) ----
    log("loading existing universe...")
    existing = pd.read_parquet(SOURCE / "prices_daily.parquet")
    if "SPY_volume" in existing.columns:
        spy_vol_old = existing["SPY_volume"]
        existing = existing.drop(columns=["SPY_volume"])
    else:
        spy_vol_old = None
    existing.index = pd.to_datetime(existing.index)
    universe = list(existing.columns)
    last_existing = existing.index.max()
    log(f"  {len(universe)} tickers, existing last date {last_existing.date()}")

    # Fetch from a buffer before last_existing to allow merge alignment
    fetch_start = (last_existing - timedelta(days=10)).strftime("%Y-%m-%d")
    log(f"fetching prices from {fetch_start} for {len(universe)} tickers...")
    new = download_close(universe, fetch_start)
    log(f"  fetched {new.shape}")
    new.index = pd.to_datetime(new.index)

    # Merge: existing rows + new rows for dates AFTER last_existing,
    # plus overwrite the recent overlap (in case there were stale values)
    cutoff = last_existing  # keep existing up through here, new after
    merged = pd.concat([
        existing.loc[existing.index <= cutoff],
        new.loc[new.index > cutoff].reindex(columns=universe),
    ])
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    new_last = merged.index.max()
    log(f"  merged: {merged.shape}, new last date {new_last.date()}")

    # Save prices
    if spy_vol_old is not None:
        merged["SPY_volume"] = spy_vol_old.reindex(merged.index).ffill()
    merged.to_parquet(SOURCE / "prices_daily.parquet")
    log(f"  saved prices_daily.parquet")

    # Returns
    if "SPY_volume" in merged.columns:
        merged_no_vol = merged.drop(columns=["SPY_volume"])
    else:
        merged_no_vol = merged
    returns = merged_no_vol.pct_change()
    returns.to_parquet(SOURCE / "returns_daily.parquet")
    log(f"  saved returns_daily.parquet")

    # ---- VOL / MACRO ----
    log("fetching vol/macro series...")
    vol_tickers = {
        "vix":  "^VIX",  "vvix": "^VVIX", "vix3m": "^VIX3M", "vix1d": "^VIX1D",
        "skew": "^SKEW", "spx":  "^GSPC", "dxy":  "DX-Y.NYB",
        "oil":  "CL=F",  "gold": "GC=F",  "tlt":  "TLT",
        "hyg":  "HYG",   "lqd":  "LQD",
    }
    vol_data = {}
    for name, tk in vol_tickers.items():
        try:
            df = yf.download(tk, start="2005-01-01", progress=False, auto_adjust=True)
            if df is not None and len(df) > 0:
                c = df["Close"]
                if isinstance(c, pd.DataFrame): c = c.iloc[:, 0]
                vol_data[name] = c
        except Exception as e:
            log(f"  warn {name}: {e}")
    vol_df = pd.DataFrame(vol_data)
    vol_df.to_parquet(SOURCE / "vol_indicators.parquet")
    log(f"  saved vol_indicators.parquet ({vol_df.shape})")

    # vol_derived
    log("computing vol_derived...")
    vd = pd.DataFrame(index=vol_df.index)
    if "vvix" in vol_df and "vix" in vol_df:
        vd["vvix_vix"] = vol_df["vvix"] / vol_df["vix"]
    if "vix3m" in vol_df and "vix" in vol_df:
        vd["vix_term"] = vol_df["vix"] - vol_df["vix3m"]   # negative = backwardation = stress
    if "oil" in vol_df:
        vd["oil_60d_vel"] = vol_df["oil"].pct_change(60) * 100
        vd["oil_20d_vel"] = vol_df["oil"].pct_change(20) * 100
    if "spx" in vol_df:
        spx = vol_df["spx"]
        vd["spx_drawdown"]        = (spx / spx.cummax() - 1) * 100
        vd["spx_return_20d"]      = spx.pct_change(20) * 100
        vd["spx_return_60d"]      = spx.pct_change(60) * 100
        vd["spx_realized_vol_20d"] = spx.pct_change().rolling(20).std() * np.sqrt(252) * 100
    if "hyg" in vol_df and "lqd" in vol_df:
        vd["hyg_lqd_ratio"] = vol_df["hyg"] / vol_df["lqd"]
    if "gold" in vol_df and "spx" in vol_df:
        vd["gold_spx"] = vol_df["gold"] / vol_df["spx"]
    if "tlt" in vol_df and "spx" in vol_df:
        vd["tlt_spx"] = vol_df["tlt"] / vol_df["spx"]
    vd.to_parquet(SOURCE / "vol_derived.parquet")
    log(f"  saved vol_derived.parquet ({vd.shape})")

    # ---- SECTOR ETFs ----
    log("fetching sector ETFs...")
    sector_tickers = ["XLB","XLC","XLE","XLF","XLI","XLK","XLP","XLRE","XLU","XLV","XLY",
                      "SPY","QQQ","DIA","IWM","SMH","SOXX"]
    sect_data = {}
    for tk in sector_tickers:
        try:
            df = yf.download(tk, start="2005-01-01", progress=False, auto_adjust=True)
            if df is not None and len(df) > 0:
                c = df["Close"]
                if isinstance(c, pd.DataFrame): c = c.iloc[:, 0]
                sect_data[tk.lower()] = c
        except Exception as e:
            log(f"  warn {tk}: {e}")
    sect_df = pd.DataFrame(sect_data)
    sect_df.to_parquet(SOURCE / "sector_etfs.parquet")
    log(f"  saved sector_etfs.parquet ({sect_df.shape})")

    # ---- FRED ----
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        log("  no FRED_API_KEY — skipping FRED refresh (keeping existing)")
    else:
        log("fetching FRED...")
        try:
            from fredapi import Fred
            fred = Fred(api_key=api_key)
            fred_series = {
                "hy_oas":"BAMLH0A0HYM2", "ig_oas":"BAMLC0A0CM",
                "us02y":"DGS2", "us10y":"DGS10", "us03m":"DGS3MO",
                "sofr":"SOFR", "effr":"EFFR", "ted_spread":"TEDRATE",
                "claims_weekly":"ICSA", "claims_4wk":"IC4WSA", "continued_claims":"CCSA",
                "fed_balance_sheet":"WALCL", "rrp":"RRPONTSYD",
                "nfci":"NFCI", "anfci":"ANFCI",
                "breakeven_5y":"T5YIE", "breakeven_10y":"T10YIE",
                "baa_yield":"BAA", "aaa_yield":"AAA",
                "mortgage_30y":"MORTGAGE30US",
                "umich_sentiment":"UMCSENT", "ism_mfg":"BUSLOANS",
            }
            fred_data = {}
            for name, sid in fred_series.items():
                try:
                    s = fred.get_series(sid, observation_start="2005-01-01")
                    fred_data[name] = s.dropna()
                except Exception as e:
                    log(f"  warn FRED {name}: {e}")
            fred_df = pd.DataFrame(fred_data)
            fred_df.to_parquet(SOURCE / "fred_indicators.parquet")
            log(f"  saved fred_indicators.parquet ({fred_df.shape})")

            # fred_derived
            fdr = pd.DataFrame(index=fred_df.index)
            if "us02y" in fred_df and "us10y" in fred_df:
                fdr["yield_2s10s"] = fred_df["us10y"] - fred_df["us02y"]
            if "us03m" in fred_df and "us10y" in fred_df:
                fdr["yield_3m10y"] = fred_df["us10y"] - fred_df["us03m"]
            if "sofr" in fred_df and "effr" in fred_df:
                fdr["sofr_ff_bps"] = (fred_df["sofr"] - fred_df["effr"]) * 100
            if "baa_yield" in fred_df and "aaa_yield" in fred_df:
                fdr["baa_aaa_spread"] = (fred_df["baa_yield"] - fred_df["aaa_yield"]) * 100
            if "fed_balance_sheet" in fred_df:
                fdr["fed_bs_T"] = fred_df["fed_balance_sheet"] / 1e6   # millions → trillions
            if "claims_weekly" in fred_df:
                rolling_low = fred_df["claims_weekly"].rolling(52, min_periods=10).min()
                fdr["claims_dist_from_low"] = (fred_df["claims_weekly"] / rolling_low - 1) * 100
            fdr.to_parquet(SOURCE / "fred_derived.parquet")
            log(f"  saved fred_derived.parquet ({fdr.shape})")
        except Exception as e:
            log(f"  FRED refresh failed: {e}")

    log(f"\nDone. New last date in prices: {new_last.date()}")
    log(f"total elapsed: {time.time() - T0:.1f}s")


if __name__ == "__main__":
    main()
