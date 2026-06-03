"""
Compute daily R_t (regime risk score) from 12 risk indicators.

Inputs:  Yahoo Finance (11 series) + FRED (Baa-Aaa spread)
Outputs:
  data/regime_daily.csv         — full R_t time series + n_indicators
  data/regime_indicators.json   — current indicator snapshot for the dashboard
                                  (12 cards: value, z, phi, status, narrative)

R_t ∈ [0,1] where 0.0 = minimum risk, 1.0 = maximum risk.
"""
from __future__ import annotations
import json, math, os, sys, warnings
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

# --------------------------------------------------------------------
# Indicator catalogue + narrative templates per (status × indicator).
# Order here is the display order on the dashboard.
# --------------------------------------------------------------------
INDICATOR_META = {
    "vix": {
        "label": "VIX", "unit": "",
        "narratives": ["Calm hedging demand", "Hedging neutral",
                       "Caution rising",       "Stress signaling"],
        "fmt": "{v:.2f}",
    },
    "vvix": {
        "label": "VVIX", "unit": "",
        "narratives": ["Tail protection cheap", "Tail protection moderate",
                       "Tail protection bid",   "Vol-of-vol stretched"],
        "fmt": "{v:.1f}",
    },
    "skew": {
        "label": "SKEW", "unit": "",
        # SKEW is sign-flipped (lower SKEW = higher risk). Narratives mirror status.
        "narratives": ["Moderate tail pricing", "Tail risk moderate",
                       "Tail risk underpriced", "Tail complacency"],
        "fmt": "{v:.0f}",
    },
    "realized_vol": {
        "label": "Real vol", "unit": "%",
        "narratives": ["Below-average volatility", "Normal volatility",
                       "Volatility rising",        "Volatility spike"],
        "fmt": "{v:.1f}",
    },
    "hyg_lqd": {
        "label": "HYG/LQD", "unit": "",
        "narratives": ["Credit spreads tight",   "Credit spreads stable",
                       "Credit spreads widening","Credit stress acute"],
        "fmt": "{v:.2f}",
    },
    "baa_aaa": {
        "label": "Baa-Aaa", "unit": "%",
        "narratives": ["Quality spread normal",   "Quality spread firm",
                       "Quality spread widening", "Quality spread acute"],
        "fmt": "{v:.2f}",
    },
    "spx_ret_60d": {
        "label": "SPX 60d", "unit": "%",
        "narratives": ["Positive momentum", "Momentum mixed",
                       "Momentum negative", "Momentum severely negative"],
        "fmt": "{v:+.1f}",
    },
    "spx_drawdown": {
        "label": "SPX DD", "unit": "%",
        "narratives": ["Near all-time high", "Mild pullback",
                       "In drawdown",         "Deep drawdown"],
        "fmt": "{v:+.1f}",
    },
    "gold_spx": {
        "label": "Gold/SPX", "unit": "",
        "narratives": ["No safe-haven bid",   "Mild safe-haven bid",
                       "Elevated safe-haven bid", "Heavy flight to safety"],
        "fmt": "{v:.2f}",
    },
    "tlt_spx": {
        "label": "TLT/SPX", "unit": "",
        "narratives": ["No flight to quality", "Bond bid neutral",
                       "Bond bid rising",      "Heavy flight to quality"],
        "fmt": "{v:.3f}",
    },
    "def_cyc": {
        "label": "Def/cyc", "unit": "",
        "narratives": ["Cyclical leadership",  "Sector rotation neutral",
                       "Slight defensive rotation", "Heavy defensive rotation"],
        "fmt": "{v:.2f}",
    },
    "oil_60d_vel": {
        "label": "Oil 60d", "unit": "%",
        "narratives": ["No supply shock", "Oil drift",
                       "Oil rallying",    "Oil shock"],
        "fmt": "{v:+.1f}",
    },
}

