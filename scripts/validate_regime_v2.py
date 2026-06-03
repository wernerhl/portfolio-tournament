"""
Validate the v2 regime model: AUC vs target, lead times per drawdown, divergence test.

Targets the same task as v1 ("≥10% SPX drawdown trough within 60 trading days"),
plus an event study on the divergence signal.

Outputs:
  data/regime_v2_auc.json            v1 / R_lead / R_full / per-indicator AUCs
  data/regime_v2_leadtimes.csv       per-episode lead time table
  data/regime_v2_divergence_test.json divergence > +0.15 → 40-day DD event study
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

REPO   = Path(__file__).resolve().parent.parent
DATA   = REPO / "data"
SOURCE = DATA / "source"


def build_v1_R_t() -> pd.Series:
    """Reproduce v1's 12-indicator equal-weight R_t over the full sample."""
    from scipy.stats import norm
    vol  = pd.read_parquet(SOURCE / "vol_indicators.parquet"); vol.index = pd.to_datetime(vol.index)
    vold = pd.read_parquet(SOURCE / "vol_derived.parquet");    vold.index = pd.to_datetime(vold.index)
    sect = pd.read_parquet(SOURCE / "sector_etfs.parquet");    sect.index = pd.to_datetime(sect.index)
    def_cyc = (sect["xlu"] + sect["xlp"]) / (sect["xlk"] + sect["xly"])

    spec = [
        ("vix",          vol["vix"],          "higher"),
        ("vvix",         vol["vvix"],         "higher"),
        ("skew",         vol["skew"],         "lower"),
        ("realized_vol", vold["spx_realized_vol_20d"], "higher"),
        ("spx_ret_60d",  vold["spx_return_60d"], "lower"),
        ("spx_drawdown", vold["spx_drawdown"], "lower"),
        ("hyg_lqd",      vold["hyg_lqd_ratio"], "lower"),
        ("gold_spx",     vold["gold_spx"],    "higher"),
        ("tlt_spx",      vold["tlt_spx"],     "higher"),
        ("def_cyc",      def_cyc,             "higher"),
        ("oil_60d_vel",  vold["oil_60d_vel"], "higher"),
        ("dxy",          vol["dxy"],          "higher"),
    ]
    idx = pd.date_range(min(s.index.min() for _,s,_ in spec),
                        max(s.index.max() for _,s,_ in spec), freq="B")
    df = pd.DataFrame(index=idx)
    for name, s, _ in spec: df[name] = s.reindex(idx).ffill()
    z_all = pd.DataFrame(index=idx)
    for name, _, direction in spec:
        m  = df[name].rolling(252, min_periods=60).mean()
        sd = df[name].rolling(252, min_periods=60).std().replace(0, np.nan)
        z  = (df[name] - m) / sd
        if direction == "lower": z = -z
        z_all[name] = norm.cdf(z)
    return z_all.mean(axis=1).rename("R_v1")


def build_target(spx: pd.Series, lookahead_days: int = 60, dd_threshold: float = -0.10) -> pd.Series:
    """1 if min(SPX drawdown) over [t, t+lookahead] <= -10%."""
    run_max = spx.cummax()
    dd = (spx - run_max) / run_max
    # rolling min over the FORWARD window
    forward_min = dd.rolling(lookahead_days, min_periods=1).min().shift(-lookahead_days + 1)
    return (forward_min <= dd_threshold).astype(int)


def auc_of(series: pd.Series, target: pd.Series, label: str) -> float:
    common = series.dropna().index.intersection(target.dropna().index)
    if len(common) < 500:
        print(f"  {label}: insufficient data ({len(common)} obs)")
        return float("nan")
    y = target.loc[common].values
    s = series.loc[common].values
    if y.sum() < 10 or y.sum() == len(y):
        print(f"  {label}: degenerate target")
        return float("nan")
    return float(roc_auc_score(y, s))


