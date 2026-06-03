"""
v4 charts — 6 PDFs (Palatino), paper-ready.

1. base_rate_by_threshold.pdf       base rates across the 5x3 target grid
2. auc_by_threshold_horizon.pdf     CV mean AUC heatmap, per method
3. cv_comparison_5pct_40d.pdf       the production target detail
4. reliability_diagram.pdf          calibration verification
5. graduated_probability_timeline.pdf  P(≥X%/Nd) over time with crisis bands
6. regime_v4_vs_v2_comparison.pdf   v2 R_full vs v4 calibrated P side-by-side
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

matplotlib.rcParams["font.family"] = "serif"
matplotlib.rcParams["font.serif"] = ["Palatino", "Palatino Linotype", "Book Antiqua", "serif"]
matplotlib.rcParams["mathtext.fontset"] = "stix"
matplotlib.rcParams["axes.grid"] = True
matplotlib.rcParams["grid.alpha"] = 0.25
matplotlib.rcParams["axes.spines.top"] = False
matplotlib.rcParams["axes.spines.right"] = False
matplotlib.rcParams["axes.linewidth"] = 0.6
matplotlib.rcParams["figure.dpi"] = 110

REPO   = Path(__file__).resolve().parent.parent
DATA   = REPO / "data"
SOURCE = DATA / "source"
CHARTS = REPO / "charts"
CHARTS.mkdir(exist_ok=True)

THRESHOLDS = [3, 5, 7, 10, 15]
HORIZONS   = [20, 40, 60]
METHODS    = ["equal_weight", "elastic_net", "logistic_pc", "random_forest", "gradient_boost"]
METHOD_LBL = {"equal_weight":"Equal-weight","elastic_net":"Elastic Net",
              "logistic_pc":"Logistic+PCs","random_forest":"Random Forest",
              "gradient_boost":"Gradient Boost"}
METHOD_COL = {"equal_weight":"#737373","elastic_net":"#16a34a",
              "logistic_pc":"#2563eb","random_forest":"#BA7517",
              "gradient_boost":"#7c3aed"}


def load_results():
    with open(DATA / "v4_model_results.json") as f:
        return json.load(f)


def load_calibration():
    with open(DATA / "v4_calibration.json") as f:
        return json.load(f)


# ====================================================================
# 1. Base rates
# ====================================================================
def chart_base_rates(results):
    br = results["base_rates"]
    mat = np.zeros((len(THRESHOLDS), len(HORIZONS)))
    cnt = np.zeros((len(THRESHOLDS), len(HORIZONS)), dtype=int)
    for i, t in enumerate(THRESHOLDS):
        for j, N in enumerate(HORIZONS):
            r = br.get(f"y_{t}_{N}", {})
            mat[i, j] = r.get("rate", 0) * 100
            cnt[i, j] = r.get("n_positive", 0)
    fig, ax = plt.subplots(figsize=(7.5, 5))
    im = ax.imshow(mat, aspect="auto", cmap="YlOrRd")
    ax.set_xticks(np.arange(len(HORIZONS))); ax.set_xticklabels([f"{N}d" for N in HORIZONS])
    ax.set_yticks(np.arange(len(THRESHOLDS))); ax.set_yticklabels([f"≥{t}%" for t in THRESHOLDS])
    for i in range(len(THRESHOLDS)):
        for j in range(len(HORIZONS)):
            ax.text(j, i, f"{mat[i,j]:.1f}%\nn={cnt[i,j]}", ha="center", va="center",
                    fontsize=9, color="white" if mat[i,j] > 25 else "black")
    ax.set_xlabel("Forward horizon")
    ax.set_ylabel("Drawdown threshold")
    ax.set_title("Base rates per (threshold, horizon) — fraction of days followed by ≥ X % within N trading days")
    plt.colorbar(im, ax=ax, label="Base rate (%)")
    fig.tight_layout(); fig.savefig(CHARTS / "base_rate_by_threshold.pdf"); plt.close(fig)


# ====================================================================
# 2. AUC heatmap per method
# ====================================================================
def chart_auc_heatmap(results):
    cv = results["cv_results"]
    fig, axes = plt.subplots(1, len(METHODS), figsize=(20, 4.2), sharey=True)
    vmin, vmax = 0.40, 0.85
    for k, m in enumerate(METHODS):
        ax = axes[k]
        mat = np.full((len(THRESHOLDS), len(HORIZONS)), np.nan)
        for i, t in enumerate(THRESHOLDS):
            for j, N in enumerate(HORIZONS):
                r = cv.get(f"y_{t}_{N}", {}).get(m, {})
                mat[i, j] = r.get("mean_auc", np.nan)
        im = ax.imshow(mat, aspect="auto", cmap="RdYlGn", vmin=vmin, vmax=vmax)
        ax.set_xticks(np.arange(len(HORIZONS))); ax.set_xticklabels([f"{N}d" for N in HORIZONS])
        if k == 0:
            ax.set_yticks(np.arange(len(THRESHOLDS)))
            ax.set_yticklabels([f"≥{t}%" for t in THRESHOLDS])
        for i in range(len(THRESHOLDS)):
            for j in range(len(HORIZONS)):
                v = mat[i, j]
                if np.isnan(v): continue
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8,
                        color="white" if (v < 0.55 or v > 0.75) else "black")
        ax.set_title(METHOD_LBL[m], fontsize=10)
    fig.suptitle("Time-series CV AUC per (threshold, horizon, method) — 5 splits + 20d purge gap",
                 fontsize=11, fontweight="bold")
    fig.tight_layout(); fig.savefig(CHARTS / "auc_by_threshold_horizon.pdf"); plt.close(fig)


# ====================================================================
# 3. CV comparison on the production target ≥5%/40d
# ====================================================================
def chart_cv_5pct_40d(results):
    cv = results["cv_results"].get("y_5_40", {})
    fig, ax = plt.subplots(figsize=(10, 4.5))
    n = len(METHODS)
    y = np.arange(n)
    means = [cv.get(m, {}).get("mean_auc", np.nan) for m in METHODS]
    stds  = [cv.get(m, {}).get("std_auc",  np.nan) for m in METHODS]
    colors = [METHOD_COL[m] for m in METHODS]
    ax.barh(y, means, xerr=stds, color=colors, alpha=0.85,
            error_kw={"linewidth":0.8, "capsize":4, "ecolor":"#444"})
    ax.set_yticks(y); ax.set_yticklabels([METHOD_LBL[m] for m in METHODS])
    ax.axvline(0.5, color="#dc2626", linestyle=":", linewidth=0.8, label="Random (0.5)")
    ax.set_xlabel("Time-series CV AUC ± std (5 folds, 20d purge gap)")
    ax.set_xlim(0.30, 0.85)
    ax.set_title("Production target: ≥5 % SPX drawdown within 40 trading days  (1,395 positives in 5,329 days)")
    for i, (m, s) in enumerate(zip(means, stds)):
        if not np.isnan(m):
            ax.text(min(m + s + 0.015, 0.83), i, f"{m:.3f}", va="center", fontsize=8)
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    fig.tight_layout(); fig.savefig(CHARTS / "cv_comparison_5pct_40d.pdf"); plt.close(fig)


# ====================================================================
# 4. Reliability diagram
# ====================================================================
def chart_reliability(cal):
    bins = cal["reliability_bins"]
    fig, ax = plt.subplots(figsize=(6.5, 6))
    pred = [b["predicted_mean"] for b in bins]
    obs  = [b["observed_freq"]  for b in bins]
    n    = [b["n"] for b in bins]
    ax.plot([0,1], [0,1], color="#dc2626", linestyle="--", linewidth=0.8, label="Perfect calibration")
    sizes = [20 + 200 * (ni / max(n)) for ni in n]
    sc = ax.scatter(pred, obs, s=sizes, c="#2563eb", alpha=0.7, edgecolor="#1e3a8a", linewidth=0.6)
    for x, y, ni in zip(pred, obs, n):
        ax.annotate(f"n={ni}", (x, y), xytext=(4, -10), textcoords="offset points", fontsize=8, color="#525252")
    ax.set_xlabel("Predicted probability")
    ax.set_ylabel("Observed frequency")
    ax.set_title(f"Reliability diagram — {cal['winning_method']} + {cal['calibration_method']}\n"
                 f"Brier {cal['brier_score']:.4f}  (baseline {cal['brier_baseline']:.4f})", fontsize=10)
    ax.set_xlim(-0.02, 1.02); ax.set_ylim(-0.02, 1.02)
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    fig.tight_layout(); fig.savefig(CHARTS / "reliability_diagram.pdf"); plt.close(fig)


# ====================================================================
# 5. Graduated probability timeline
# ====================================================================
def chart_prob_timeline():
    daily = pd.read_csv(DATA / "regime_v4_daily.csv", index_col="date", parse_dates=["date"])
    ep = pd.read_csv(SOURCE / "spx_drawdown_episodes.csv")
    ep["peak_date"]   = pd.to_datetime(ep["peak_date"])
    ep["trough_date"] = pd.to_datetime(ep["trough_date"])

    fig, axes = plt.subplots(3, 1, figsize=(13, 8), sharex=True,
                              gridspec_kw={"height_ratios":[1,1,1]})

    # Find available probability columns for each horizon
    cols_3  = [c for c in daily.columns if c.startswith("p_3_")  or c == "p_5_40_calibrated" and False]
    cols_5  = [c for c in daily.columns if c.startswith("p_5_")  and c != "p_5_40_calibrated"] + ["p_5_40_calibrated"]
    cols_10 = [c for c in daily.columns if c.startswith("p_10_")]

    # Plot ≥3% probabilities
    for c in [c for c in daily.columns if c.startswith("p_3_")]:
        axes[0].plot(daily.index, daily[c], linewidth=0.7, alpha=0.7, label=c.replace("p_", "P(≥").replace("_", "%/")+"d)")
    axes[0].set_ylabel("P(≥3%)")
    axes[0].legend(loc="upper left", frameon=False, fontsize=8)
    axes[0].set_ylim(0, 1)

    # ≥5%
    for c in [c for c in daily.columns if c.startswith("p_5_")]:
        lbl = "P(≥5% / 40d) calibrated" if c == "p_5_40_calibrated" else c.replace("p_", "P(≥").replace("_", "%/")+"d)"
        lw  = 1.4 if c == "p_5_40_calibrated" else 0.7
        col = "#dc2626" if c == "p_5_40_calibrated" else None
        axes[1].plot(daily.index, daily[c], linewidth=lw, alpha=0.85, label=lbl, color=col)
    axes[1].set_ylabel("P(≥5%)")
    axes[1].axhline(0.25, color="#16a34a", linestyle=":", linewidth=0.7, label="DEPLOY cutoff")
    axes[1].axhline(0.45, color="#f59e0b", linestyle=":", linewidth=0.7, label="CAUTIOUS cutoff")
    axes[1].axhline(0.65, color="#dc2626", linestyle=":", linewidth=0.7, label="DEFENSIVE cutoff")
    axes[1].legend(loc="upper left", frameon=False, fontsize=8, ncol=2)
    axes[1].set_ylim(0, 1)

    # ≥10%
    for c in [c for c in daily.columns if c.startswith("p_10_")]:
        axes[2].plot(daily.index, daily[c], linewidth=0.7, alpha=0.7, label=c.replace("p_", "P(≥").replace("_", "%/")+"d)")
    axes[2].set_ylabel("P(≥10%)")
    axes[2].legend(loc="upper left", frameon=False, fontsize=8)
    axes[2].set_ylim(0, 1)

    # Shade SPX drawdown episodes on all three
    for ax in axes:
        for _, e in ep.iterrows():
            ax.axvspan(e["peak_date"], e["trough_date"], color="#dc2626", alpha=0.10)

    fig.suptitle("Graduated forward-drawdown probabilities over time — shaded: SPX ≥10% episodes",
                 fontsize=11, fontweight="bold")
    fig.tight_layout(); fig.savefig(CHARTS / "graduated_probability_timeline.pdf"); plt.close(fig)


# ====================================================================
# 6. v4 vs v2 timeline comparison
# ====================================================================
def chart_v4_vs_v2():
    daily = pd.read_csv(DATA / "regime_v4_daily.csv", index_col="date", parse_dates=["date"])
    v2 = pd.read_csv(DATA / "regime_v2_daily.csv", index_col="date", parse_dates=["date"])
    ep = pd.read_csv(SOURCE / "spx_drawdown_episodes.csv")
    ep["peak_date"]   = pd.to_datetime(ep["peak_date"])
    ep["trough_date"] = pd.to_datetime(ep["trough_date"])

    fig, axes = plt.subplots(2, 1, figsize=(13, 6.5), sharex=True)

    v2["R_full"].astype(float).plot(ax=axes[0], color="#2563eb", linewidth=0.9, label="v2  R_full (tier-weighted Φ-mean)")
    axes[0].set_ylabel("R_full (v2)")
    axes[0].set_title("v2 tier-weighted composite")
    axes[0].set_ylim(0, 1)
    axes[0].legend(loc="upper left", frameon=False, fontsize=9)

    daily["p_5_40_calibrated"].plot(ax=axes[1], color="#16a34a", linewidth=0.9,
                                     label="v4  P(≥5% / 40 trading days), calibrated")
    axes[1].axhline(0.25, color="#16a34a", linestyle=":", linewidth=0.7, alpha=0.5)
    axes[1].axhline(0.45, color="#f59e0b", linestyle=":", linewidth=0.7, alpha=0.7)
    axes[1].axhline(0.65, color="#dc2626", linestyle=":", linewidth=0.7, alpha=0.7)
    axes[1].set_ylabel("P (calibrated)")
    axes[1].set_title("v4 calibrated drawdown probability (production target)")
    axes[1].set_ylim(0, 1)
    axes[1].legend(loc="upper left", frameon=False, fontsize=9)

    for ax in axes:
        for _, e in ep.iterrows():
            ax.axvspan(e["peak_date"], e["trough_date"], color="#dc2626", alpha=0.10)

    fig.suptitle("v2 composite vs v4 calibrated probability — shaded: SPX ≥10% drawdowns",
                 fontsize=11, fontweight="bold")
    fig.tight_layout(); fig.savefig(CHARTS / "regime_v4_vs_v2_comparison.pdf"); plt.close(fig)


def main():
    print("Loading results + calibration...")
    results = load_results()
    cal = load_calibration()
    print("Generating v4 charts...")
    for name, fn, args in [
        ("base_rate_by_threshold.pdf",        chart_base_rates,    (results,)),
        ("auc_by_threshold_horizon.pdf",      chart_auc_heatmap,   (results,)),
        ("cv_comparison_5pct_40d.pdf",        chart_cv_5pct_40d,   (results,)),
        ("reliability_diagram.pdf",           chart_reliability,   (cal,)),
        ("graduated_probability_timeline.pdf", chart_prob_timeline, ()),
        ("regime_v4_vs_v2_comparison.pdf",    chart_v4_vs_v2,      ()),
    ]:
        print(f"  {name}...")
        try:
            fn(*args)
        except Exception as e:
            print(f"    FAILED: {e}")
    print("\nDone.")


if __name__ == "__main__":
    main()
