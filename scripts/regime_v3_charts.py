"""
v3 charts — 6 PDFs into charts/, Palatino font, paper-ready.

1. pca_variance_explained.pdf   scree plot + cumulative
2. pca_loadings_heatmap.pdf     loadings (indicators × top PCs)
3. ml_weights_comparison.pdf    bar chart, 5 methods × 23 indicators
4. loco_cv_comparison.pdf       AUC per crisis per method
5. correlation_matrix.pdf       23×23 indicator correlation heatmap
6. regime_v3_timeline.pdf       R_t v1 vs v2 vs v3 over time + crisis bands
"""
from __future__ import annotations
import json, warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

warnings.filterwarnings("ignore")

# Palatino setup
matplotlib.rcParams["font.family"] = "serif"
matplotlib.rcParams["font.serif"] = ["Palatino", "Palatino Linotype", "Book Antiqua", "serif"]
matplotlib.rcParams["mathtext.fontset"] = "stix"
matplotlib.rcParams["axes.grid"] = True
matplotlib.rcParams["grid.alpha"] = 0.25
matplotlib.rcParams["axes.spines.top"]   = False
matplotlib.rcParams["axes.spines.right"] = False
matplotlib.rcParams["axes.linewidth"]    = 0.6
matplotlib.rcParams["figure.dpi"]        = 110

REPO    = Path(__file__).resolve().parent.parent
DATA    = REPO / "data"
CHARTS  = REPO / "charts"
CHARTS.mkdir(exist_ok=True)


# ====================================================================
# 1. PCA variance explained (scree)
# ====================================================================
def chart_pca_variance():
    var_df = pd.read_csv(DATA / "pca_variance_explained.csv")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.0))
    n = min(15, len(var_df))
    x = np.arange(1, n + 1)

    ax = axes[0]
    ax.bar(x, var_df["var_ratio"].head(n) * 100, color="#2563eb", alpha=0.8, edgecolor="#1e40af")
    ax.set_xlabel("Principal component")
    ax.set_ylabel("Variance explained (%)")
    ax.set_title("Scree plot — individual PCs")
    ax.set_xticks(x); ax.set_xticklabels([f"PC{i}" for i in x], rotation=0, fontsize=8)

    ax = axes[1]
    ax.plot(x, var_df["cumulative"].head(n) * 100, "-o", color="#16a34a", linewidth=1.6, markersize=4)
    ax.axhline(85, color="#dc2626", linestyle="--", linewidth=0.8, label="85% target")
    ax.set_xlabel("Number of components")
    ax.set_ylabel("Cumulative variance (%)")
    ax.set_title("Cumulative variance explained")
    ax.set_ylim(0, 105)
    ax.set_xticks(x); ax.set_xticklabels([f"PC{i}" for i in x], rotation=0, fontsize=8)
    # Annotate the 85% crossover
    cum = var_df["cumulative"].values
    n_components = int(np.argmax(cum >= 0.85) + 1)
    ax.annotate(f"{n_components} PCs reach 85%",
                xy=(n_components, 85), xytext=(n_components + 1.5, 75),
                fontsize=9, arrowprops=dict(arrowstyle="->", color="#dc2626", lw=0.6))
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    fig.suptitle(f"PCA on {len(var_df)} risk indicators — {n_components} components for 85% variance",
                 fontsize=11, fontweight="bold")
    fig.tight_layout()
    fig.savefig(CHARTS / "pca_variance_explained.pdf"); plt.close(fig)


# ====================================================================
# 2. PCA loadings heatmap
# ====================================================================
def chart_pca_loadings():
    loadings = pd.read_csv(DATA / "pca_loadings.csv", index_col=0)
    fig, ax = plt.subplots(figsize=(8.5, 9))
    vmax = loadings.abs().values.max()
    im = ax.imshow(loadings.values, aspect="auto",
                   cmap="RdBu_r", vmin=-vmax, vmax=vmax)
    ax.set_xticks(np.arange(len(loadings.columns)))
    ax.set_xticklabels(loadings.columns, rotation=45, ha="right", fontsize=9)
    ax.set_yticks(np.arange(len(loadings.index)))
    ax.set_yticklabels(loadings.index, fontsize=9)
    # Annotate large loadings
    for i in range(loadings.shape[0]):
        for j in range(loadings.shape[1]):
            v = loadings.iloc[i, j]
            if abs(v) > 0.30:
                ax.text(j, i, f"{v:.2f}", ha="center", va="center",
                        fontsize=7, color="white" if abs(v) > 0.5 else "black")
    cbar = plt.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cbar.set_label("Loading (z-scored scale)", fontsize=9)
    ax.set_title("PCA loadings — indicators × principal components")
    fig.tight_layout()
    fig.savefig(CHARTS / "pca_loadings_heatmap.pdf"); plt.close(fig)


