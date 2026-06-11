"""
score_regime_v4_daily.py — light daily v4 scorer (AUDIT FIX 2a).

Extends data/regime_v4_daily.csv with rows for any new sessions, using the
isotonic curves saved by regime_v4_ml.py in data/v4_scoring_params.json.
numpy-only: sklearn's IsotonicRegression.predict(out_of_bounds='clip') is
exactly np.interp over (X_thresholds_, y_thresholds_) with edge clipping,
so output is bit-compatible with the full pipeline for every equal-weight
column. The 3 model-winner columns (p_15_* elastic_net / logistic_pc) are
left empty on appended rows — they are not displayed; the monthly
recalibration (full regime_v4_ml.py run in monthly_rebalance.yml) refreshes
the entire CSV including those.

Why this exists: regime_v4_daily.csv froze at its last manual run while the
dashboard headline kept quoting it — the daily pipeline never computed v4
because CI lacked scikit-learn. This scorer costs <1s and zero new deps.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"


def graduated_regime(p: float, th: dict) -> str:
    if p < th["deploy_lt"]:    return "DEPLOY"
    if p < th["cautious_lt"]:  return "CAUTIOUS"
    if p < th["defensive_lt"]: return "DEFENSIVE"
    return "CRISIS"


def iso_predict(x: np.ndarray, knots: dict) -> np.ndarray:
    """Bit-compatible IsotonicRegression.predict with out_of_bounds='clip'."""
    xs, ys = np.asarray(knots["x"]), np.asarray(knots["y"])
    return np.interp(np.clip(x, xs[0], xs[-1]), xs, ys)


def main():
    params_p = DATA / "v4_scoring_params.json"
    csv_p    = DATA / "regime_v4_daily.csv"
    if not params_p.exists():
        print("  v4_scoring_params.json missing — run regime_v4_ml.py once to "
              "generate calibration knots. Skipping daily v4 score.")
        return
    params = json.load(open(params_p))
    th = params["graduated_thresholds"]

    risk = pd.read_parquet(DATA / "regime_v2_risk_scores.parquet")
    risk.index = pd.to_datetime(risk.index)
    # Match training preprocessing exactly: NaN → 0.5, mean over all columns.
    row_mean = risk.fillna(0.5).mean(axis=1)
    # Only rows where at least MIN indicators had real data
    valid = risk.notna().sum(axis=1) >= 12
    row_mean = row_mean[valid]

    existing = pd.read_csv(csv_p, index_col="date") if csv_p.exists() else pd.DataFrame()
    existing.index = existing.index.astype(str)

    # Trailing-window OVERWRITE, not append-only: recompute the last 5 existing
    # rows plus anything new. Idempotent (same knots → same values), and it
    # self-corrects any partial-session row that slipped in from an intraday
    # manual run — the nightly run replaces it with the settled close.
    if len(existing) >= 5:
        cutoff = existing.index.sort_values()[-5]
    else:
        cutoff = "1900-01-01"
    recompute_dates = [d for d in row_mean.index if d.strftime("%Y-%m-%d") >= cutoff]
    if not recompute_dates:
        print(f"  regime_v4_daily.csv already current — nothing to score")
        return
    kept = existing[existing.index < cutoff]

    new_rows = {}
    means = row_mean.loc[recompute_dates].values
    for out_col, knots in params["targets"].items():
        new_rows[out_col] = iso_predict(means, knots)
    block = pd.DataFrame(new_rows, index=[d.strftime("%Y-%m-%d") for d in recompute_dates])
    block["graduated_regime"] = [graduated_regime(p, th) for p in block["p_5_40_calibrated"]]
    block.index.name = "date"

    n_appended = len([d for d in block.index if d not in existing.index])
    # Align columns to existing CSV (model-winner cols left NaN on rescored rows)
    combined = pd.concat([kept, block.reindex(columns=kept.columns if len(kept) else block.columns)])
    combined.index.name = "date"
    combined.to_csv(csv_p)
    for d in block.index:
        print(f"  appended {d}: p_5_40 = {block.loc[d, 'p_5_40_calibrated']:.4f} "
              f"→ {block.loc[d, 'graduated_regime']}")
    print(f"  saved regime_v4_daily.csv ({len(combined)} rows, through {combined.index.max()})")
    print(f"  knots fitted_at {params['fitted_at'][:10]} / train_end {params['train_end']} — "
          f"full recalibration runs monthly")


if __name__ == "__main__":
    main()
