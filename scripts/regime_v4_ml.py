"""
EWS v4 — Graduated drawdown prediction with proper time-series CV.

Instead of one binary target (≥10% DD / 60d, ~7 events in 16y — useless for ML),
predict a SPECTRUM of forward drawdown severity:

  Thresholds:  3%, 5%, 7%, 10%, 15%
  Horizons:    20, 40, 60 trading days

The sweet spot is ≥5% / 40d — hundreds of events, real ML territory, matches
monthly rebalancing cadence.

Pipeline:
  1. Compute all 15 binary targets + continuous max_dd_40
  2. Time-series CV (5 splits, 20-day purge gap) for each target
  3. Train 5 methods per target: Logistic+PC, ElasticNet, RF, GB, equal-weight baseline
  4. Pick winning method per (threshold, horizon)
  5. Calibrate ≥5%/40d probabilities via Platt scaling
  6. Produce daily P(≥X% / Nd) for the production thresholds

Outputs:
  data/forward_drawdown_targets.parquet
  data/v4_model_results.json
  data/v4_calibration.json
  data/regime_v4_daily.csv
"""
from __future__ import annotations
import json, sys, warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import roc_auc_score, brier_score_loss

warnings.filterwarnings("ignore")

REPO   = Path(__file__).resolve().parent.parent
DATA   = REPO / "data"
SOURCE = DATA / "source"

THRESHOLDS = [0.03, 0.05, 0.07, 0.10, 0.15]
HORIZONS   = [20, 40, 60]
PRODUCTION_TARGET = (0.05, 40)          # the one we calibrate and ship
PCA_VAR    = 0.85
CV_SPLITS  = 5
PURGE_DAYS = 20
RANDOM_STATE = 42


# ====================================================================
# 1. Forward drawdown targets (5 × 3 = 15 binary + 1 continuous)
# ====================================================================
def compute_targets(spx: pd.Series) -> pd.DataFrame:
    """For each day t, max_dd_N = min(spx[t+1:t+N+1]) / spx[t] - 1."""
    vals = spx.values
    n = len(vals)
    cols = {}
    # Continuous max_dd per horizon
    for N in HORIZONS:
        max_dd = np.full(n, np.nan)
        for i in range(n - 1):
            end = min(i + N + 1, n)
            future = vals[i + 1:end]
            if future.size > 0:
                max_dd[i] = future.min() / vals[i] - 1
        cols[f"max_dd_{N}"] = max_dd
    df = pd.DataFrame(cols, index=spx.index)
    # Binary thresholds
    for thr in THRESHOLDS:
        for N in HORIZONS:
            df[f"y_{int(thr*100)}_{N}"] = (df[f"max_dd_{N}"] <= -thr).astype(float)
    # NaN-out the binary targets where max_dd is NaN
    for thr in THRESHOLDS:
        for N in HORIZONS:
            df.loc[df[f"max_dd_{N}"].isna(), f"y_{int(thr*100)}_{N}"] = np.nan
    return df


# ====================================================================
# 2. Time-series CV
# ====================================================================
def ts_cv_auc(X: pd.DataFrame, y: pd.Series, fit_predict_fn,
              n_splits: int = CV_SPLITS, gap: int = PURGE_DAYS) -> tuple[float, float, list]:
    """Expanding-window time-series CV with purge gap. fit_predict_fn(X_tr, y_tr, X_te) → probs."""
    tscv = TimeSeriesSplit(n_splits=n_splits, gap=gap)
    aucs = []
    for tr_idx, te_idx in tscv.split(X):
        X_tr, X_te = X.iloc[tr_idx], X.iloc[te_idx]
        y_tr, y_te = y.iloc[tr_idx], y.iloc[te_idx]
        if y_tr.sum() < 5 or y_te.sum() < 1 or y_te.sum() == len(y_te):
            continue
        try:
            probs = fit_predict_fn(X_tr, y_tr, X_te)
            aucs.append(float(roc_auc_score(y_te, probs)))
        except Exception as e:
            print(f"    skip split: {e}", file=sys.stderr)
    if not aucs:
        return float("nan"), float("nan"), []
    return float(np.mean(aucs)), float(np.std(aucs)), aucs


