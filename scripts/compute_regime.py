"""
Compute daily R_t (regime risk score) from market indicators.
Uses 12 indicators with rolling 252-day z-scores, mapped to [0,1] via Φ.

Input:  fetches live data from Yahoo Finance
Output: data/regime_daily.csv (full series; overwritten each run)

R_t ∈ [0,1] where 0.0 = minimum risk, 1.0 = maximum risk.
"""
from __future__ import annotations
import sys, warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import norm

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR  = REPO_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)


def fetch_indicator_data(lookback_days: int = 400) -> pd.DataFrame:
    end = datetime.now()
    start = end - timedelta(days=lookback_days)

    yahoo_tickers = {
        "vix":  "^VIX",
        "vvix": "^VVIX",
        "skew": "^SKEW",
        "spx":  "^GSPC",
        "dxy":  "DX-Y.NYB",
        "oil":  "CL=F",
        "gold": "GC=F",
        "tlt":  "TLT",
        "hyg":  "HYG",
        "lqd":  "LQD",
    }
    data = {}
    for name, ticker in yahoo_tickers.items():
        try:
            df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
            if df is not None and len(df) > 0:
                close = df["Close"]
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                data[name] = close
        except Exception as e:
            print(f"  warn: {name} ({ticker}): {e}", file=sys.stderr)
    prices = pd.DataFrame(data)

    # Defensive/Cyclical from sector ETFs
    sector_tickers = ["XLU", "XLP", "XLK", "XLY"]
    try:
        sect = yf.download(sector_tickers, start=start, end=end,
                           progress=False, auto_adjust=True)
        if sect is not None and "Close" in sect:
            closes = sect["Close"]
            prices["def_cyc"] = (closes["XLU"] + closes["XLP"]) / (closes["XLK"] + closes["XLY"])
    except Exception as e:
        print(f"  warn: sector ETFs: {e}", file=sys.stderr)
    return prices


def compute_regime_score(prices: pd.DataFrame, lookback: int = 252):
    """Returns (R_t Series, per-indicator Φ(z) DataFrame)."""
    indicators = {}

    if "vix"  in prices: indicators["vix"]  = ("higher", prices["vix"])
    if "vvix" in prices: indicators["vvix"] = ("higher", prices["vvix"])
    if "skew" in prices: indicators["skew"] = ("lower",  prices["skew"])

    if "spx" in prices:
        rv = prices["spx"].pct_change().rolling(20).std() * np.sqrt(252) * 100
        indicators["realized_vol"] = ("higher", rv)
        indicators["spx_ret_60d"]  = ("lower",  prices["spx"].pct_change(60) * 100)
        dd = (prices["spx"] / prices["spx"].cummax() - 1) * 100
        indicators["spx_drawdown"] = ("lower",  dd)

    if "hyg" in prices and "lqd" in prices:
        indicators["hyg_lqd"] = ("lower", prices["hyg"] / prices["lqd"])
    if "gold" in prices and "spx" in prices:
        indicators["gold_spx"] = ("higher", prices["gold"] / prices["spx"])
    if "tlt"  in prices and "spx" in prices:
        indicators["tlt_spx"]  = ("higher", prices["tlt"] / prices["spx"])
    if "def_cyc" in prices:
        indicators["def_cyc"]  = ("higher", prices["def_cyc"])
    if "oil" in prices:
        indicators["oil_60d_vel"] = ("higher", prices["oil"].pct_change(60) * 100)
    if "dxy" in prices:
        indicators["dxy"] = ("higher", prices["dxy"])

    regime_components = pd.DataFrame(index=prices.index)
    for name, (direction, series) in indicators.items():
        roll_mean = series.rolling(lookback, min_periods=60).mean()
        roll_std  = series.rolling(lookback, min_periods=60).std().replace(0, np.nan)
        z = (series - roll_mean) / roll_std
        if direction == "lower":
            z = -z
        regime_components[name] = norm.cdf(z)

    R_t = regime_components.mean(axis=1)
    return R_t, regime_components


def regime_label(R: float) -> str:
    if R < 0.30: return "LOW RISK"
    if R < 0.50: return "ELEVATED"
    if R < 0.70: return "HIGH RISK"
    return "CRISIS"


def main():
    print("Fetching indicator data...")
    prices = fetch_indicator_data(lookback_days=400)
    print(f"  fetched {prices.shape[1]} indicator series, {prices.shape[0]} rows")

    print("Computing R_t...")
    R_t, components = compute_regime_score(prices)

    if R_t.dropna().empty:
        print("ERROR: R_t series is empty (insufficient data)", file=sys.stderr)
        sys.exit(1)

    today_R = float(R_t.dropna().iloc[-1])
    regime = regime_label(today_R)

    print(f"\nR_t today: {today_R:.3f} → {regime}")
    print("Cash formula examples:")
    print(f"  Tier 1 (Cap Pres):   {min(100, 25 + today_R * 75):.0f}% cash")
    print(f"  Tier 2 (Balanced):   {min(85,  15 + today_R * 70):.0f}% cash")
    print(f"  Tier 3 (Aggressive): {min(50,  10 + today_R * 40):.0f}% cash")
    print(f"  Tier 4 (Tactical):   {min(100, today_R * 100):.0f}% cash")

    regime_df = pd.DataFrame({"R_t": R_t, "n_indicators": components.notna().sum(axis=1)})
    regime_df.index.name = "date"
    out = DATA_DIR / "regime_daily.csv"
    regime_df.to_csv(out)
    print(f"\nSaved to {out}  ({len(regime_df)} rows)")

    return today_R


if __name__ == "__main__":
    main()
