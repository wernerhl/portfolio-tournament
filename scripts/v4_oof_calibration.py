#!/usr/bin/env python3
"""v4_oof_calibration.py — out-of-fold calibration evidence (order 9-Sept, B2).

Why: v4_calibration.json's reliability bins showed predicted mean == observed
frequency to four decimals in every bin. Isotonic regression produces exactly
that on its own training data; it is not evidence of calibration.

What: for the production target (>=5% drawdown within 40 sessions) and the
three contending methods (equal_weight, logistic_pc, elastic_net):
  * FOLDS — leave-one-crisis-out, extended to full coverage: every SPX
    drawdown episode [peak, recovery] from data/source/spx_drawdown_episodes.csv
    (deduped as regime_v3_ml does) is one fold, and every calm stretch between
    episodes is one fold, so every day sits in exactly one held-out fold.
    Training for a fold excludes the fold plus a symmetric purge of
    HORIZON + PURGE sessions (forward-looking labels overlap the boundary).
  * Per fold: fit the method on the training days, fit the isotonic
    calibrator on the TRAINING predictions, apply both to the held-out fold.
  * Assemble the out-of-fold series; report Brier and reliability bins —
    out-of-fold AND in-sample, labelled. Select the winner on out-of-fold
    Brier. If equal_weight still wins the switch stands; otherwise the
    production target must revert (recorded in the decision block).

Writes: v4_calibration.json (merged: evaluation, fold_definition, methods,
        out_of_fold / in_sample tables, decision), data/v4_oof_predictions.csv.
"""
from __future__ import annotations
import json, os, sys, warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.metrics import brier_score_loss
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")
REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
SOURCE = DATA / "source"

PROD_COL = "y_5_40"
HORIZON = 40
PURGE = 20
PCA_VAR = 0.85
RS = 42
METHODS = ("equal_weight", "logistic_pc", "elastic_net")


def load_episodes() -> pd.DataFrame:
    ep = pd.read_csv(SOURCE / "spx_drawdown_episodes.csv",
                     parse_dates=["peak_date", "trough_date", "recovery_date"])
    # dedupe as regime_v3_ml: episodes sharing a peak collapse to the deepest
    depth_col = next((c for c in ep.columns if "drawdown" in c.lower() or "depth" in c.lower()), None)
    if depth_col:
        ep = ep.sort_values(depth_col).drop_duplicates("peak_date", keep="first")
    else:
        ep = ep.sort_values("recovery_date").drop_duplicates("peak_date", keep="last")
    return ep.sort_values("peak_date").reset_index(drop=True)


def build_folds(index: pd.DatetimeIndex, episodes: pd.DataFrame) -> tuple[pd.Series, list[dict]]:
    """fold id per day: crisis episodes are folds; the calm stretches between
    them are folds too, so every day is held out exactly once."""
    fold = pd.Series(-1, index=index)
    meta = []
    k = 0
    cursor = index.min()
    for _, ep in episodes.iterrows():
        a, b = pd.Timestamp(ep["peak_date"]), pd.Timestamp(ep["recovery_date"])
        if pd.isna(b):
            b = pd.Timestamp(ep["trough_date"])
        if b < index.min() or a > index.max():
            continue
        calm = (fold.index >= cursor) & (fold.index < a) & (fold == -1)
        if calm.sum() > 0:
            fold[calm] = k; meta.append({"fold": k, "type": "calm", "from": str(cursor.date()), "to": str(a.date()), "n": int(calm.sum())}); k += 1
        crisis = (fold.index >= a) & (fold.index <= b)
        fold[crisis] = k; meta.append({"fold": k, "type": "crisis", "from": str(a.date()), "to": str(b.date()), "n": int(crisis.sum())}); k += 1
        cursor = b + pd.Timedelta(days=1)
    tail = (fold == -1)
    if tail.sum() > 0:
        fold[tail] = k; meta.append({"fold": k, "type": "calm", "from": str(cursor.date()), "to": str(index.max().date()), "n": int(tail.sum())}); k += 1
    return fold, meta


def fit_predict(method: str, X_tr: pd.DataFrame, y_tr: np.ndarray, X_te: pd.DataFrame, n_pc: int):
    """Returns (train_scores, test_scores) — uncalibrated method outputs."""
    if method == "equal_weight":
        return X_tr.mean(axis=1).values, X_te.mean(axis=1).values
    sc = StandardScaler().fit(X_tr)
    Xtr, Xte = sc.transform(X_tr), sc.transform(X_te)
    if method == "logistic_pc":
        pca = PCA(n_components=min(n_pc, Xtr.shape[1])).fit(Xtr)
        Xtr, Xte = pca.transform(Xtr), pca.transform(Xte)
        m = LogisticRegression(class_weight="balanced", penalty="l2", C=1.0, max_iter=2000, random_state=RS).fit(Xtr, y_tr)
        return m.predict_proba(Xtr)[:, 1], m.predict_proba(Xte)[:, 1]
    if method == "elastic_net":
        m = SGDClassifier(loss="log_loss", penalty="elasticnet", l1_ratio=0.5, alpha=0.001,
                          class_weight="balanced", max_iter=5000, random_state=RS).fit(Xtr, y_tr)
        sig = lambda d: 1.0 / (1.0 + np.exp(-d))
        return sig(m.decision_function(Xtr)), sig(m.decision_function(Xte))
    raise ValueError(method)


def calibrated(s_tr: np.ndarray, y_tr: np.ndarray, s_te: np.ndarray) -> np.ndarray:
    iso = IsotonicRegression(out_of_bounds="clip").fit(s_tr, y_tr)
    return iso.predict(s_te)


