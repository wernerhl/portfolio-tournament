"""
EWS v3 — ML-Weighted Regime Model

Three-step pipeline:
  Step 1: PCA. Decorrelate the 23 risk indicators into independent dimensions.
  Step 2: Weight. Four ML approaches: Logistic-on-PCs, Elastic-Net, RF, GB,
          plus a model-free ΔAUC leave-one-out.
  Step 3: Validate. Leave-one-crisis-out CV across 8 SPX drawdown episodes.
          This is the only honest validation with so few events; k-fold on
          autocorrelated daily data overstates skill.

Outputs (all into data/, charts produced by regime_v3_charts.py):
  data/pca_loadings.csv             loadings matrix (indicators × PCs)
  data/pca_variance_explained.csv   per-PC variance + cumulative
  data/ml_indicator_weights.csv     consensus weights from all 5 methods
  data/loco_cv_results.csv          per-crisis AUC for each model
  data/regime_v3_daily.csv          R_t v3 (the LOCO-winning method)
  data/regime_comparison.json       v1 vs v2 vs v3 AUC + LOCO summary
  data/regime_v3_correlation.csv    23x23 indicator correlation matrix
"""
from __future__ import annotations
import json, math, sys, warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from scipy.stats import norm

warnings.filterwarnings("ignore")

REPO   = Path(__file__).resolve().parent.parent
DATA   = REPO / "data"
SOURCE = DATA / "source"

THRESHOLD = -0.10
HORIZON   = 60       # forward trading days
PCA_VAR   = 0.85     # target variance explained
RANDOM_STATE = 42


# ====================================================================
# 1. Load inputs
# ====================================================================
def load_inputs():
    risk = pd.read_parquet(DATA / "regime_v2_risk_scores.parquet")
    risk.index = pd.to_datetime(risk.index)
    vol = pd.read_parquet(SOURCE / "vol_indicators.parquet")
    vol.index = pd.to_datetime(vol.index)
    spx = vol["spx"].dropna()
    episodes = pd.read_csv(SOURCE / "spx_drawdown_episodes.csv")
    episodes["peak_date"]     = pd.to_datetime(episodes["peak_date"])
    episodes["trough_date"]   = pd.to_datetime(episodes["trough_date"])
    episodes["recovery_date"] = pd.to_datetime(episodes["recovery_date"])
    return risk, spx, episodes


def import_v2_indicators_meta():
    """Pull tier classification from compute_regime_v2 INDICATORS spec."""
    sys.path.insert(0, str(REPO / "scripts"))
    import compute_regime_v2 as crv2
    meta = {}
    for key, tier, direction, *_ in crv2.INDICATORS:
        meta[key] = {"tier": tier, "direction": direction,
                     "weight": crv2.TIER_WEIGHTS[tier]}
    return meta


# ====================================================================
# 2. Target: did SPX fall ≥ 10% within next 60 trading days?
# ====================================================================
def compute_target(spx: pd.Series, threshold: float = THRESHOLD,
                   horizon: int = HORIZON) -> pd.Series:
    # forward-min of (spx_future/spx_today) over the next `horizon` trading days
    vals = spx.values
    n = len(vals)
    y = np.zeros(n, dtype=int)
    for i in range(n - horizon):
        future = vals[i+1:i+1+horizon]
        if future.size == 0:
            continue
        if (future.min() / vals[i] - 1) <= threshold:
            y[i] = 1
    return pd.Series(y, index=spx.index)


def dedupe_episodes(ep: pd.DataFrame) -> pd.DataFrame:
    """Collapse episodes that share a peak_date (deepest trough wins)."""
    keep = []
    for peak, group in ep.groupby("peak_date"):
        # take the row with the LOWEST drawdown_pct (most negative)
        keep.append(group.sort_values("drawdown_pct").iloc[0])
    return pd.DataFrame(keep).sort_values("peak_date").reset_index(drop=True)


# ====================================================================
# 3. PCA
# ====================================================================
def run_pca(X: pd.DataFrame, target_var: float = PCA_VAR):
    scaler = StandardScaler()
    X_s = scaler.fit_transform(X)
    pca = PCA()
    X_pca = pca.fit_transform(X_s)

    cumvar = np.cumsum(pca.explained_variance_ratio_)
    n_components = int(np.argmax(cumvar >= target_var) + 1)

    loadings = pd.DataFrame(
        pca.components_[:n_components].T,
        index=X.columns,
        columns=[f"PC{i+1}" for i in range(n_components)],
    )
    var_df = pd.DataFrame({
        "PC":         [f"PC{i+1}" for i in range(len(pca.explained_variance_ratio_))],
        "var_ratio":  pca.explained_variance_ratio_,
        "cumulative": cumvar,
    })
    return X_pca[:, :n_components], pca, scaler, loadings, var_df, n_components


