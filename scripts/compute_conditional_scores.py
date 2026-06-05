"""
compute_conditional_scores.py — regime-conditional scoring of the
historical backtest, with empirical-Bayes / James-Stein shrinkage.

Per the brief:
  - Score each sleeve INSIDE its regime bucket (a tail hedge judged in
    stress; a contango harvester judged in contango).
  - REGRESSION framing, not raw buckets: regress daily returns on regime-
    state dummies; condition means + standard errors come out naturally.
  - James-Stein shrinkage toward the UNCONDITIONAL mean, intensity ∝ 1/n.
    With handful-per-year stress regimes, shrunk-conditional ≈ unconditional
    almost everywhere. That is the HONEST result — not a bug. Caption it.
  - Always display bucket n and shrinkage weight; never a raw bucket mean.

Output: data/regime_conditional_scores.json
"""
from __future__ import annotations
import json, math, sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO   = Path(__file__).resolve().parent.parent
DATA   = REPO / "data"
SOURCE = DATA / "source"

ANNUALIZE = 252.0


def classify_state(spread: float) -> str:
    # Mirror compute_vol_regime.STATE_BREAKS
    if spread < -3.0: return "deep_contango"
    if spread < -1.0: return "contango"
    if spread <  0.5: return "flattening"
    return "backwardation"


def james_stein_shrink(bucket_mean: float, bucket_var: float, bucket_n: int,
                        unc_mean: float) -> tuple[float, float]:
    """
    Empirical-Bayes / James-Stein shrinkage of a bucket mean toward the
    unconditional mean. Shrinkage intensity = bucket_se² / (bucket_se² + tau²),
    where tau is the spread between buckets. For thin buckets (large SE),
    shrinkage→1 (use unconditional); for thick buckets, shrinkage→0 (use raw).

    Approximation: shrinkage_weight = bucket_se² / (bucket_se² + 0.001²)
    (we use a small floor so even buckets with n≈252 still see a tiny touch
    of shrinkage toward the unconditional — keeps the toggle from being
    over-confident in any single regime cell).
    """
    if bucket_n < 2 or bucket_var <= 0:
        return unc_mean, 1.0
    bucket_se_sq = bucket_var / bucket_n
    # tau² = inter-bucket variance proxy; floor avoids division weirdness
    tau_sq = max(1e-8, abs(unc_mean) * 0.001)
    shrink_w = bucket_se_sq / (bucket_se_sq + tau_sq)
    shrunk = (1 - shrink_w) * bucket_mean + shrink_w * unc_mean
    return shrunk, shrink_w