# --------------------------------------------------------------------
# Data fetchers
# --------------------------------------------------------------------
def fetch_yahoo(lookback_days: int = 400) -> pd.DataFrame:
    end = datetime.now()
    start = end - timedelta(days=lookback_days)
    yahoo_tickers = {
        "vix":  "^VIX",  "vvix": "^VVIX", "skew": "^SKEW",
        "spx":  "^GSPC", "oil":  "CL=F",  "gold": "GC=F",
        "tlt":  "TLT",   "hyg":  "HYG",   "lqd":  "LQD",
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

    # Defensive/Cyclical sector ratio
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


def fetch_fred_baa_aaa(lookback_days: int = 400) -> pd.Series | None:
    """Daily Baa-Aaa corporate bond yield spread, percentage points."""
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        print("  warn: no FRED_API_KEY — Baa-Aaa indicator will be missing", file=sys.stderr)
        return None
    try:
        from fredapi import Fred
        fred = Fred(api_key=api_key)
        start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        baa = fred.get_series("BAA", observation_start=start).dropna()
        aaa = fred.get_series("AAA", observation_start=start).dropna()
        return (baa - aaa).dropna()
    except Exception as e:
        print(f"  warn: FRED Baa-Aaa fetch failed: {e}", file=sys.stderr)
        return None


# --------------------------------------------------------------------
# Build the indicator panel (with risk direction)
# --------------------------------------------------------------------
def build_indicator_panel(prices: pd.DataFrame, baa_aaa: pd.Series | None) -> dict:
    """Returns {indicator_key: (direction, raw_series)}.  direction ∈ {"higher", "lower"}
       where the direction is which way of the raw series is RISKIER."""
    indicators = {}

    if "vix"  in prices: indicators["vix"]          = ("higher", prices["vix"])
    if "vvix" in prices: indicators["vvix"]         = ("higher", prices["vvix"])
    if "skew" in prices: indicators["skew"]         = ("lower",  prices["skew"])

    if "spx" in prices:
        rv = prices["spx"].pct_change().rolling(20).std() * np.sqrt(252) * 100
        indicators["realized_vol"] = ("higher", rv)
        indicators["spx_ret_60d"]  = ("lower",  prices["spx"].pct_change(60) * 100)
        dd = (prices["spx"] / prices["spx"].cummax() - 1) * 100
        indicators["spx_drawdown"] = ("lower",  dd)

    if "hyg" in prices and "lqd" in prices:
        indicators["hyg_lqd"]  = ("lower", prices["hyg"] / prices["lqd"])
    if baa_aaa is not None and not baa_aaa.empty:
        indicators["baa_aaa"] = ("higher", baa_aaa)
    if "gold" in prices and "spx" in prices:
        indicators["gold_spx"] = ("higher", prices["gold"] / prices["spx"])
    if "tlt"  in prices and "spx" in prices:
        indicators["tlt_spx"]  = ("higher", prices["tlt"] / prices["spx"])
    if "def_cyc" in prices:
        indicators["def_cyc"]  = ("higher", prices["def_cyc"])
    if "oil" in prices:
        indicators["oil_60d_vel"] = ("higher", prices["oil"].pct_change(60) * 100)
    return indicators


def compute_regime_score(prices: pd.DataFrame, baa_aaa: pd.Series | None, lookback: int = 252):
    """Returns (R_t Series, per-indicator Φ(z) DataFrame, per-indicator raw values DF,
                per-indicator z DF, direction map)."""
    indicators = build_indicator_panel(prices, baa_aaa)
    common_idx = prices.index
    if baa_aaa is not None:
        common_idx = common_idx.union(baa_aaa.index)
    common_idx = sorted(common_idx)
    raw_df  = pd.DataFrame(index=common_idx)
    z_df    = pd.DataFrame(index=common_idx)
    phi_df  = pd.DataFrame(index=common_idx)
    direction_map = {}

    for name, (direction, series) in indicators.items():
        s = series.reindex(common_idx).ffill()
        raw_df[name] = s
        roll_mean = s.rolling(lookback, min_periods=60).mean()
        roll_std  = s.rolling(lookback, min_periods=60).std().replace(0, np.nan)
        z = (s - roll_mean) / roll_std
        if direction == "lower":
            z = -z   # so higher z always = more risky
        z_df[name] = z
        phi_df[name] = norm.cdf(z)
        direction_map[name] = direction

    R_t = phi_df.mean(axis=1)
    return R_t, phi_df, raw_df, z_df, direction_map


def regime_label(R: float) -> str:
    if R < 0.30: return "LOW RISK"
    if R < 0.50: return "ELEVATED"
    if R < 0.70: return "HIGH RISK"
    return "CRISIS"


def status_from_phi(phi: float) -> str:
    """4-level status from Φ(z) value (always 'higher = riskier' after sign-flip)."""
    if phi < 0.40: return "safe"
    if phi < 0.60: return "neutral"
    if phi < 0.80: return "elevated"
    return "crisis"


def narrative_for(key: str, phi: float) -> str:
    meta = INDICATOR_META.get(key, {})
    narratives = meta.get("narratives") or ["—", "—", "—", "—"]
    if phi < 0.40: return narratives[0]
    if phi < 0.60: return narratives[1]
    if phi < 0.80: return narratives[2]
    return narratives[3]


# --------------------------------------------------------------------
# JSON serialization helpers
# --------------------------------------------------------------------
def _clean(o):
    if isinstance(o, dict):  return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):  return [_clean(v) for v in o]
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)): return None
    return o


