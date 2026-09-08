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
    from trading_calendar import require_trading_day  # SEPT AUDIT [2.4]
    require_trading_day("score_regime_v4_daily")
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
    # SEPT AUDIT [7]: the raw (pre-calibration) score — the isotonic input,
    # i.e. the equal-weight mean of the risk scores — persisted alongside the
    # stepped calibrated probability so the dashboard can show both.
    block["raw_score"] = means
    # Order 9-Sept B1: model identity travels with the data. The id is keyed
    # to the calibration file's as_of + winning method.
    try:
        _cal = json.load(open(DATA / "v4_calibration.json"))
        model_version = f"v4-{str(_cal.get('as_of') or '')[:10] or 'unknown'}-{_cal.get('winning_method', 'unknown')}"
    except Exception:
        model_version = "v4-unknown"
    block["model_version"] = model_version
    block.index.name = "date"

    n_appended = len([d for d in block.index if d not in existing.index])
    # SEPT AUDIT [1.4]/[7]: the model-winner columns (p_7_60_logistic_pc and
    # the p_15_* elastic_net / logistic_pc) are produced ONLY by the monthly
    # regime_v4_ml run. This trailing-window rescore used to blank them on
    # the last 5 rows every night, so they were ALWAYS empty for the latest
    # sessions — silently, and unrelated to any feed. Preserve the monthly
    # values instead; rows the monthly never covered stay NaN (honest), and
    # v4_delta_attribution.json records model_cols_scored_at (their vintage).
    all_cols = list(dict.fromkeys(list(existing.columns) + list(block.columns)))
    block = block.reindex(columns=all_cols)
    for c in all_cols:
        if c not in new_rows and c not in ("graduated_regime", "raw_score") and c in existing.columns:
            block[c] = existing[c].reindex(block.index)
    combined = pd.concat([kept.reindex(columns=all_cols), block])
    combined.index.name = "date"
    # Backfill raw_score for every historical row: the equal-weight mean is
    # model-state independent and the risk parquet holds the full history.
    combined["raw_score"] = row_mean.reindex(pd.to_datetime(combined.index)).values
    # B1 backfill: rows without a model_version were produced by the calibration
    # currently in force (the monthly run rewrites the whole series), so they
    # carry its id — never a different version's id for values it did not produce.
    if "model_version" not in combined.columns:
        combined["model_version"] = None
    combined["model_version"] = combined["model_version"].where(combined["model_version"].notna(), model_version)
    combined.to_csv(csv_p)

    # ── JULY AUDIT FIX 4a: delta attribution for the production probability ──
    # p = iso(mean of 23 risk scores). Finite-difference: re-score today
    # substituting each feature's YESTERDAY value one at a time;
    # contribution_i = p_today − p_counterfactual_i. Because isotonic is a
    # step function the contributions don't sum exactly to Δp — the residual
    # is reported honestly, never hidden.
    try:
        risk_f = risk.fillna(0.5)
        if len(risk_f) >= 2:
            x_t, x_y = risk_f.iloc[-1], risk_f.iloc[-2]
            d_t, d_y = risk_f.index[-1], risk_f.index[-2]
            n = len(x_t)
            knots = params["targets"]["p_5_40_calibrated"]
            p_t = float(iso_predict(np.array([x_t.mean()]), knots)[0])
            p_y = float(iso_predict(np.array([x_y.mean()]), knots)[0])
            contribs = []
            for col in risk_f.columns:
                cf_mean = x_t.mean() - (x_t[col] - x_y[col]) / n
                p_cf = float(iso_predict(np.array([cf_mean]), knots)[0])
                contribs.append({"feature": col,
                                  "delta_feature": round(float(x_t[col] - x_y[col]), 4),
                                  "contribution_pp": round((p_t - p_cf) * 100, 2)})
            contribs.sort(key=lambda c: -abs(c["contribution_pp"]))
            explained = sum(c["contribution_pp"] for c in contribs)
            residual = round((p_t - p_y) * 100 - explained, 2)
            # SEPT AUDIT [1.4]/[7]: vintage of the monthly model-winner columns
            model_cols = [c for c in combined.columns
                          if c.endswith(("_logistic_pc", "_elastic_net"))]
            _mc_last = None
            for c in model_cols:
                nn = combined[c].dropna()
                if len(nn):
                    _mc_last = max(_mc_last or "", str(nn.index.max()))
            attr = {
                "as_of": d_t.strftime("%Y-%m-%d"),
                "session_date": d_t.strftime("%Y-%m-%d"),
                "cadence": "daily",
                "prev":  d_y.strftime("%Y-%m-%d"),
                "raw_score_today": round(float(x_t.mean()), 4),
                "raw_score_prev":  round(float(x_y.mean()), 4),
                "model_cols_scored_at": _mc_last,
                "model_cols_note": ("p_*_logistic_pc / p_*_elastic_net are produced only by the "
                                    "monthly regime_v4_ml run; the nightly rescore preserves "
                                    "them (it used to blank the last 5 rows) — they advance monthly"),
                "p_today": round(p_t, 4), "p_prev": round(p_y, 4),
                "delta_pp": round((p_t - p_y) * 100, 2),
                "top3": contribs[:3],
                "all": contribs,
                "residual_pp": residual,
                "method": ("finite difference through the isotonic curve, one feature "
                            "at a time; contributions approximate (isotonic is piecewise-"
                            "constant) — residual reported, not hidden"),
            }
            with open(DATA / "v4_delta_attribution.json", "w") as f:
                json.dump(attr, f, indent=2)
            top = " · ".join(f"{c['feature']} {c['contribution_pp']:+.1f}pp" for c in contribs[:3])
            print(f"  Δp(5/40) {attr['delta_pp']:+.2f}pp — moved by: {top} (residual {residual:+.2f}pp)")
    except Exception as e:
        print(f"  warn delta attribution: {e}", file=sys.stderr)
    for d in block.index:
        print(f"  appended {d}: p_5_40 = {block.loc[d, 'p_5_40_calibrated']:.4f} "
              f"→ {block.loc[d, 'graduated_regime']}")
    print(f"  saved regime_v4_daily.csv ({len(combined)} rows, through {combined.index.max()})")
    print(f"  knots fitted_at {params['fitted_at'][:10]} / train_end {params['train_end']} — "
          f"full recalibration runs monthly")


if __name__ == "__main__":
    main()