# ====================================================================
# 3. ML weights comparison
# ====================================================================
def chart_ml_weights():
    df = pd.read_csv(DATA / "ml_indicator_weights.csv", index_col=0)
    df = df.sort_values("mean_weight", ascending=True)
    methods = ["Logistic_PC", "Elastic_Net", "Random_Forest", "Gradient_Boost", "Delta_AUC"]
    methods = [m for m in methods if m in df.columns]
    colors = {"Logistic_PC":"#2563eb", "Elastic_Net":"#16a34a", "Random_Forest":"#BA7517",
              "Gradient_Boost":"#7c3aed", "Delta_AUC":"#dc2626"}

    fig, ax = plt.subplots(figsize=(11, 8))
    n_inds = len(df)
    n_methods = len(methods)
    y = np.arange(n_inds)
    h = 0.16
    for i, m in enumerate(methods):
        offset = (i - n_methods / 2) * h + h / 2
        ax.barh(y + offset, df[m], h, color=colors[m], label=m.replace("_", " "), alpha=0.85)
    ax.set_yticks(y); ax.set_yticklabels(df.index, fontsize=9)
    ax.set_xlabel("Normalized weight (0-1)")
    ax.set_title("ML weight comparison across 5 methods")
    ax.legend(loc="lower right", frameon=False, fontsize=9, ncol=2)
    ax.axvline(0, color="black", linewidth=0.5)
    fig.tight_layout()
    fig.savefig(CHARTS / "ml_weights_comparison.pdf"); plt.close(fig)


# ====================================================================
# 4. LOCO CV results
# ====================================================================
def chart_loco():
    df = pd.read_csv(DATA / "loco_cv_results.csv")
    methods = ["auc_equal_weight", "auc_tier_weighted", "auc_logistic_pc",
               "auc_elastic_net", "auc_random_forest", "auc_gradient_boost"]
    labels  = ["Equal", "Tier (v2)", "Logistic+PC", "Elastic Net", "Random Forest", "Gradient Boost"]
    colors  = ["#737373", "#0891b2", "#2563eb", "#16a34a", "#BA7517", "#7c3aed"]

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5),
                              gridspec_kw={"width_ratios": [2.2, 1.0]})

    # Left: per-crisis AUC for each method (grouped bar)
    ax = axes[0]
    n_crises = len(df)
    x = np.arange(n_crises)
    n_methods = len(methods)
    w = 0.13
    for i, (mcol, lbl, col) in enumerate(zip(methods, labels, colors)):
        offset = (i - n_methods / 2) * w + w / 2
        ax.bar(x + offset, df[mcol], w, color=col, label=lbl, alpha=0.85)
    ax.axhline(0.5, color="#dc2626", linestyle=":", linewidth=0.8, label="Random (0.5)")
    ax.set_xticks(x)
    crisis_labels = [f"{r['held_out_peak']}\n({r['drawdown_pct']:.0f}%)" for _, r in df.iterrows()]
    ax.set_xticklabels(crisis_labels, fontsize=8)
    ax.set_ylabel("AUC on held-out crisis")
    ax.set_title("Per-crisis AUC (leave-one-crisis-out)")
    ax.set_ylim(0, 1.05)
    ax.legend(loc="upper right", frameon=False, fontsize=8, ncol=2)

    # Right: mean ± std summary
    ax = axes[1]
    means = [df[m].mean() for m in methods]
    stds  = [df[m].std()  for m in methods]
    y = np.arange(len(methods))
    ax.barh(y, means, xerr=stds, color=colors, alpha=0.85, error_kw={"linewidth":0.8, "capsize":3, "ecolor":"#444"})
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=9)
    ax.axvline(0.5, color="#dc2626", linestyle=":", linewidth=0.8)
    ax.set_xlabel("Mean LOCO AUC ± std")
    ax.set_title("LOCO summary")
    ax.set_xlim(0, 1.05)
    for i, (m, s) in enumerate(zip(means, stds)):
        ax.text(min(m + s + 0.02, 0.97), i, f"{m:.3f}", va="center", fontsize=8)

    fig.suptitle(f"Leave-one-crisis-out cross-validation ({n_crises} episodes)",
                 fontsize=11, fontweight="bold")
    fig.tight_layout()
    fig.savefig(CHARTS / "loco_cv_comparison.pdf"); plt.close(fig)