# ====================================================================
# 4. Four ML models + ΔAUC
# ====================================================================
def fit_logistic_pc(X_pc, y):
    lr = LogisticRegression(class_weight="balanced", penalty="l2", C=1.0,
                            max_iter=2000, random_state=RANDOM_STATE)
    lr.fit(X_pc, y)
    return lr


def fit_elastic_net(X_s, y):
    en = SGDClassifier(loss="log_loss", penalty="elasticnet", l1_ratio=0.5,
                       alpha=0.001, class_weight="balanced", max_iter=5000,
                       random_state=RANDOM_STATE)
    en.fit(X_s, y)
    return en


def fit_random_forest(X_s, y):
    rf = RandomForestClassifier(n_estimators=500, max_depth=4,
                                min_samples_leaf=50, class_weight="balanced",
                                random_state=RANDOM_STATE, n_jobs=-1)
    rf.fit(X_s, y)
    return rf


def fit_gradient_boost(X_s, y):
    gb = GradientBoostingClassifier(n_estimators=200, max_depth=3,
                                    min_samples_leaf=50, learning_rate=0.05,
                                    subsample=0.8, random_state=RANDOM_STATE)
    gb.fit(X_s, y)
    return gb


def delta_auc_loo(X: pd.DataFrame, y: pd.Series) -> pd.Series:
    """For each column: AUC of equal-weight composite WITHOUT that column."""
    composite_full = X.mean(axis=1)
    valid = composite_full.notna() & y.notna()
    baseline = roc_auc_score(y[valid], composite_full[valid])
    deltas = {}
    for col in X.columns:
        sub = X.drop(columns=[col])
        comp = sub.mean(axis=1)
        v = comp.notna() & y.notna()
        deltas[col] = baseline - roc_auc_score(y[v], comp[v])
    return pd.Series(deltas, name="delta_auc")


# ====================================================================
# 5. Leave-one-crisis-out cross-validation
# ====================================================================
def loco_cv(X: pd.DataFrame, y: pd.Series, episodes: pd.DataFrame,
            tier_weights: pd.Series, n_components: int):
    """Returns DataFrame of (held_out, n_test, n_positive, auc_*) rows."""
    rows = []
    for _, ep in episodes.iterrows():
        peak, trough = ep["peak_date"], ep["trough_date"]
        # Buffer ±90 days around the entire episode to prevent leakage
        excl_start = peak  - pd.Timedelta(days=90 + 60)  # 60d label horizon + 90d buffer
        excl_end   = trough + pd.Timedelta(days=90)
        # Test window: 60 trading days before peak through trough
        test_start = peak  - pd.Timedelta(days=120)  # ~60 trading days
        test_end   = trough

        train_mask = ~((X.index >= excl_start) & (X.index <= excl_end))
        test_mask  =  (X.index >= test_start) & (X.index <= test_end)

        X_tr, y_tr = X[train_mask].fillna(0.5), y[train_mask]
        X_te, y_te = X[test_mask].fillna(0.5),  y[test_mask]
        if len(X_te) < 10 or y_te.sum() == 0 or y_te.sum() == len(y_te):
            continue

        scaler = StandardScaler()
        X_tr_s = scaler.fit_transform(X_tr)
        X_te_s = scaler.transform(X_te)

        # PCA fit on train only
        pca = PCA(n_components=n_components)
        X_tr_pc = pca.fit_transform(X_tr_s)
        X_te_pc = pca.transform(X_te_s)

        # Models
        try:
            lr = fit_logistic_pc(X_tr_pc, y_tr)
            p_lr = lr.predict_proba(X_te_pc)[:, 1]
            auc_lr = roc_auc_score(y_te, p_lr)
        except Exception: auc_lr = float("nan")
        try:
            en = fit_elastic_net(X_tr_s, y_tr)
            p_en = en.decision_function(X_te_s)
            auc_en = roc_auc_score(y_te, p_en)
        except Exception: auc_en = float("nan")
        try:
            rf = fit_random_forest(X_tr_s, y_tr)
            p_rf = rf.predict_proba(X_te_s)[:, 1]
            auc_rf = roc_auc_score(y_te, p_rf)
        except Exception: auc_rf = float("nan")
        try:
            gb = fit_gradient_boost(X_tr_s, y_tr)
            p_gb = gb.predict_proba(X_te_s)[:, 1]
            auc_gb = roc_auc_score(y_te, p_gb)
        except Exception: auc_gb = float("nan")

        # Baselines: equal-weight + tier-weighted (v2)
        auc_eq = roc_auc_score(y_te, X_te.mean(axis=1).values)
        # Tier-weighted with cols aligned
        tw = tier_weights.reindex(X_te.columns).fillna(1.0).values
        comp_tw = (X_te.values * tw).sum(axis=1) / tw.sum()
        auc_tw = roc_auc_score(y_te, comp_tw)

        rows.append({
            "held_out_peak":    str(peak.date()),
            "trough":           str(trough.date()),
            "drawdown_pct":     ep["drawdown_pct"],
            "n_test":           int(len(X_te)),
            "n_positive":       int(y_te.sum()),
            "auc_equal_weight": round(auc_eq, 4),
            "auc_tier_weighted":round(auc_tw, 4),
            "auc_logistic_pc":  round(auc_lr, 4),
            "auc_elastic_net":  round(auc_en, 4),
            "auc_random_forest":round(auc_rf, 4),
            "auc_gradient_boost":round(auc_gb, 4),
        })
    return pd.DataFrame(rows)