def main():
    print("Fetching indicator data...")
    prices = fetch_yahoo(lookback_days=400)
    print(f"  Yahoo: {prices.shape[1]} series, {prices.shape[0]} rows")
    baa_aaa = fetch_fred_baa_aaa(lookback_days=400)
    if baa_aaa is not None:
        print(f"  FRED Baa-Aaa: {len(baa_aaa)} obs (last {baa_aaa.index[-1].date()})")

    print("Computing R_t + per-indicator state...")
    R_t, phi_df, raw_df, z_df, dir_map = compute_regime_score(prices, baa_aaa)

    if R_t.dropna().empty:
        print("ERROR: R_t series is empty (insufficient data)", file=sys.stderr)
        sys.exit(1)

    today_R = float(R_t.dropna().iloc[-1])
    regime  = regime_label(today_R)
    print(f"\nR_t today: {today_R:.3f} → {regime}")
    print("Cash formula examples:")
    print(f"  Tier 1 (Cap Pres):   {min(100, 25 + today_R * 75):.0f}% cash")
    print(f"  Tier 2 (Balanced):   {min(85,  15 + today_R * 70):.0f}% cash")
    print(f"  Tier 3 (Aggressive): {min(50,  10 + today_R * 40):.0f}% cash")
    print(f"  Tier 4 (Tactical):   {min(100, today_R * 100):.0f}% cash")

    # ---- regime_daily.csv (full history) ----
    regime_df = pd.DataFrame({"R_t": R_t, "n_indicators": phi_df.notna().sum(axis=1)})
    regime_df.index.name = "date"
    regime_df.to_csv(DATA_DIR / "regime_daily.csv")
    print(f"\nSaved regime_daily.csv  ({len(regime_df)} rows)")

    # ---- regime_indicators.json (current snapshot) ----
    indicator_payload = []
    last_idx = R_t.dropna().index[-1]
    for key, meta in INDICATOR_META.items():
        if key not in phi_df.columns:
            continue
        # Latest non-NaN row for THIS indicator
        s = phi_df[key].dropna()
        if s.empty: continue
        d = s.index[-1]
        phi_v = float(s.iloc[-1])
        z_v   = float(z_df[key].dropna().iloc[-1]) if not z_df[key].dropna().empty else None
        raw_v = float(raw_df[key].dropna().iloc[-1]) if not raw_df[key].dropna().empty else None
        status = status_from_phi(phi_v)
        narr = narrative_for(key, phi_v)
        try:
            value_str = meta["fmt"].format(v=raw_v) if raw_v is not None else "—"
        except Exception:
            value_str = f"{raw_v:.2f}" if raw_v is not None else "—"
        indicator_payload.append({
            "key":     key,
            "label":   meta["label"],
            "value":   raw_v,
            "value_str": value_str + meta.get("unit", ""),
            "z":       z_v,
            "phi":     phi_v,
            "status":  status,
            "narrative": narr,
            "direction": dir_map.get(key),
        })

    n_safe     = sum(1 for i in indicator_payload if i["status"] in ("safe", "neutral"))
    n_elevated = sum(1 for i in indicator_payload if i["status"] == "elevated")
    n_crisis   = sum(1 for i in indicator_payload if i["status"] == "crisis")
    total      = len(indicator_payload)

    if today_R < 0.30:
        verdict = f"Risk below average across {n_safe} of {total} channels. Full deployment permitted."
    elif today_R < 0.50:
        verdict = f"Mixed signals: {n_safe} safe / {n_elevated + n_crisis} flagged. Standard deployment with bias toward quality."
    elif today_R < 0.70:
        verdict = f"Elevated risk across {n_elevated + n_crisis} of {total} channels. Trim exposure, raise cash."
    else:
        verdict = f"Crisis regime: {n_crisis} channels in stress. Defensive posture, maximize cash."

    payload = {
        "updated": datetime.now().isoformat(),
        "as_of":   last_idx.strftime("%Y-%m-%d"),
        "R_t":     round(today_R, 4),
        "regime":  regime,
        "n_indicators": total,
        "n_safe":     n_safe,
        "n_elevated": n_elevated,
        "n_crisis":   n_crisis,
        "verdict":    verdict,
        "indicators": indicator_payload,
    }
    out_json = DATA_DIR / "regime_indicators.json"
    with open(out_json, "w") as f:
        json.dump(_clean(payload), f, indent=2, default=str, allow_nan=False)
    print(f"Saved regime_indicators.json  ({total} indicators)")
    print(f"  safe/neutral: {n_safe}  elevated: {n_elevated}  crisis: {n_crisis}")
    print(f"  verdict: {verdict}")

    return today_R


if __name__ == "__main__":
    main()