# ====================================================================
# 5. Correlation matrix heatmap
# ====================================================================
def chart_correlation():
    corr = pd.read_csv(DATA / "regime_v3_correlation.csv", index_col=0)
    # Reorder by simple hierarchical-like grouping: tier A/B/C from compute_regime_v2
    import sys
    sys.path.insert(0, str(REPO / "scripts"))
    import compute_regime_v2 as crv2
    order_by_tier = []
    for tier in ["A", "B", "C"]:
        order_by_tier += [k for k, t, *_ in crv2.INDICATORS if t == tier and k in corr.columns]
    corr = corr.loc[order_by_tier, order_by_tier]

    fig, ax = plt.subplots(figsize=(11, 10))
    im = ax.imshow(corr.values, vmin=-1, vmax=1, cmap="RdBu_r", aspect="auto")
    ax.set_xticks(np.arange(len(corr.columns)))
    ax.set_xticklabels(corr.columns, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(np.arange(len(corr.index)))
    ax.set_yticklabels(corr.index, fontsize=8)
    # Annotate strong correlations
    for i in range(len(corr)):
        for j in range(len(corr)):
            if i == j: continue
            v = corr.iloc[i, j]
            if abs(v) >= 0.6:
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=6.5,
                        color="white" if abs(v) > 0.75 else "black")
    cbar = plt.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cbar.set_label("Pearson r", fontsize=9)
    # Tier dividers
    counts = {"A": sum(1 for k, t, *_ in crv2.INDICATORS if t == "A"),
              "B": sum(1 for k, t, *_ in crv2.INDICATORS if t == "B"),
              "C": sum(1 for k, t, *_ in crv2.INDICATORS if t == "C")}
    a_end = counts["A"] - 0.5
    b_end = a_end + counts["B"]
    for v in [a_end, b_end]:
        ax.axhline(v, color="black", linewidth=0.6)
        ax.axvline(v, color="black", linewidth=0.6)
    ax.set_title("23 × 23 indicator correlation matrix (ordered by tier: A, B, C)")
    fig.tight_layout()
    fig.savefig(CHARTS / "correlation_matrix.pdf"); plt.close(fig)


# ====================================================================
# 6. Regime timeline v1 vs v2 vs v3 + crisis bands
# ====================================================================
def chart_regime_timeline():
    v2 = pd.read_csv(DATA / "regime_v2_daily.csv", index_col="date", parse_dates=["date"])
    v3 = pd.read_csv(DATA / "regime_v3_daily.csv", index_col="date", parse_dates=["date"])
    risk = pd.read_parquet(DATA / "regime_v2_risk_scores.parquet")
    risk.index = pd.to_datetime(risk.index)
    R_v1 = risk.mean(axis=1)
    R_v2 = v2["R_full"].astype(float)
    R_v3 = v3["R_t_v3"].astype(float)
    episodes = pd.read_csv(DATA / "source" / "spx_drawdown_episodes.csv")
    episodes["peak_date"]   = pd.to_datetime(episodes["peak_date"])
    episodes["trough_date"] = pd.to_datetime(episodes["trough_date"])

    fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True,
                              gridspec_kw={"height_ratios":[1, 1]})

    ax = axes[0]
    R_v1.plot(ax=ax, color="#9ca3af", linewidth=0.8, label="v1 equal-weight (23 inds)")
    R_v2.plot(ax=ax, color="#2563eb", linewidth=1.0, label="v2 tier-weighted")
    for _, ep in episodes.iterrows():
        ax.axvspan(ep["peak_date"], ep["trough_date"], color="#dc2626", alpha=0.10)
    ax.set_ylabel("$R_t$ (composite)")
    ax.set_title("v1 (equal-weight) vs v2 (tier-weighted) composite")
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    ax.set_ylim(0, 1)

    ax = axes[1]
    R_v3.plot(ax=ax, color="#16a34a", linewidth=1.0, label="v3 ElasticNet (LOCO winner)")
    for _, ep in episodes.iterrows():
        ax.axvspan(ep["peak_date"], ep["trough_date"], color="#dc2626", alpha=0.10)
    ax.set_ylabel("$R_t^{v3}$ (normalized)")
    ax.set_title("v3 — ElasticNet probability, rescaled to [0,1]")
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    ax.set_ylim(0, 1)

    fig.suptitle("Regime composite over time — shaded bands: SPX ≥10% drawdown episodes",
                 fontsize=11, fontweight="bold")
    fig.tight_layout()
    fig.savefig(CHARTS / "regime_v3_timeline.pdf"); plt.close(fig)


def main():
    print("Generating v3 charts...")
    for name, fn in [
        ("pca_variance_explained.pdf",  chart_pca_variance),
        ("pca_loadings_heatmap.pdf",    chart_pca_loadings),
        ("ml_weights_comparison.pdf",   chart_ml_weights),
        ("loco_cv_comparison.pdf",      chart_loco),
        ("correlation_matrix.pdf",      chart_correlation),
        ("regime_v3_timeline.pdf",      chart_regime_timeline),
    ]:
        print(f"  {name}...")
        try:
            fn()
        except Exception as e:
            print(f"    FAILED: {e}")
    print("\nDone.")


if __name__ == "__main__":
    main()
