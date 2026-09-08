#!/usr/bin/env python3
"""c2_vintage_compare.py — revised vs point-in-time inputs for the regime index (order 9-Sept, C2).

Inputs (produced upstream):
  data/regime_v2_daily.csv              revised inputs (served series)
  data/c2/regime_v2_daily_pit.csv       REGIME_PIT=1 rebuild on ALFRED vintages
  data/c2/backtest_metrics_rev.json     backtest driven by revised R_full
  data/c2/backtest_metrics_pit.json     backtest driven by point-in-time R_full
Outputs:
  data/c2_vintage_comparison.json (cadence on_change) + a markdown table on stdout.
"""
from __future__ import annotations
import json, sys
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"; SOURCE = DATA / "source"; C2 = DATA / "c2"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_regime_v2 import build_target, auc_of, detect_dd_episodes, lead_time  # noqa: E402


def main() -> int:
    rev = pd.read_csv(DATA / "regime_v2_daily.csv", index_col="date", parse_dates=["date"])
    pit = pd.read_csv(C2 / "regime_v2_daily_pit.csv", index_col="date", parse_dates=["date"])
    vol = pd.read_parquet(SOURCE / "vol_indicators.parquet"); vol.index = pd.to_datetime(vol.index)
    spx = vol["spx"].dropna()
    common = rev.index.intersection(pit.index)
    rev, pit = rev.loc[common], pit.loc[common]

    target = build_target(spx, lookahead_days=60, dd_threshold=-0.10)
    auc = {}
    for lbl, df in (("revised", rev), ("point_in_time", pit)):
        auc[lbl] = {"R_full": round(auc_of(df["R_full"].astype(float), target, lbl), 4),
                    "R_lead": round(auc_of(df["R_lead"].astype(float), target, lbl), 4)}

    episodes = detect_dd_episodes(spx, threshold=-0.10)
    leads = []
    for _, ep in episodes.iterrows():
        pk = ep["peak_date"]
        row = {"peak": str(pk.date()), "trough": str(ep["trough_date"].date()), "drawdown_pct": ep["drawdown_pct"]}
        for lbl, df in (("rev", rev), ("pit", pit)):
            row[f"lead_full_0p50_{lbl}"] = lead_time(df["R_full"].astype(float), 0.50, pk)
            row[f"lead_full_0p70_{lbl}"] = lead_time(df["R_full"].astype(float), 0.70, pk)
            row[f"lead_lead_0p55_{lbl}"] = lead_time(df["R_lead"].astype(float), 0.55, pk)
        leads.append(row)

    d = (pit["R_full"].astype(float) - rev["R_full"].astype(float)).dropna()
    cov = pd.DataFrame({"rev": rev["n_full_indicators"], "pit": pit["n_full_indicators"]}).groupby(common.year).mean().round(1)
    series_stats = {
        "corr_R_full": round(float(pit["R_full"].astype(float).corr(rev["R_full"].astype(float))), 4),
        "mean_abs_diff_R_full": round(float(d.abs().mean()), 4),
        "share_days_abs_diff_gt_0p05": round(float((d.abs() > 0.05).mean()), 4),
        "share_days_abs_diff_gt_0p10": round(float((d.abs() > 0.10).mean()), 4),
        "n_full_indicators_mean_by_year": {str(y): {"revised": float(r["rev"]), "point_in_time": float(r["pit"])} for y, r in cov.iterrows()},
    }

    dd = {}
    try:
        mr = json.load(open(C2 / "backtest_metrics_rev.json")); mp = json.load(open(C2 / "backtest_metrics_pit.json"))
        spy_dd = mr["spy"]["max_drawdown"]
        for tid in ("1_cap_pres", "2_balanced", "3_aggressive", "4_tactical"):
            a, b = mr[tid], mp[tid]
            dd[tid] = {
                "max_dd_revised": a["max_drawdown"], "max_dd_pit": b["max_drawdown"], "spy_max_dd": spy_dd,
                "dd_reduction_vs_spy_revised": round(1 - a["max_drawdown"] / spy_dd, 4),
                "dd_reduction_vs_spy_pit": round(1 - b["max_drawdown"] / spy_dd, 4),
                "cagr_net_revised": a["cagr"], "cagr_net_pit": b["cagr"],
                "sharpe_net_revised": a["sharpe"], "sharpe_net_pit": b["sharpe"],
                "turnover_one_way_annual_revised": a.get("turnover_one_way_annual"),
                "turnover_one_way_annual_pit": b.get("turnover_one_way_annual"),
            }
    except FileNotFoundError as e:
        dd = {"error": f"backtest override outputs missing: {e}"}

    meta = json.load(open(SOURCE / "fred_vintage_meta.json")) if (SOURCE / "fred_vintage_meta.json").exists() else {}
    out = {"cadence": "on_change", "as_of": datetime.now().strftime("%Y-%m-%d"),
           "window": [str(common.min().date()), str(common.max().date())],
           "auc_vs_10pct_dd_60d": auc, "lead_times": leads, "series": series_stats,
           "drawdown_reduction": dd, "vintage_meta": meta.get("series", {}), "method": meta.get("method")}
    json.dump(out, open(DATA / "c2_vintage_comparison.json", "w"), indent=2, default=str)

    print("| metric | revised | point-in-time |\n|---|---|---|")
    print(f"| AUC R_full | {auc['revised']['R_full']} | {auc['point_in_time']['R_full']} |")
    print(f"| AUC R_lead | {auc['revised']['R_lead']} | {auc['point_in_time']['R_lead']} |")
    print(f"| corr(R_full) | {series_stats['corr_R_full']} | · |")
    print(f"| mean abs ΔR_full | {series_stats['mean_abs_diff_R_full']} | · |")
    print(f"| days abs Δ > 0.05 / > 0.10 | {series_stats['share_days_abs_diff_gt_0p05']*100:.1f}% / {series_stats['share_days_abs_diff_gt_0p10']*100:.1f}% | · |")
    print("\n| episode peak | DD | lead R_full≥0.50 rev / pit | lead R_full≥0.70 rev / pit | lead R_lead≥0.55 rev / pit |\n|---|---|---|---|---|")
    for r in leads:
        print(f"| {r['peak']} | {r['drawdown_pct']:.1f}% | {r['lead_full_0p50_rev']} / {r['lead_full_0p50_pit']} | {r['lead_full_0p70_rev']} / {r['lead_full_0p70_pit']} | {r['lead_lead_0p55_rev']} / {r['lead_lead_0p55_pit']} |")
    if "error" not in dd:
        print("\n| tier | max DD rev / pit | DD reduction vs SPY rev / pit | CAGR net rev / pit | Sharpe rev / pit |\n|---|---|---|---|---|")
        for tid, v in dd.items():
            print(f"| {tid} | {v['max_dd_revised']*100:.1f}% / {v['max_dd_pit']*100:.1f}% | {v['dd_reduction_vs_spy_revised']*100:.1f}% / {v['dd_reduction_vs_spy_pit']*100:.1f}% | {v['cagr_net_revised']*100:.2f}% / {v['cagr_net_pit']*100:.2f}% | {v['sharpe_net_revised']:.2f} / {v['sharpe_net_pit']:.2f} |")
    print("\ncoverage (mean n_full_indicators by year, revised vs PIT):")
    for y, v in series_stats["n_full_indicators_mean_by_year"].items():
        print(f"  {y}: {v['revised']} vs {v['point_in_time']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