def detect_dd_episodes(spx: pd.Series, threshold: float = -0.10) -> pd.DataFrame:
    """Detect non-overlapping ≥|threshold| drawdown episodes: (peak, trough, recovery)."""
    run_max = spx.cummax()
    dd = (spx - run_max) / run_max
    episodes = []
    i = 0
    while i < len(spx):
        # find next time dd crosses below threshold
        below = dd.iloc[i:][dd.iloc[i:] <= threshold]
        if below.empty: break
        first_below = below.index[0]
        # peak = running_max just before this point
        peak_val = run_max.loc[first_below]
        peak_date = (run_max.loc[:first_below] == peak_val).idxmax()
        # trough = min of dd until recovery
        # recovery = first time spx >= peak_val after first_below
        post = spx.loc[first_below:]
        recovery = post[post >= peak_val]
        if recovery.empty:
            # still drawing down — trough is min so far
            trough_date = post.idxmin()
            recovery_date = spx.index[-1]
        else:
            recovery_date = recovery.index[0]
            trough_date = post.loc[:recovery_date].idxmin()
        episodes.append({
            "peak_date": peak_date, "trough_date": trough_date, "recovery_date": recovery_date,
            "peak_val": float(peak_val), "trough_val": float(spx.loc[trough_date]),
            "drawdown_pct": round(float(spx.loc[trough_date] / peak_val - 1) * 100, 2),
        })
        i = spx.index.get_loc(recovery_date) + 1
    return pd.DataFrame(episodes)


def lead_time(R_t: pd.Series, threshold: float, peak_date: pd.Timestamp, max_look_back_days: int = 252) -> int | None:
    """Trading days between R_t first crossing `threshold` and the peak."""
    window = R_t.loc[max(R_t.index.min(), peak_date - pd.Timedelta(days=max_look_back_days*2)):peak_date]
    above = (window >= threshold)
    if not above.any(): return None
    first = above[above].index[0]
    return int(window.loc[first:peak_date].shape[0] - 1)