def main():
    print("Loading backtest equity curves + vol regime...")
    bt = pd.read_csv(DATA / "backtest_equity_curves.csv", parse_dates=["date"]).set_index("date")
    vol = pd.read_parquet(SOURCE / "vol_indicators.parquet")
    vol.index = pd.to_datetime(vol.index)
    spread = (vol["vix"] - vol["vix3m"]).dropna()
    states = spread.apply(classify_state).rename("state")

    # Align backtest returns with regime states (signal known at close,
    # APPLIED at next session — Δreturns are next-day; assert no look-ahead)
    sleeves = [c for c in bt.columns if c in (
        "1_cap_pres","2_balanced","3_aggressive","4_tactical","spy","qqq","sso","60_40")]
    rets = bt[sleeves].pct_change().dropna(how="all")
    # Apply state TO THE FOLLOWING SESSION'S return (no look-ahead)
    states_t1 = states.shift(1)
    joined = rets.join(states_t1, how="inner").dropna(subset=["state"])

    # Unconditional means + variances (used as JS shrinkage target)
    unc = {}
    for s in sleeves:
        v = joined[s].dropna()
        unc[s] = {
            "n":          int(len(v)),
            "mean_daily": float(v.mean()),
            "ann_return": float(v.mean() * ANNUALIZE),
            "ann_vol":    float(v.std() * math.sqrt(ANNUALIZE)),
            "sharpe":     float((v.mean() * ANNUALIZE) / (v.std() * math.sqrt(ANNUALIZE))) if v.std() > 0 else None,
        }

    # Regression framing: per sleeve, regress returns on state dummies.
    # We implement this as a per-state mean + JS-shrunk version. The
    # regression SE equals σ/√n per cell; we use that for shrinkage.
    state_list = ["deep_contango", "contango", "flattening", "backwardation"]
    conditional = {}
    for s in sleeves:
        cells = {}
        for state in state_list:
            sub = joined[joined["state"] == state][s].dropna()
            n = int(len(sub))
            if n == 0:
                cells[state] = {
                    "n": 0, "ann_return": None, "ann_vol": None,
                    "shrunk_ann_return": unc[s]["ann_return"],
                    "shrinkage_weight": 1.0,
                    "raw_mean_daily": None,
                }
                continue
            raw_mean = float(sub.mean())
            raw_var  = float(sub.var())
            shrunk_d, w = james_stein_shrink(raw_mean, raw_var, n, unc[s]["mean_daily"])
            cells[state] = {
                "n":                  n,
                "raw_mean_daily":     raw_mean,
                "raw_ann_return":     raw_mean * ANNUALIZE,
                "raw_ann_vol":        float(sub.std() * math.sqrt(ANNUALIZE)),
                "shrunk_ann_return":  shrunk_d * ANNUALIZE,
                "shrinkage_weight":   round(w, 3),
                "se_daily":           math.sqrt(raw_var / n) if raw_var > 0 else None,
            }
        conditional[s] = {
            "unconditional": unc[s],
            "per_state":     cells,
        }

    # State-day census (for the dashboard "≈ unconditional until..." caption)
    state_n = joined["state"].value_counts().to_dict()
    total_days = int(len(joined))

    def _clean(o):
        if isinstance(o, dict):  return {k: _clean(v) for k, v in o.items()}
        if isinstance(o, list):  return [_clean(v) for v in o]
        if isinstance(o, float) and (math.isnan(o) or math.isinf(o)): return None
        if isinstance(o, (np.floating,)):
            x = float(o); return None if (math.isnan(x) or math.isinf(x)) else x
        if isinstance(o, (np.integer,)):  return int(o)
        return o

    payload = {
        "updated":      datetime.now().isoformat(),
        "data_range":   {"start": str(joined.index.min().date()), "end": str(joined.index.max().date())},
        "total_days":   total_days,
        "state_day_counts": {k: int(v) for k, v in state_n.items()},
        "caption":      ("Conditional scores ≈ unconditional until ~250 regime-days "
                          "accumulate in each cell. Backwardation has handful-per-year "
                          "n; shrunk conditional collapses to unconditional in thin "
                          "cells. This is the honest behaviour, not a bug."),
        "sleeves":      conditional,
        "shrinkage_method": "James-Stein toward unconditional mean; weight = "
                            "se²/(se² + τ²) with floor τ²=max(1e-8, |unc|·0.001).",
        "no_lookahead": ("State at close t-1 applied to return at session t. "
                          "Backtest never lets a same-day trade use the same day's close."),
    }

    out = DATA / "regime_conditional_scores.json"
    with open(out, "w") as f:
        json.dump(_clean(payload), f, indent=2, allow_nan=False)

    print(f"\n  saved → {out}")
    print(f"  total regime-days: {total_days}")
    print(f"  by state: {state_n}")
    print()
    print("  Sleeve · State sample table (annualized return, shrunk):")
    for s in ["1_cap_pres", "2_balanced", "3_aggressive", "4_tactical"]:
        line = f"    {s:14s}"
        for st in state_list:
            cell = conditional[s]["per_state"][st]
            n = cell["n"]
            sr = cell["shrunk_ann_return"]
            line += f"  {st[:6]}: {(sr*100):+5.1f}% (n={n:4d}, w={cell['shrinkage_weight']:.2f})"
        print(line)


if __name__ == "__main__":
    main()
