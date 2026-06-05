"""
Build data/indicator_series.json — full history per indicator for the dashboard's
click-to-drill-down detail panel.

Per indicator:
  - 5y of raw values, sampled to ~500 points
  - 5y of z-scores (same sampling)
  - current value, z, phi, status
  - 1y / lifetime statistics
  - tier / direction / weight / narrative / FRED series id
"""
from __future__ import annotations
import json, math
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# Reuse the indicator catalogue + sources from compute_regime_v2
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import compute_regime_v2 as crv2

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"

CHART_DAYS = 1260      # ~5y of trading days
TARGET_POINTS = 500    # downsample target

DESCRIPTIONS = {
    "nfci":            ("Chicago Fed National Financial Conditions Index", "FRED:NFCI",
                        "Composite of 105 financial variables. Designed to lead economic activity by 1-3 quarters."),
    "anfci":           ("Adjusted NFCI (business-cycle-stripped)", "FRED:ANFCI",
                        "Removes business cycle correlation from NFCI. Isolates the pure financial stress signal."),
    "yield_3m10y":     ("10Y minus 3M Treasury yield", "FRED:DGS10−DGS3MO",
                        "Spread between 10Y and 3M. Inversion has predicted every US recession since 1968 with 6-18 month lead."),
    "breakeven_5y":    ("5Y inflation breakeven", "FRED:T5YIE",
                        "TIPS vs nominal Treasury. Rising breakevens signal market expects inflation to force Fed tightening."),
    "baa_aaa":         ("Baa minus Aaa corporate yield spread", "FRED:BAA−AAA",
                        "Bond investors' default-quality differentiation. Widens before defaults arrive."),
    "vix_term":        ("VIX − VIX3M term structure", "CBOE",
                        "Backwardation (VIX>VIX3M) means options market prices near-term risk higher than medium-term. Acute leading signal."),
    "skew":            ("CBOE SKEW Index", "CBOE",
                        "OTM put vs ATM call pricing. Low skew = complacency. Tail protection is cheap, so investors aren't buying it."),
    "vix":             ("CBOE Volatility Index (30-day implied)", "CBOE",
                        "30-day expected SPX volatility from options. Forward by mechanism, partly contemporaneous in timing."),
    "vvix":            ("VIX of VIX — vol of vol", "CBOE",
                        "Implied vol of VIX options. Demand for convexity. More leading than VIX itself."),
    "mfg_new_orders":  ("Manufacturers' New Orders: Durable Goods", "FRED:NEWORDER",
                        "Monthly durable goods orders. Substitute for ISM mfg new orders (discontinued on FRED). Leads production by 1-2 months."),
    "kcfsi":           ("Kansas City Fed Financial Stress Index", "FRED:KCFSI",
                        "11-variable composite. Positive values indicate above-average stress. Alternative to NFCI."),
    "stlfsi":          ("St. Louis Fed Financial Stress Index v4", "FRED:STLFSI4",
                        "Weekly 18-variable composite. Zero = normal. Captures yield spreads, vol, correlations."),
    "loan_tightening": ("SLOOS net % tightening C&I standards", "FRED:DRTSCILM",
                        "Quarterly. Positive = banks tightening. Leads credit cycles by 2-4 quarters."),
    "consumer_expect": ("Michigan Consumer Expectations Index", "FRED:MICH",
                        "Monthly. Forward-looking part of UMich sentiment. Expectations about income / business / buying 1-5Y out."),
    "hyg_lqd":         ("HYG / LQD ratio", "Yahoo: HYG/LQD",
                        "High-yield ETF vs investment-grade ETF. Falling ratio = credit deteriorating now. Leads equities by 1-2 weeks."),
    "gold_spx":        ("Gold / SPX ratio", "Yahoo: GC=F / ^GSPC",
                        "Current safe-haven demand. Reacts to geopolitical risk faster than equities."),
    "tlt_spx":         ("TLT / SPX ratio", "Yahoo: TLT / ^GSPC",
                        "Current flight-to-quality into Treasuries. Breaks when stocks and bonds fall together (2022)."),
    "def_cyc":         ("Defensive / Cyclical sector ratio", "Yahoo: (XLU+XLP)/(XLK+XLY)",
                        "Institutional rotation. Defensive bid = beta reduction by fund managers. Leads broad market 2-4 weeks."),
    "dxy":             ("US Dollar Index", "Yahoo: DX-Y.NYB",
                        "Current dollar strength. Strong USD drains global liquidity. Effects propagate to equities 1-4 weeks."),
    "realized_vol":    ("SPX 20-day realized volatility", "Computed: SPX",
                        "Trailing 20-day std of SPX returns × √252. Value comes only from volatility clustering."),
    "spx_ret_60d":     ("SPX 60-day return", "Computed: SPX",
                        "Trailing 60-day price change. Purely backward-looking; persistence keeps regime elevated DURING drawdowns."),
    "spx_drawdown":    ("SPX drawdown from running peak", "Computed: SPX",
                        "Distance from past 252-day peak. Mean time to recovery from −10% is ~4 months."),
    "oil_60d_vel":     ("Oil 60-day velocity", "Computed: CL=F",
                        "Trailing 60-day oil price change. Oil shocks lead recessions but the price itself is contemporaneous."),
}

