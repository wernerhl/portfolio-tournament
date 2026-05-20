"""
Score every ticker on technical + fundamental factors as of the latest available data.
Output: data/scored_universe.csv  (ticker, name, sector, scores, ranks, raw metrics).
Runs monthly on the 1st (via monthly_rebalance.yml).
"""
from __future__ import annotations
import json, warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO     = Path(__file__).resolve().parent.parent
DATA     = REPO / "data"
SOURCE   = DATA / "source"
DATA.mkdir(exist_ok=True)


def rsi14(close: pd.Series) -> pd.Series:
    d = close.diff()
    g = d.clip(lower=0).rolling(14).mean()
    l = (-d.clip(upper=0)).rolling(14).mean()
    rs = g / l.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def main():
    print("Loading source parquet files...")
    prices = pd.read_parquet(SOURCE / "prices_daily.parquet")
    if "SPY_volume" in prices.columns:
        prices = prices.drop(columns=["SPY_volume"])
    prices.index = pd.to_datetime(prices.index)
    fund = pd.read_parquet(SOURCE / "fundamentals_snapshot.parquet")
    vol  = pd.read_parquet(SOURCE / "vol_indicators.parquet")
    vol.index = pd.to_datetime(vol.index)
    spx = vol["spx"].dropna().reindex(prices.index).ffill()

    today = prices.index[-1]
    print(f"  scoring as of {today.date()}  ({prices.shape[1]} tickers)")

    # Eligibility: ≥ 252 days of non-null price history through today
    history_days = prices.notna().sum()
    eligible = history_days[history_days >= 252].index.tolist()
    print(f"  eligible: {len(eligible)} tickers")

    # --- Technical metrics (latest values) ---
    ma200 = prices[eligible].rolling(200, min_periods=200).mean().iloc[-1]
    rsi   = prices[eligible].apply(rsi14).iloc[-1]
    ret_6m_stock = prices[eligible].iloc[-1] / prices[eligible].iloc[-127] - 1
    ret_6m_spx   = float(spx.iloc[-1] / spx.iloc[-127] - 1)

    tech = pd.DataFrame(index=eligible)
    tech["ma200_dist"] = (prices[eligible].iloc[-1] / ma200 - 1)
    tech["rsi"]        = rsi
    tech["rel_str_6m"] = ret_6m_stock - ret_6m_spx

    # Cross-sectional ranks (0 to 1, where 1 = best by the model's preference)
    # Lower ma200_dist = better → invert rank
    tech["ma200_rank"] = 1.0 - tech["ma200_dist"].rank(pct=True)
    # Lower RSI = better → invert
    tech["rsi_rank"]   = 1.0 - tech["rsi"].rank(pct=True)
    # Higher relative strength = better
    tech["rs6m_rank"]  = tech["rel_str_6m"].rank(pct=True)

    tech["tech_score"] = (tech["ma200_rank"].fillna(0.5) +
                          tech["rsi_rank"].fillna(0.5) +
                          tech["rs6m_rank"].fillna(0.5)) / 3 * 25

    # --- Fundamental metrics ---
    fund_metrics = [
        ("forwardPE",       -1),
        ("revenueGrowth",   +1),
        ("grossMargins",    +1),
        ("returnOnEquity",  +1),
        ("operatingMargins",+1),
    ]
    f = pd.DataFrame(index=fund.index)
    for col, sign in fund_metrics:
        if col not in fund.columns: continue
        s = pd.to_numeric(fund[col], errors="coerce")
        lo, hi = s.quantile(0.02), s.quantile(0.98)
        s = s.clip(lo, hi)
        r = s.rank(pct=True)
        if sign == -1: r = 1 - r
        f[col + "_rank"] = r
    f["fund_score"] = f.mean(axis=1, skipna=True) * 25

    # Sector + name + market cap from fundamentals snapshot
    meta_cols = ["sector", "industry", "shortName", "marketCap",
                 "forwardPE", "revenueGrowth", "grossMargins",
                 "returnOnEquity", "operatingMargins", "freeCashflow"]
    meta = fund[[c for c in meta_cols if c in fund.columns]].copy()

    # --- Combine ---
    out = pd.DataFrame(index=eligible)
    out = out.join(tech)
    out = out.join(f, how="left")
    out = out.join(meta, how="left")
    out["fund_score"] = out["fund_score"].fillna(out["fund_score"].median())

    out["composite"] = out["tech_score"] + out["fund_score"]
    out["composite_rank"] = out["composite"].rank(ascending=False, method="min").astype(int)
    out["tech_rank"]      = out["tech_score"].rank(ascending=False, method="min").astype(int)
    out["fund_rank"]      = out["fund_score"].rank(ascending=False, method="min").astype(int)

    out.index.name = "ticker"
    out = out.reset_index()
    # Column order
    cols = ["ticker", "shortName", "sector", "industry", "marketCap",
            "tech_score", "fund_score", "composite",
            "composite_rank", "tech_rank", "fund_rank",
            "ma200_dist", "rsi", "rel_str_6m",
            "ma200_rank", "rsi_rank", "rs6m_rank",
            "forwardPE", "revenueGrowth", "grossMargins",
            "returnOnEquity", "operatingMargins", "freeCashflow",
            "forwardPE_rank", "revenueGrowth_rank", "grossMargins_rank",
            "returnOnEquity_rank", "operatingMargins_rank"]
    cols = [c for c in cols if c in out.columns]
    out = out[cols].sort_values("composite", ascending=False)
    out.to_csv(DATA / "scored_universe.csv", index=False)
    print(f"  saved {len(out)} scored tickers → data/scored_universe.csv")
    print(f"  top 5: {out.head(5)['ticker'].tolist()}")


if __name__ == "__main__":
    main()