# ====================================================================
# 3. Method definitions (each returns fit_predict_fn)
# ====================================================================
def make_logistic_pc(n_components):
    def f(X_tr, y_tr, X_te):
        scaler = StandardScaler()
        X_tr_s = scaler.fit_transform(X_tr)
        X_te_s = scaler.transform(X_te)
        pca = PCA(n_components=min(n_components, X_tr_s.shape[1]))
        X_tr_pc = pca.fit_transform(X_tr_s)
        X_te_pc = pca.transform(X_te_s)
        m = LogisticRegression(class_weight="balanced", penalty="l2", C=1.0,
                               max_iter=2000, random_state=RANDOM_STATE)
        m.fit(X_tr_pc, y_tr.values)
        return m.predict_proba(X_te_pc)[:, 1]
    return f

def make_elastic_net():
    def f(X_tr, y_tr, X_te):
        scaler = StandardScaler()
        X_tr_s = scaler.fit_transform(X_tr)
        X_te_s = scaler.transform(X_te)
        m = SGDClassifier(loss="log_loss", penalty="elasticnet", l1_ratio=0.5,
                          alpha=0.001, class_weight="balanced", max_iter=5000,
                          random_state=RANDOM_STATE)
        m.fit(X_tr_s, y_tr.values)
        d = m.decision_function(X_te_s)
        return 1.0 / (1.0 + np.exp(-d))  # logistic squash
    return f

def make_random_forest():
    def f(X_tr, y_tr, X_te):
        scaler = StandardScaler()
        X_tr_s = scaler.fit_transform(X_tr)
        X_te_s = scaler.transform(X_te)
        # With more events, we can be less conservative
        m = RandomForestClassifier(n_estimators=400, max_depth=5,
                                   min_samples_leaf=30, class_weight="balanced",
                                   random_state=RANDOM_STATE, n_jobs=-1)
        m.fit(X_tr_s, y_tr.values)
        return m.predict_proba(X_te_s)[:, 1]
    return f

def make_gradient_boost():
    def f(X_tr, y_tr, X_te):
        scaler = StandardScaler()
        X_tr_s = scaler.fit_transform(X_tr)
        X_te_s = scaler.transform(X_te)
        m = GradientBoostingClassifier(n_estimators=300, max_depth=3,
                                       min_samples_leaf=30, learning_rate=0.05,
                                       subsample=0.8, random_state=RANDOM_STATE)
        m.fit(X_tr_s, y_tr.values)
        return m.predict_proba(X_te_s)[:, 1]
    return f

def make_equal_weight():
    def f(X_tr, y_tr, X_te):
        return X_te.mean(axis=1).values
    return f


# ====================================================================
# 4. Refit-on-full + calibrate the winner for the production target
# ====================================================================
def fit_and_calibrate_winner(X: pd.DataFrame, y: pd.Series, winner: str,
                              n_components: int):
    """Refit the winning method on all data with isotonic calibration.
       Returns (calibrator, scaler, pca, equal_weight_isotonic_fallback) tuple.
       The fallback is used when CalibratedClassifierCV fails on a sparse target."""
    from sklearn.isotonic import IsotonicRegression
    scaler = StandardScaler()
    X_s = scaler.fit_transform(X)
    pca = None
    base = None

    if winner == "logistic_pc":
        pca = PCA(n_components=min(n_components, X_s.shape[1]))
        X_in = pca.fit_transform(X_s)
        base = LogisticRegression(class_weight="balanced", C=1.0, max_iter=2000,
                                  random_state=RANDOM_STATE)
    elif winner == "elastic_net":
        X_in = X_s
        base = SGDClassifier(loss="log_loss", penalty="elasticnet", l1_ratio=0.5,
                             alpha=0.001, class_weight="balanced",
                             max_iter=5000, random_state=RANDOM_STATE)
    elif winner == "random_forest":
        X_in = X_s
        base = RandomForestClassifier(n_estimators=400, max_depth=5,
                                      min_samples_leaf=30, class_weight="balanced",
                                      random_state=RANDOM_STATE, n_jobs=-1)
    elif winner == "gradient_boost":
        X_in = X_s
        base = GradientBoostingClassifier(n_estimators=300, max_depth=3,
                                          min_samples_leaf=30, learning_rate=0.05,
                                          subsample=0.8, random_state=RANDOM_STATE)

    if base is not None:
        try:
            cv = TimeSeriesSplit(n_splits=5, gap=PURGE_DAYS)
            calibrator = CalibratedClassifierCV(base, method="isotonic", cv=cv)
            calibrator.fit(X_in, y.values)
            return ("model", calibrator, scaler, pca)
        except Exception as e:
            print(f"    calibrator fit failed ({e}), falling back to isotonic-on-equal-weight",
                  file=sys.stderr)

    # equal_weight path (or fallback): isotonic-calibrate the X.mean predictions
    raw = X.mean(axis=1).values
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(raw, y.values)
    return ("equal_iso", iso, None, None)


