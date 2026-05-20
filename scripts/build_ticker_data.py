"""
Build per-ticker indicator JSON for every ticker held in any tier (1-4 algorithmic or
Werner's manual). Dashboard reads data/ticker_indicators.json for the drill-down panel.
"""
from __future__ import annotations
import json, warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO   = Path(__file__).resolve().parent.parent
DATA   = REPO / "data"
SOURCE = DATA / "source"


def rsi14(s: pd.Series) -> float:
    d = s.diff()
    g = d.clip(lower=0).rolling(14).mean()
    l = (-d.clip(upper=0)).rolling(14).mean()
    rs = g.iloc[-1] / l.iloc[-1] if (l.iloc[-1] and l.iloc[-1] > 0) else np.nan
    return float(100 - 100 / (1 + rs)) if pd.notna(rs) else None


def main():
    print("loading source...")
    prices = pd.read_parquet(SOURCE / "prices_daily.parquet")
    if "SPY_volume" in prices.columns:
        prices = prices.drop(columns=["SPY_volume"])
    prices.index = pd.to_datetime(prices.index)
    fund    = pd.read_parquet(SOURCE / "fundamentals_snapshot.parquet")
    sect    = pd.read_parquet(SOURCE / "sector_etfs.parquet"); sect.index = pd.to_datetime(sect.index)

    scored  = pd.read_csv(DATA / "scored_universe.csv").set_index("ticker")

    # Collect every ticker in any tier
    tier_holdings = json.load(open(DATA / "tier_holdings.json"))
    cfg           = json.load(open(REPO / "config.json"))

    all_tickers = set()
    in_tiers_map = {}
    for tid, tickers in tier_holdings["tiers"].items():
        for t in tickers:
            all_tickers.add(t)
            in_tiers_map.setdefault(t, []).append(tid)
    for t in cfg["werner_picks"]["holdings"]:
        all_tickers.add(t)
        in_tiers_map.setdefault(t, []).append("5_werner")

    tickers = sorted(all_tickers)
    missing = [t for t in tickers if t not in prices.columns]
    if missing:
        print(f"  WARN: {len(missing)} tickers not in price data, skipping: {missing}")
    tickers = [t for t in tickers if t in prices.columns]
    print(f"building data for {len(tickers)} tickers")

    # Pre-compute returns DataFrame for correlations (60-day window, daily returns)
    rets_60d = prices[tickers].dropna(axis=1, how="all").pct_change().tail(60)
    # Include SPX
    if "SPX" not in rets_60d.columns:
        spx = pd.read_parquet(SOURCE / "vol_indicators.parquet")["spx"]
        spx.index = pd.to_datetime(spx.index)
        rets_60d["SPX"] = spx.reindex(rets_60d.index).pct_change()
    corr_mat = rets_60d.corr()

    out = {}
    for t in tickers:
        if t not in prices.columns:
            continue
        ser = prices[t].dropna()
        if len(ser) < 30:
            continue
        # Last 252 days for chart
        chart_ser = ser.tail(252)
        ma50  = ser.rolling(50,  min_periods=50).mean()
        ma200 = ser.rolling(200, min_periods=200).mean()
        chart = [{"d": d.strftime("%Y-%m-%d"),
                  "c": round(float(ser.loc[d]), 2),
                  "m50":  round(float(ma50.loc[d]), 2)  if pd.notna(ma50.loc[d]) else None,
                  "m200": round(float(ma200.loc[d]), 2) if pd.notna(ma200.loc[d]) else None}
                 for d in chart_ser.index]

        # Current technicals
        last_px = float(ser.iloc[-1])
        m50_v   = float(ma50.iloc[-1])  if pd.notna(ma50.iloc[-1])  else None
        m200_v  = float(ma200.iloc[-1]) if pd.notna(ma200.iloc[-1]) else None
        hi_52w  = float(ser.tail(252).max())
        lo_52w  = float(ser.tail(252).min())
        rng_pos = (last_px - lo_52w) / (hi_52w - lo_52w) * 100 if hi_52w > lo_52w else 50
        rsi     = rsi14(ser.tail(30))
        # Returns
        def ret(days):
            if len(ser) < days + 1: return None
            return round((ser.iloc[-1] / ser.iloc[-1 - days] - 1) * 100, 2)
        vol_20d = round(float(ser.pct_change().tail(20).std() * np.sqrt(252) * 100), 2)

        tech = {
            "price":          round(last_px, 2),
            "ma50":           round(m50_v, 2)  if m50_v else None,
            "ma200":          round(m200_v, 2) if m200_v else None,
            "ma50_dist":      round((last_px / m50_v - 1) * 100, 2)  if m50_v else None,
            "ma200_dist":     round((last_px / m200_v - 1) * 100, 2) if m200_v else None,
            "rsi":            round(rsi, 1) if rsi else None,
            "high_52w":       round(hi_52w, 2),
            "low_52w":        round(lo_52w, 2),
            "range_52w_pct":  round(rng_pos, 1),
            "ret_1w":  ret(5),  "ret_1m":  ret(21),  "ret_3m": ret(63),
            "ret_6m": ret(126), "ret_1y": ret(252),
            "vol_20d": vol_20d,
        }

        # Fundamentals from snapshot
        fund_row = fund.loc[t] if t in fund.index else None
        def fget(col, mul=1, ndigits=2):
            if fund_row is None or col not in fund_row.index: return None
            v = pd.to_numeric(fund_row[col], errors="coerce")
            if pd.isna(v): return None
            return round(float(v) * mul, ndigits)
        fund_dict = {
            "mcap_B":     fget("marketCap", 1e-9, 1),
            "fwd_pe":     fget("forwardPE", 1, 2),
            "trail_pe":   fget("trailingPE", 1, 2),
            "peg":        fget("pegRatio", 1, 2),
            "pb":         fget("priceToBook", 1, 2),
            "ps":         fget("priceToSalesTrailing12Months", 1, 2),
            "ev_ebitda":  fget("enterpriseToEbitda", 1, 2),
            "rev_growth": fget("revenueGrowth", 100, 1),
            "gross_mgn":  fget("grossMargins",  100, 1),
            "op_mgn":     fget("operatingMargins", 100, 1),
            "profit_mgn": fget("profitMargins", 100, 1),
            "roe":        fget("returnOnEquity", 100, 1),
            "roa":        fget("returnOnAssets", 100, 1),
            "de":         fget("debtToEquity",  1, 2),
            "fcf_B":      fget("freeCashflow",  1e-9, 2),
            "div_yield":  fget("dividendYield", 100, 2),
            "beta":       fget("beta", 1, 2),
        }

        # Score breakdown
        score_dict = None
        if t in scored.index:
            s_row = scored.loc[t]
            pct = lambda r: round(float(r) * 100, 1) if pd.notna(r) else None
            score_dict = {
                "technical":   round(float(s_row.get("tech_score", np.nan)), 2),
                "fundamental": round(float(s_row.get("fund_score", np.nan)), 2),
                "composite":   round(float(s_row.get("composite", np.nan)), 2),
                "rank":        int(s_row.get("composite_rank", 0)),
                "percentile":  round(100 * (1 - (s_row.get("composite_rank", 0) - 1) / max(len(scored), 1)), 1),
                "components": {
                    "ma200_dist":  pct(s_row.get("ma200_rank")),
                    "rsi":         pct(s_row.get("rsi_rank")),
                    "rel_str_6m":  pct(s_row.get("rs6m_rank")),
                    "fwd_pe":      pct(s_row.get("forwardPE_rank")),
                    "rev_growth":  pct(s_row.get("revenueGrowth_rank")),
                    "gross_mgn":   pct(s_row.get("grossMargins_rank")),
                    "roe":         pct(s_row.get("returnOnEquity_rank")),
                    "op_mgn":      pct(s_row.get("operatingMargins_rank")),
                },
            }

        # Top-10 correlations with other portfolio tickers + SPX
        corrs = {}
        if t in corr_mat.columns:
            row = corr_mat[t].drop(t, errors="ignore").dropna()
            top = row.abs().nlargest(10).index.tolist()
            for u in top:
                corrs[u] = round(float(corr_mat.loc[t, u]), 3)

        # Identity
        sector = fund_row["sector"] if fund_row is not None and "sector" in fund_row.index else None
        industry = fund_row["industry"] if fund_row is not None and "industry" in fund_row.index else None
        name = fund_row["shortName"] if fund_row is not None and "shortName" in fund_row.index else t

        out[t] = {
            "ticker":   t,
            "name":     name,
            "sector":   sector,
            "industry": industry,
            "in_tiers": in_tiers_map.get(t, []),
            "chart":    chart,
            "tech":     tech,
            "fund":     fund_dict,
            "score":    score_dict,
            "corr":     corrs,
        }

    outpath = DATA / "ticker_indicators.json"
    with open(outpath, "w") as f:
        json.dump(out, f, separators=(",", ":"), default=str)
    size_kb = outpath.stat().st_size / 1024
    print(f"saved {len(out)} tickers → {outpath} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