def main():
    print("Loading v2 regime + source data...")
    v2 = pd.read_csv(DATA / "regime_v2_daily.csv", index_col="date", parse_dates=["date"])
    risk = pd.read_parquet(DATA / "regime_v2_risk_scores.parquet")
    risk.index = pd.to_datetime(risk.index)
    vol = pd.read_parquet(SOURCE / "vol_indicators.parquet"); vol.index = pd.to_datetime(vol.index)
    spx = vol["spx"].dropna()
    print(f"  spx: {len(spx)} days  {spx.index[0].date()} → {spx.index[-1].date()}")

    print("\nReconstructing v1 R_t for comparison...")
    v1 = build_v1_R_t()

    print("Building target (≥10% drawdown within 60 trading days)...")
    target = build_target(spx, lookahead_days=60, dd_threshold=-0.10)
    print(f"  positive class share: {target.mean():.3f}")

    # === AUC table ===
    print("\n=== AUC vs target ===")
    aucs = {}
    aucs["v1_equal_weight_12"] = auc_of(v1, target, "v1 (12, equal)")
    aucs["v2_R_lead_9_fwd"]    = auc_of(v2["R_lead"].astype(float), target, "v2 R_lead")
    aucs["v2_R_full_18_tiered"]= auc_of(v2["R_full"].astype(float), target, "v2 R_full")
    print(f"  v1 12 equal-weight:        AUC = {aucs['v1_equal_weight_12']:.4f}")
    print(f"  v2 R_lead (9, Tier A):     AUC = {aucs['v2_R_lead_9_fwd']:.4f}")
    print(f"  v2 R_full (18, tiered):    AUC = {aucs['v2_R_full_18_tiered']:.4f}")

    # Per-indicator AUC
    print("\n=== Per-indicator AUC ===")
    per_ind = {}
    for col in risk.columns:
        per_ind[col] = auc_of(risk[col], target, col)
    per_ind_sorted = dict(sorted(per_ind.items(), key=lambda x: -x[1] if not np.isnan(x[1]) else 0))
    for k, v in per_ind_sorted.items():
        print(f"  {k:<18} AUC = {v:.4f}")

    # === Lead times per episode ===
    print("\n=== Drawdown episodes (≥10%) + lead times ===")
    episodes = detect_dd_episodes(spx, threshold=-0.10)
    print(f"  {len(episodes)} episodes detected")
    rows = []
    for _, ep in episodes.iterrows():
        peak = ep["peak_date"]
        rows.append({
            "peak_date":   peak.date(),
            "trough_date": ep["trough_date"].date(),
            "drawdown_pct": ep["drawdown_pct"],
            "lead_v1_at_0p50":     lead_time(v1, 0.50, peak),
            "lead_v1_at_0p70":     lead_time(v1, 0.70, peak),
            "lead_R_full_at_0p50": lead_time(v2["R_full"].astype(float), 0.50, peak),
            "lead_R_full_at_0p70": lead_time(v2["R_full"].astype(float), 0.70, peak),
            "lead_R_lead_at_0p55": lead_time(v2["R_lead"].astype(float), 0.55, peak),
            "lead_R_lead_at_0p75": lead_time(v2["R_lead"].astype(float), 0.75, peak),
        })
    lead_df = pd.DataFrame(rows)
    lead_df.to_csv(DATA / "regime_v2_leadtimes.csv", index=False)
    print(lead_df.to_string(index=False))

    # === Divergence event study ===
    print("\n=== Divergence event study ===")
    div = v2["divergence"].astype(float)
    # On days when divergence > +0.15, did SPX fall ≥5% in next 40 trading days?
    run_max = spx.cummax(); dd = (spx - run_max) / run_max
    forward_min_40 = dd.rolling(40, min_periods=1).min().shift(-39)
    y5 = (forward_min_40 <= -0.05).astype(int)
    common = div.dropna().index.intersection(y5.dropna().index)
    div_pos = (div.loc[common] > 0.15)
    p_cond = float(y5.loc[common][div_pos].mean()) if div_pos.sum() > 0 else float("nan")
    p_uncond = float(y5.loc[common].mean())
    div_rec = (div.loc[common] < -0.15)
    p_cond_rec = float(y5.loc[common][div_rec].mean()) if div_rec.sum() > 0 else float("nan")
    ds = {
        "target":                     "≥5% SPX drawdown trough within 40 trading days",
        "unconditional_prob":          round(p_uncond, 4),
        "P(target | divergence>+0.15)": round(p_cond, 4),
        "P(target | divergence<-0.15)": round(p_cond_rec, 4),
        "n_days_div_above_0p15":       int(div_pos.sum()),
        "n_days_div_below_neg_0p15":   int(div_rec.sum()),
        "n_days_total":                int(len(common)),
        "lift_above_unconditional":    round(p_cond - p_uncond, 4) if not np.isnan(p_cond) else None,
    }
    print(f"  unconditional P(≥5% DD/40d): {p_uncond:.3f}")
    print(f"  P(... | divergence > +0.15): {p_cond:.3f}  (lift {p_cond - p_uncond:+.3f})  on {ds['n_days_div_above_0p15']} days")
    print(f"  P(... | divergence < -0.15): {p_cond_rec:.3f}                on {ds['n_days_div_below_neg_0p15']} days")

    # === Save AUC json ===
    auc_payload = {
        "target":  "≥10% SPX drawdown trough within 60 trading days",
        "n_days":  int((target.notna() & v2["R_full"].notna()).sum()),
        "positive_class_share": round(float(target.mean()), 4),
        "composite": aucs,
        "per_indicator": {k: (round(v, 4) if not np.isnan(v) else None) for k, v in per_ind_sorted.items()},
        "comparison_summary": {
            "delta_R_full_vs_v1": round(aucs["v2_R_full_18_tiered"] - aucs["v1_equal_weight_12"], 4),
            "delta_R_lead_vs_v1": round(aucs["v2_R_lead_9_fwd"]    - aucs["v1_equal_weight_12"], 4),
        },
    }
    with open(DATA / "regime_v2_auc.json", "w") as f:
        json.dump(auc_payload, f, indent=2, default=str)
    with open(DATA / "regime_v2_divergence_test.json", "w") as f:
        json.dump(ds, f, indent=2, default=str)
    print("\nSaved regime_v2_auc.json, regime_v2_leadtimes.csv, regime_v2_divergence_test.json")


if __name__ == "__main__":
    main()