# ====================================================================
# 6. Build the v3 daily R_t with the winning method
# ====================================================================
def build_v3_r_t(X: pd.DataFrame, y: pd.Series, winner: str,
                 n_components: int) -> pd.Series:
    """Refit the winning method on ALL data and produce R_t for every day."""
    X_filled = X.fillna(0.5)
    scaler = StandardScaler()
    X_s = scaler.fit_transform(X_filled)

    if winner == "logistic_pc":
        pca = PCA(n_components=n_components)
        X_pc = pca.fit_transform(X_s)
        m = fit_logistic_pc(X_pc, y); probs = m.predict_proba(X_pc)[:, 1]
    elif winner == "elastic_net":
        m = fit_elastic_net(X_s, y)
        # Map decision_function to [0,1] via logistic
        d = m.decision_function(X_s)
        probs = 1.0 / (1.0 + np.exp(-d))
    elif winner == "random_forest":
        m = fit_random_forest(X_s, y); probs = m.predict_proba(X_s)[:, 1]
    elif winner == "gradient_boost":
        m = fit_gradient_boost(X_s, y); probs = m.predict_proba(X_s)[:, 1]
    elif winner == "tier_weighted":
        # Use v2's R_t as-is
        v2 = pd.read_csv(DATA / "regime_v2_daily.csv", index_col="date", parse_dates=["date"])
        return v2["R_full"].astype(float).reindex(X.index)
    else:  # equal_weight
        return X.mean(axis=1)
    return pd.Series(probs, index=X.index, name="R_t_v3")