NAMES = {
    "nfci": "NFCI",
    "anfci": "ANFCI",
    "yield_3m10y": "3m-10y spread",
    "breakeven_5y": "5y breakeven",
    "baa_aaa": "Baa-Aaa spread",
    "vix_term": "VIX term",
    "skew": "SKEW",
    "vix": "VIX",
    "vvix": "VVIX",
    "mfg_new_orders": "Mfg new orders",
    "kcfsi": "KCFSI",
    "stlfsi": "STLFSI",
    "loan_tightening": "Loan tightening",
    "consumer_expect": "UMich expectations",
    "hyg_lqd": "HYG/LQD",
    "gold_spx": "Gold/SPX",
    "tlt_spx": "TLT/SPX",
    "def_cyc": "Defensive/Cyclical",
    "dxy": "DXY",
    "realized_vol": "Realized vol (20d)",
    "spx_ret_60d": "SPX 60-day return",
    "spx_drawdown": "SPX drawdown",
    "oil_60d_vel": "Oil 60-day velocity",
}

# Sampling stride to keep JSON small.
# CRITICAL: iloc[::stride] silently drops the LAST point whenever
# (len-1) is not a multiple of stride — e.g. len=1260 with stride=2
# samples indices 0,2,...,1258 and drops 1259 (today's reading). That
# made the indicator chart end one day before the current-state panel
# during a crash session. Always force the final observation into the
# sample so chart endpoint == panel "current state."
def downsample(series: pd.Series, target: int = TARGET_POINTS) -> pd.Series:
    if len(series) <= target:
        return series
    stride = max(1, len(series) // target)
    sampled = series.iloc[::stride]
    if len(series) > 0 and sampled.index[-1] != series.index[-1]:
        sampled = pd.concat([sampled, series.iloc[[-1]]])
    return sampled


def _clean(o):
    if isinstance(o, dict):  return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):  return [_clean(v) for v in o]
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)): return None
    return o


def main():
    print("Loading sources + computed scores...")
    sources = crv2.load_sources()
    series_dict = crv2.load_series_dict(sources)
    panel = crv2.build_daily_panel(series_dict)
    zscores = pd.read_parquet(DATA / "regime_v2_zscores.parquet"); zscores.index = pd.to_datetime(zscores.index)
    risks   = pd.read_parquet(DATA / "regime_v2_risk_scores.parquet"); risks.index = pd.to_datetime(risks.index)

    out = {}
    for spec in crv2.INDICATORS:
        key, tier, direction, src, col, label, fmt, _narr = spec
        if key not in panel.columns: continue
        raw = panel[key].dropna()
        if len(raw) < 30: continue
        # Trim to last CHART_DAYS, then downsample
        raw5 = downsample(raw.tail(CHART_DAYS))
        z_series = zscores[key].dropna() if key in zscores.columns else pd.Series(dtype=float)
        r_series = risks[key].dropna() if key in risks.columns else pd.Series(dtype=float)
        z5 = downsample(z_series.tail(CHART_DAYS)) if not z_series.empty else pd.Series(dtype=float)

        # Build chart points
        chart = [{"d": d.strftime("%Y-%m-%d"), "v": round(float(v), 4)}
                 for d, v in raw5.items() if pd.notna(v)]
        z_chart = [{"d": d.strftime("%Y-%m-%d"), "v": round(float(v), 3)}
                   for d, v in z5.items() if pd.notna(v)]

        # Stats from the FULL trailing 252 days of raw values (not downsampled)
        last_1y = raw.tail(252)
        cur = float(raw.iloc[-1])
        cur_z = float(z_series.iloc[-1]) if not z_series.empty else None
        cur_phi = float(r_series.iloc[-1]) if not r_series.empty else None
        # Percentile = fraction of past-1y observations <= current
        pct = float((last_1y <= cur).mean() * 100) if len(last_1y) > 0 else None

        desc_tuple = DESCRIPTIONS.get(key, (label, src + ":" + col, ""))
        display_name, source_label, description = desc_tuple

        try:
            value_str = fmt.format(v=cur)
        except Exception:
            value_str = f"{cur:.2f}"

        out[key] = {
            "key":          key,
            "label":        label,
            "display_name": display_name,
            "tier":         tier,
            "weight":       crv2.TIER_WEIGHTS[tier],
            "direction":    direction,
            "source_label": source_label,
            "description":  description,
            "current": {
                "value":      round(cur, 4),
                "value_str":  value_str,
                "z":          round(cur_z, 3) if cur_z is not None else None,
                "phi":        round(cur_phi, 3) if cur_phi is not None else None,
                "status":     crv2.status_from_phi(cur_phi) if cur_phi is not None else None,
                "date":       raw.index[-1].strftime("%Y-%m-%d"),
                "percentile_1y": round(pct, 1) if pct is not None else None,
            },
            "stats": {
                "mean_1y":   round(float(last_1y.mean()), 4),
                "std_1y":    round(float(last_1y.std()), 4),
                "min_1y":    round(float(last_1y.min()), 4),
                "max_1y":    round(float(last_1y.max()), 4),
                "min_all":   round(float(raw.min()), 4),
                "max_all":   round(float(raw.max()), 4),
                "n_obs":     int(len(raw)),
                "start":     raw.index[0].strftime("%Y-%m-%d"),
            },
            "chart":   chart,
            "z_chart": z_chart,
        }

    outpath = DATA / "indicator_series.json"
    with open(outpath, "w") as f:
        json.dump(_clean({"updated": datetime.now().isoformat(), "indicators": out}),
                  f, separators=(",", ":"), default=str, allow_nan=False)
    size_kb = outpath.stat().st_size / 1024
    print(f"  saved {outpath}  ({len(out)} indicators, {size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