def reliability_bins(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> list[dict]:
    edges = np.linspace(0, 1, n_bins + 1)
    rows = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        m = (p >= lo) & ((p < hi) if i < n_bins - 1 else (p <= hi))
        if m.sum() == 0:
            continue
        rows.append({"bin": i, "lo": round(float(lo), 2), "hi": round(float(hi), 2),
                     "predicted_mean": round(float(p[m].mean()), 4),
                     "observed_freq": round(float(y[m].mean()), 4), "n": int(m.sum())})
    return rows


def main() -> int:
    risk = pd.read_parquet(DATA / "regime_v2_risk_scores.parquet"); risk.index = pd.to_datetime(risk.index)
    targets = pd.read_parquet(DATA / "forward_drawdown_targets.parquet"); targets.index = pd.to_datetime(targets.index)
    common = risk.dropna(how="all").index.intersection(targets.index)
    X = risk.loc[common].fillna(0.5)
    y = targets.loc[common, PROD_COL]
    mask = y.notna()
    X, y = X[mask], y[mask].astype(float)
    episodes = load_episodes()
    fold, meta = build_folds(X.index, episodes)
    n_pc = int(np.argmax(np.cumsum(PCA(). fit(StandardScaler().fit_transform(X)).explained_variance_ratio_) >= PCA_VAR) + 1)
    print(f"sample {len(X)} days · positives {int(y.sum())} · folds {len(meta)} "
          f"({sum(1 for m in meta if m['type']=='crisis')} crisis + {sum(1 for m in meta if m['type']=='calm')} calm) · PCA {n_pc}")

    purge = pd.Timedelta(days=int((HORIZON + PURGE) * 1.45))   # sessions → calendar days
    oof = pd.DataFrame(index=X.index)
    results = {}
    for method in METHODS:
        pred = pd.Series(np.nan, index=X.index)
        for m in meta:
            te = fold == m["fold"]
            a, b = X.index[te].min(), X.index[te].max()
            tr = ~te & ~((X.index >= a - purge) & (X.index <= b + purge))
            if y[tr].sum() < 5 or y[tr].sum() == tr.sum():
                continue
            s_tr, s_te = fit_predict(method, X[tr], y[tr].values, X[te], n_pc)
            pred[te] = calibrated(s_tr, y[tr].values, s_te)
        oof[method] = pred
        ok = pred.notna()
        b_oof = float(brier_score_loss(y[ok], pred[ok]))
        # in-sample: fit and calibrate on everything, predict everything
        s_all, _ = fit_predict(method, X, y.values, X, n_pc)
        p_in = calibrated(s_all, y.values, s_all)
        b_in = float(brier_score_loss(y, p_in))
        results[method] = {"brier_out_of_fold": round(b_oof, 4), "brier_in_sample": round(b_in, 4),
                           "n_oof": int(ok.sum()), "bins_out_of_fold": reliability_bins(y[ok].values, pred[ok].values),
                           "bins_in_sample": reliability_bins(y.values, p_in)}
        print(f"  {method:13} Brier out-of-fold {b_oof:.4f}   in-sample {b_in:.4f}   (n_oof {int(ok.sum())})")
    base = float(y.mean() * (1 - y.mean()))
    winner = min(METHODS, key=lambda m: results[m]["brier_out_of_fold"])
    print(f"  base-rate Brier {base:.4f} · out-of-fold winner: {winner}")

    oof["y"] = y.values
    oof.index.name = "date"
    oof.to_csv(DATA / "v4_oof_predictions.csv")

    calp = DATA / "v4_calibration.json"
    cal = json.load(open(calp)) if calp.exists() else {}
    cal.update({
        "evaluation": "out_of_fold",
        "fold_definition": {
            "type": "leave-one-crisis-out, extended to full coverage: each SPX drawdown episode [peak, recovery] is a fold; each calm stretch between episodes is a fold; every day is held out exactly once",
            "n_folds": len(meta), "folds": meta,
            "purge": f"{HORIZON}+{PURGE} sessions either side of the held-out fold (forward labels overlap the boundary)",
            "calibrator": "isotonic fitted on TRAINING predictions per fold, applied to the held-out fold",
            "source": "data/source/spx_drawdown_episodes.csv (deduped as regime_v3_ml)",
        },
        "base_rate_brier": round(base, 4),
        "methods": {m: {k: v for k, v in r.items() if not k.startswith("bins")} for m, r in results.items()},
        "out_of_fold_reliability_bins": {m: r["bins_out_of_fold"] for m, r in results.items()},
        "in_sample_reliability_bins": {m: r["bins_in_sample"] for m, r in results.items()},
        "decision": {
            "out_of_fold_winner": winner,
            "production_winner_in_file": cal.get("winning_method"),
            "switch_stands": bool(winner == "equal_weight"),
            "rule": "the production method must win on out-of-fold Brier; in-sample reliability is not evidence",
            "evaluated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    })
    json.dump(cal, open(calp, "w"), indent=2)
    print(f"  wrote v4_calibration.json (evaluation: out_of_fold) and v4_oof_predictions.csv")
    # markdown table for the report
    print("\n| method | Brier out-of-fold | Brier in-sample | n (oof) |\n|---|---|---|---|")
    for m in METHODS:
        r = results[m]; print(f"| {m} | {r['brier_out_of_fold']:.4f} | {r['brier_in_sample']:.4f} | {r['n_oof']} |")
    print(f"| base rate | {base:.4f} | {base:.4f} | {len(y)} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