# ====================================================================
# Main
# ====================================================================
def main():
    print("Loading inputs...")
    risk, spx, episodes_raw = load_inputs()
    episodes = dedupe_episodes(episodes_raw)
    meta = import_v2_indicators_meta()
    print(f"  risk_scores: {risk.shape}, spx: {len(spx)} days, episodes: {len(episodes)} (deduped from {len(episodes_raw)})")

    print("\nComputing target (≥10% DD within 60 trading days)...")
    target = compute_target(spx)
    print(f"  positive class share: {target.mean():.4f}")

    # Align
    common = risk.dropna(how="all").index.intersection(target.index)
    X = risk.loc[common].fillna(0.5)
    y = target.loc[common]
    print(f"  aligned sample: {len(X)} days, {int(y.sum())} positive ({y.mean()*100:.2f}%)")

    # Tier weights for v2 baseline
    tier_w = pd.Series({c: meta[c]["weight"] for c in X.columns if c in meta},
                       name="tier_weight")
    tier_w = tier_w.reindex(X.columns).fillna(1.0)

    # ----- 23x23 correlation matrix -----
    print("\nCorrelation matrix...")
    corr = X.corr()
    corr.to_csv(DATA / "regime_v3_correlation.csv")
    # Quick read: pairs with |r| > 0.7
    pairs = []
    cols = list(X.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            r = corr.iloc[i, j]
            if abs(r) > 0.7:
                pairs.append((cols[i], cols[j], round(float(r), 3)))
    print(f"  {len(pairs)} indicator pairs with |r| > 0.7:")
    for a, b, r in sorted(pairs, key=lambda x: -abs(x[2]))[:10]:
        print(f"    {a:<18s} ~ {b:<18s}  r = {r:+.3f}")

    # ----- PCA -----
    print(f"\nPCA (target {PCA_VAR*100:.0f}% variance)...")
    X_pc, pca, scaler, loadings, var_df, n_components = run_pca(X, PCA_VAR)
    print(f"  components for {PCA_VAR*100:.0f}% variance: {n_components}")
    for i in range(min(8, len(var_df))):
        print(f"  PC{i+1}: {var_df['var_ratio'].iloc[i]*100:5.1f}%  "
              f"(cum {var_df['cumulative'].iloc[i]*100:.1f}%)")
    print(f"\n  PC loadings — top 5 absolute per component:")
    for pc in loadings.columns:
        top5 = loadings[pc].abs().nlargest(5)
        print(f"   {pc} ({var_df.set_index('PC').loc[pc,'var_ratio']*100:.1f}%):")
        for ind in top5.index:
            v = loadings.loc[ind, pc]
            print(f"      {('+' if v > 0 else '-')}{ind:<20s} {abs(v):.3f}")
    loadings.to_csv(DATA / "pca_loadings.csv")
    var_df.to_csv(DATA / "pca_variance_explained.csv", index=False)

    # ----- ML models (in-sample) -----
    print("\nTraining ML models (in-sample AUCs are biased — see LOCO below)...")
    X_filled = X.values
    scaler_full = StandardScaler()
    X_s = scaler_full.fit_transform(X_filled)

    # Logistic on PCs
    lr = fit_logistic_pc(X_pc, y.values)
    auc_lr_is = roc_auc_score(y.values, lr.predict_proba(X_pc)[:, 1])
    # Convert PC coefs back to indicator weights via loadings
    w_pc = lr.coef_[0]
    w_lr = pd.Series(loadings.values @ w_pc, index=X.columns, name="Logistic_PC")

    # Elastic Net
    en = fit_elastic_net(X_s, y.values)
    auc_en_is = roc_auc_score(y.values, en.decision_function(X_s))
    w_en = pd.Series(en.coef_[0], index=X.columns, name="Elastic_Net")

    # Random Forest
    rf = fit_random_forest(X_s, y.values)
    auc_rf_is = roc_auc_score(y.values, rf.predict_proba(X_s)[:, 1])
    w_rf = pd.Series(rf.feature_importances_, index=X.columns, name="Random_Forest")

    # Gradient Boost
    gb = fit_gradient_boost(X_s, y.values)
    auc_gb_is = roc_auc_score(y.values, gb.predict_proba(X_s)[:, 1])
    w_gb = pd.Series(gb.feature_importances_, index=X.columns, name="Gradient_Boost")

    # ΔAUC LOO
    w_dauc = delta_auc_loo(X, y)
    w_dauc.name = "Delta_AUC"

    print(f"  Logistic PC:    in-sample AUC = {auc_lr_is:.4f}")
    print(f"  Elastic Net:    in-sample AUC = {auc_en_is:.4f}")
    print(f"  Random Forest:  in-sample AUC = {auc_rf_is:.4f}")
    print(f"  Gradient Boost: in-sample AUC = {auc_gb_is:.4f}")

    # Consensus weights — normalize each to [0,1], then average
    cons = pd.concat([w_lr, w_en, w_rf, w_gb, w_dauc], axis=1)
    cons_norm = pd.DataFrame(index=cons.index)
    for col in cons.columns:
        v = cons[col]
        mn, mx = v.min(), v.max()
        cons_norm[col] = (v - mn) / (mx - mn) if mx > mn else v * 0
    cons_norm["mean_weight"] = cons_norm.mean(axis=1)
    cons_norm["rank"] = cons_norm["mean_weight"].rank(ascending=False, method="min").astype(int)
    cons_norm["tier"] = [meta.get(i, {}).get("tier", "?") for i in cons_norm.index]
    cons_norm = cons_norm.sort_values("rank")
    cons_norm.to_csv(DATA / "ml_indicator_weights.csv")
    print(f"\nConsensus top 10 indicators by normalized mean weight:")
    print(cons_norm[["mean_weight", "rank", "tier"]].head(10).to_string())

    # ----- Leave-one-crisis-out CV -----
    print(f"\nLeave-one-crisis-out CV ({len(episodes)} episodes)...")
    loco = loco_cv(X, y, episodes, tier_w, n_components)
    loco.to_csv(DATA / "loco_cv_results.csv", index=False)
    print(loco.to_string(index=False))
    print("\nMean AUC across held-out crises:")
    mean_aucs = {}
    for col in ["auc_equal_weight", "auc_tier_weighted", "auc_logistic_pc",
                "auc_elastic_net", "auc_random_forest", "auc_gradient_boost"]:
        m_, s_ = loco[col].mean(), loco[col].std()
        mean_aucs[col] = (m_, s_)
        print(f"  {col:<22s} {m_:.4f}  ±  {s_:.4f}")

    # Pick winner
    name_map = {
        "auc_equal_weight":   "equal_weight",
        "auc_tier_weighted":  "tier_weighted",
        "auc_logistic_pc":    "logistic_pc",
        "auc_elastic_net":    "elastic_net",
        "auc_random_forest":  "random_forest",
        "auc_gradient_boost": "gradient_boost",
    }
    winner_col = max(mean_aucs, key=lambda k: mean_aucs[k][0])
    winner = name_map[winner_col]
    print(f"\nLOCO winner: {winner} (mean AUC {mean_aucs[winner_col][0]:.4f})")

    # ----- Build R_t v3 -----
    print(f"\nBuilding R_t v3 using {winner}...")
    R_v3 = build_v3_r_t(X, y, winner, n_components)
    # Min-max normalize R_v3 to [0,1] for comparability
    rng = R_v3.max() - R_v3.min()
    R_v3_n = (R_v3 - R_v3.min()) / rng if rng > 0 else R_v3 * 0 + 0.5
    out = pd.DataFrame({"R_t_v3_raw": R_v3, "R_t_v3": R_v3_n})
    out.index.name = "date"
    out.to_csv(DATA / "regime_v3_daily.csv")
    print(f"  R_t v3 range: {R_v3.min():.3f} → {R_v3.max():.3f}")
    print(f"  Normalized range: {R_v3_n.min():.3f} → {R_v3_n.max():.3f}")

    # ----- Comparison summary -----
    v2 = pd.read_csv(DATA / "regime_v2_daily.csv", index_col="date", parse_dates=["date"])
    R_v1 = X.mean(axis=1)   # equal-weight composite (v1 baseline reconstruction)
    R_v2 = v2["R_full"].reindex(X.index).astype(float)
    valid = R_v3.notna() & y.notna() & R_v1.notna() & R_v2.notna()

    comparison = {
        "in_sample_AUC": {
            "v1_equal_weight":   round(float(roc_auc_score(y[valid], R_v1[valid])), 4),
            "v2_tier_weighted":  round(float(roc_auc_score(y[valid], R_v2[valid])), 4),
            "v3_logistic_pc":    round(float(auc_lr_is), 4),
            "v3_elastic_net":    round(float(auc_en_is), 4),
            "v3_random_forest":  round(float(auc_rf_is), 4),
            "v3_gradient_boost": round(float(auc_gb_is), 4),
        },
        "loco_mean_AUC": {k: round(float(v[0]), 4) for k, v in mean_aucs.items()},
        "loco_std_AUC":  {k: round(float(v[1]), 4) for k, v in mean_aucs.items()},
        "winner": winner,
        "winning_loco_auc": round(float(mean_aucs[winner_col][0]), 4),
        "n_episodes": int(len(episodes)),
        "n_components_pca": int(n_components),
        "pca_variance_explained_target": PCA_VAR,
        "correlation_pairs_above_0p7": len(pairs),
        "target_definition": f"SPX min(t+1:t+{HORIZON}) / SPX(t) - 1 <= {THRESHOLD}",
        "sample_days": int(len(X)),
        "positive_class_share": round(float(y.mean()), 4),
    }
    with open(DATA / "regime_comparison.json", "w") as f:
        json.dump(comparison, f, indent=2)
    print("\n=== v1 vs v2 vs v3 ===")
    print(json.dumps(comparison, indent=2))


if __name__ == "__main__":
    main()