def predict_calibrated(calibrated, X: pd.DataFrame) -> np.ndarray:
    """`calibrated` is the tuple returned by fit_and_calibrate_winner."""
    if calibrated is None: return X.mean(axis=1).values
    kind = calibrated[0]
    if kind == "model":
        _, calibrator, scaler, pca = calibrated
        X_s = scaler.transform(X)
        X_in = pca.transform(X_s) if pca is not None else X_s
        return calibrator.predict_proba(X_in)[:, 1]
    if kind == "equal_iso":
        _, iso, _, _ = calibrated
        return iso.predict(X.mean(axis=1).values)
    return X.mean(axis=1).values


# ====================================================================
# 5. Reliability diagram bins (for calibration verification)
# ====================================================================
def reliability_bins(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> list[dict]:
    """Bin predictions and report (mean predicted, observed frequency, n)."""
    edges = np.linspace(0, 1, n_bins + 1)
    rows = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (y_prob >= lo) & (y_prob < hi if i < n_bins - 1 else y_prob <= hi)
        n = int(mask.sum())
        if n == 0:
            continue
        rows.append({
            "bin":            i,
            "lo":             round(float(lo), 3),
            "hi":             round(float(hi), 3),
            "predicted_mean": round(float(y_prob[mask].mean()), 4),
            "observed_freq":  round(float(y_true[mask].mean()), 4),
            "n":              n,
        })
    return rows


# ====================================================================
# 6. Graduated regime classification
# ====================================================================
def graduated_regime(p_5_40: float) -> str:
    if p_5_40 < 0.25: return "DEPLOY"
    if p_5_40 < 0.45: return "CAUTIOUS"
    if p_5_40 < 0.65: return "DEFENSIVE"
    return "CRISIS"


# ====================================================================
# Main
# ====================================================================
def main():
    print("Loading inputs...")
    risk = pd.read_parquet(DATA / "regime_v2_risk_scores.parquet")
    risk.index = pd.to_datetime(risk.index)
    vol = pd.read_parquet(SOURCE / "vol_indicators.parquet")
    vol.index = pd.to_datetime(vol.index)
    spx = vol["spx"].dropna()
    print(f"  risk: {risk.shape}, spx: {len(spx)} days")

    print("\nComputing 15 binary targets + 3 continuous max_dd series...")
    targets = compute_targets(spx)
    targets.to_parquet(DATA / "forward_drawdown_targets.parquet")
    print(f"  saved forward_drawdown_targets.parquet ({targets.shape})")

    print("\nBase rates (per target):")
    base_rates = {}
    print(f"  {'threshold':>10s} {'horizon':>8s}  {'n_pos':>7s}  {'n_total':>7s}  {'rate':>6s}")
    for thr in THRESHOLDS:
        for N in HORIZONS:
            col = f"y_{int(thr*100)}_{N}"
            ser = targets[col].dropna()
            n_pos = int(ser.sum())
            base_rates[col] = {"n_positive": n_pos, "n_total": len(ser),
                                "rate": round(float(ser.mean()), 4)}
            print(f"  ≥{thr*100:>5.0f}%   {N:>5}d  {n_pos:>7d}  {len(ser):>7d}  {ser.mean()*100:>5.1f}%")

    # ---- Align with risk scores ----
    common = risk.dropna(how="all").index.intersection(targets.index)
    X_full = risk.loc[common].fillna(0.5)
    print(f"\nAligned sample: {len(X_full)} days, {X_full.shape[1]} indicators")

    # n_components from full sample PCA (used inside CV methods)
    pca_full = PCA().fit(StandardScaler().fit_transform(X_full))
    cumvar = np.cumsum(pca_full.explained_variance_ratio_)
    n_components = int(np.argmax(cumvar >= PCA_VAR) + 1)
    print(f"PCA: {n_components} components for {PCA_VAR*100:.0f}% variance\n")

    # ---- Time-series CV across (method, threshold, horizon) ----
    methods = {
        "equal_weight":   make_equal_weight(),
        "elastic_net":    make_elastic_net(),
        "logistic_pc":    make_logistic_pc(n_components),
        "random_forest":  make_random_forest(),
        "gradient_boost": make_gradient_boost(),
    }

    all_results = {}      # {target_col: {method: {mean, std, fold_aucs}}}
    print("Running time-series CV (5 splits, 20d purge gap)...")
    for thr in THRESHOLDS:
        for N in HORIZONS:
            col = f"y_{int(thr*100)}_{N}"
            y = targets.loc[common, col]
            mask = y.notna()
            Xc, yc = X_full[mask], y[mask]
            if yc.sum() < 10:
                # Not enough events even for CV
                continue
            print(f"\n  Target: ≥{thr*100:.0f}% / {N}d  ({int(yc.sum())} positives in {len(yc)})")
            tgt_results = {}
            for mname, fn in methods.items():
                m_, s_, fold = ts_cv_auc(Xc, yc, fn)
                tgt_results[mname] = {"mean_auc": round(m_, 4),
                                      "std_auc":  round(s_, 4),
                                      "fold_aucs": [round(x, 4) for x in fold]}
                print(f"    {mname:<16s} AUC = {m_:.4f} ± {s_:.4f}  ({len(fold)} folds)")
            # Winner = max mean_auc (skipping NaN)
            winner = max(tgt_results.items(),
                         key=lambda kv: -1 if np.isnan(kv[1]["mean_auc"]) else kv[1]["mean_auc"])[0]
            tgt_results["_winner"] = winner
            all_results[col] = tgt_results

    # ---- Calibrate winner for the production target ≥5% / 40d ----
    prod_col = f"y_{int(PRODUCTION_TARGET[0]*100)}_{PRODUCTION_TARGET[1]}"
    print(f"\n=== Production target: {prod_col} ===")
    prod_winner = all_results.get(prod_col, {}).get("_winner", "equal_weight")
    print(f"  Winning method: {prod_winner}")

    y_prod = targets.loc[common, prod_col]
    mask = y_prod.notna()
    X_train, y_train = X_full[mask], y_prod[mask]
    print(f"  Training on {len(X_train)} days, {int(y_train.sum())} positives")

    prod_cal = fit_and_calibrate_winner(X_train, y_train, prod_winner, n_components)

    # Predicted probabilities for the FULL sample
    p_prod = predict_calibrated(prod_cal, X_train)
    # Reliability for calibration verification
    rel = reliability_bins(y_train.values, p_prod, n_bins=10)
    brier = float(brier_score_loss(y_train.values, p_prod))
    print(f"  Brier score: {brier:.4f}  (lower is better; baseline = {(y_train.mean()*(1-y_train.mean())):.4f})")
    print(f"  Reliability bins (predicted vs observed):")
    for r in rel:
        flag = "OK " if abs(r["predicted_mean"] - r["observed_freq"]) < 0.05 else "off"
        print(f"    bin [{r['lo']:.1f}-{r['hi']:.1f}] n={r['n']:>5d}  pred {r['predicted_mean']:.3f}  obs {r['observed_freq']:.3f}  {flag}")

    cal_payload = {
        "production_target":       prod_col,
        "winning_method":          prod_winner,
        "calibration_method":      "isotonic",
        "brier_score":             round(brier, 4),
        "brier_baseline":          round(float(y_train.mean() * (1 - y_train.mean())), 4),
        "reliability_bins":        rel,
    }
    with open(DATA / "v4_calibration.json", "w") as f:
        json.dump(cal_payload, f, indent=2)

    # ---- Daily probabilities for ALL production thresholds ----
    print("\nProducing daily P(dd ≥ X / Nd) for the calibrated winning model + the other targets...")
    daily_probs = pd.DataFrame(index=X_full.index)
    daily_probs["p_5_40_calibrated"] = predict_calibrated(prod_cal, X_full)
    # For non-calibrated thresholds, refit the winner of each target on FULL data and predict
    for col, res in all_results.items():
        if col == prod_col: continue   # already done with calibration
        w = res.get("_winner", "equal_weight")
        y_c = targets.loc[common, col]
        mask = y_c.notna()
        Xt, yt = X_full[mask], y_c[mask]
        if yt.sum() < 5 or len(yt) - yt.sum() < 5:
            continue
        try:
            cal_t = fit_and_calibrate_winner(Xt, yt, w, n_components)
            daily_probs[f"p_{col[2:]}_{w}"] = predict_calibrated(cal_t, X_full)
        except Exception as e:
            print(f"    skip {col}: {e}", file=sys.stderr)
    # Graduated classification driven by calibrated p_5_40
    daily_probs["graduated_regime"] = daily_probs["p_5_40_calibrated"].apply(graduated_regime)
    daily_probs.index.name = "date"
    daily_probs.to_csv(DATA / "regime_v4_daily.csv")
    print(f"  saved regime_v4_daily.csv ({daily_probs.shape})")

    # ---- Scoring params for the daily light scorer (AUDIT FIX 2a) ----
    # All displayed columns are equal-weight winners: isotonic(row_mean).
    # IsotonicRegression.predict(out_of_bounds='clip') == np.interp over
    # (X_thresholds_, y_thresholds_) with edge clipping, so dumping the
    # knots lets score_regime_v4_daily.py extend the CSV daily with numpy
    # only. This full script remains the MONTHLY recalibration job.
    scoring_params = {
        "fitted_at":  datetime.now().isoformat(),
        "train_end":  str(X_full.index.max().date()),
        "graduated_thresholds": {"deploy_lt": 0.25, "cautious_lt": 0.45, "defensive_lt": 0.65},
        "feature_note": "input = mean over risk-score columns of regime_v2_risk_scores.parquet, NaN→0.5",
        "targets": {},
    }
    def _dump_iso(out_col, cal):
        if cal is not None and cal[0] == "equal_iso":
            iso = cal[1]
            scoring_params["targets"][out_col] = {
                "x": [round(float(v), 6) for v in iso.X_thresholds_],
                "y": [round(float(v), 6) for v in iso.y_thresholds_],
            }
    _dump_iso("p_5_40_calibrated", prod_cal)
    for col, res in all_results.items():
        if col == prod_col: continue
        w = res.get("_winner", "equal_weight")
        if w != "equal_weight": continue
        out_col = f"p_{col[2:]}_{w}"
        if out_col in daily_probs.columns and out_col not in scoring_params["targets"]:
            y_c = targets.loc[common, col]; mask = y_c.notna()
            try:
                cal_t = fit_and_calibrate_winner(X_full[mask], y_c[mask], w, n_components)
                _dump_iso(out_col, cal_t)
            except Exception as e:
                print(f"    knot-dump skip {out_col}: {e}", file=sys.stderr)
    with open(DATA / "v4_scoring_params.json", "w") as f:
        json.dump(scoring_params, f, indent=2)
    print(f"  saved v4_scoring_params.json ({len(scoring_params['targets'])} isotonic curves)")

    # ---- Print regime distribution ----
    print(f"\nGraduated regime distribution (calibrated P(≥5%/40d)):")
    counts = daily_probs["graduated_regime"].value_counts()
    for k in ["DEPLOY", "CAUTIOUS", "DEFENSIVE", "CRISIS"]:
        n = int(counts.get(k, 0))
        print(f"  {k:<10s} {n:>5d} days  ({n/len(daily_probs)*100:>5.1f}%)")

    # ---- Save full results ----
    summary = {
        "production_target":   prod_col,
        "winning_method":      prod_winner,
        "n_components_pca":    n_components,
        "cv_splits":           CV_SPLITS,
        "purge_gap_days":      PURGE_DAYS,
        "base_rates":          base_rates,
        "cv_results":          all_results,
        "calibration":         {"method": "isotonic", "brier": round(brier, 4)},
        "regime_distribution": {k: int(counts.get(k, 0)) for k in ["DEPLOY","CAUTIOUS","DEFENSIVE","CRISIS"]},
        "thresholds":          THRESHOLDS,
        "horizons":            HORIZONS,
    }
    with open(DATA / "v4_model_results.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)

    # ---- Latest snapshot ----
    last = daily_probs.iloc[-1]
    print(f"\n=== LATEST ({daily_probs.index[-1].date()}) ===")
    print(f"  Calibrated P(≥5% / 40d) = {last['p_5_40_calibrated']:.3f}")
    print(f"  Regime: {last['graduated_regime']}")

    print("\nDone. See data/v4_model_results.json for the full summary.")


if __name__ == "__main__":
    main()
