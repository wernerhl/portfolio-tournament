#!/usr/bin/env python3
"""c2_vintage_compare.py — revised vs point-in-time inputs for the regime index (order 9-Sept, C2).

Variants of the 24-indicator v2 index, all through the same engine and tier sizing:
  rev      as-published (revised) FRED inputs — data/regime_v2_daily.csv
  lag      revised values shifted by each series' measured publication lag
           (release lag only; no revisions; every series treated as existing)
  pitfill  true ALFRED vintages after a series' first vintage, lag-only before
           (release lag + revisions; every series treated as existing)
  pit      strict point-in-time: as pitfill, but a series is unavailable before
           it existed as published data (NFCI/ANFCI 2011, KCFSI 2010, STLFSI4 2022)
Successive differences isolate: rev→lag release lag, lag→pitfill revisions,
pitfill→pit series existence.

Inputs: data/c2/regime_v2_daily_<v>.csv and data/c2/backtest_metrics_<v>.json.
Output: data/c2_vintage_comparison.json (cadence on_change) + markdown tables on stdout.
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

VARIANTS = ["rev", "lag", "pitfill", "pit"]
TIERS = ("1_cap_pres", "2_balanced", "3_aggressive", "4_tactical")


def main() -> int:
    reg = {"rev": pd.read_csv(DATA / "regime_v2_daily.csv", index_col="date", parse_dates=["date"])}
    for v in VARIANTS[1:]:
        p = C2 / f"regime_v2_daily_{v}.csv"
        if p.exists():
            reg[v] = pd.read_csv(p, index_col="date", parse_dates=["date"])
    variants = [v for v in VARIANTS if v in reg]
    vol = pd.read_parquet(SOURCE / "vol_indicators.parquet"); vol.index = pd.to_datetime(vol.index)
    spx = vol["spx"].dropna()
    common = reg["rev"].index
    for v in variants:
        common = common.intersection(reg[v].index)
    reg = {v: reg[v].loc[common] for v in variants}

    target = build_target(spx, lookahead_days=60, dd_threshold=-0.10)
    auc = {v: {"R_full": round(auc_of(reg[v]["R_full"].astype(float), target, v), 4),
               "R_lead": round(auc_of(reg[v]["R_lead"].astype(float), target, v), 4)} for v in variants}

    episodes = detect_dd_episodes(spx, threshold=-0.10)
    leads = []
    for _, ep in episodes.iterrows():
        pk = ep["peak_date"]
        row = {"peak": str(pk.date()), "trough": str(ep["trough_date"].date()), "drawdown_pct": ep["drawdown_pct"]}
        for v in variants:
            row[f"lead_full_0p50_{v}"] = lead_time(reg[v]["R_full"].astype(float), 0.50, pk)
            row[f"lead_full_0p70_{v}"] = lead_time(reg[v]["R_full"].astype(float), 0.70, pk)
            row[f"lead_lead_0p55_{v}"] = lead_time(reg[v]["R_lead"].astype(float), 0.55, pk)
        leads.append(row)

    series_stats = {}
    for v in variants[1:]:
        d = (reg[v]["R_full"].astype(float) - reg["rev"]["R_full"].astype(float)).dropna()
        series_stats[v] = {
            "corr_R_full_vs_rev": round(float(reg[v]["R_full"].astype(float).corr(reg["rev"]["R_full"].astype(float))), 4),
            "mean_abs_diff_R_full": round(float(d.abs().mean()), 4),
            "share_days_abs_diff_gt_0p05": round(float((d.abs() > 0.05).mean()), 4),
            "share_days_abs_diff_gt_0p10": round(float((d.abs() > 0.10).mean()), 4),
        }
    cov = pd.DataFrame({v: reg[v]["n_full_indicators"] for v in variants}).groupby(common.year).mean().round(1)
    coverage = {str(y): {v: float(r[v]) for v in variants} for y, r in cov.iterrows()}

    metrics = {}
    for v in variants:
        p = C2 / f"backtest_metrics_{v}.json"
        if p.exists():
            metrics[v] = json.load(open(p))
    dd = {}
    if "rev" in metrics:
        spy_dd = metrics["rev"]["spy"]["max_drawdown"]
        for tid in TIERS:
            dd[tid] = {"spy_max_dd": spy_dd}
            for v, m in metrics.items():
                a = m[tid]
                dd[tid][v] = {"max_dd": a["max_drawdown"], "dd_reduction_vs_spy": round(1 - a["max_drawdown"] / spy_dd, 4),
                              "cagr_net": a["cagr"], "sharpe_net": a["sharpe"],
                              "turnover_one_way_annual": a.get("turnover_one_way_annual")}
    served = {}
    try:
        sm = json.load(open(DATA / "backtest_metrics.json"))
        served = {tid: {"max_dd": sm[tid]["max_drawdown"], "dd_reduction_vs_spy": round(1 - sm[tid]["max_drawdown"] / sm["spy"]["max_drawdown"], 4),
                        "cagr_net": sm[tid]["cagr"], "sharpe_net": sm[tid]["sharpe"]} for tid in TIERS}
        served["_note"] = "served leaderboard backtest: internal 12-indicator vol-based R_t (no FRED inputs, unrevised) — unaffected by vintages"
    except Exception:
        pass

    meta = json.load(open(SOURCE / "fred_vintage_meta.json")) if (SOURCE / "fred_vintage_meta.json").exists() else {}
    out = {"cadence": "on_change", "as_of": datetime.now().strftime("%Y-%m-%d"),
           "variants": variants, "window": [str(common.min().date()), str(common.max().date())],
           "auc_vs_10pct_dd_60d": auc, "lead_times": leads, "series_vs_revised": series_stats,
           "coverage_n_full_by_year": coverage, "drawdown_reduction": dd, "served_backtest_reference": served,
           "vintage_meta": meta.get("series", {}), "method": meta.get("method")}
    json.dump(out, open(DATA / "c2_vintage_comparison.json", "w"), indent=2, default=str)

    hdr = " | ".join(variants)
    print(f"| metric | {hdr} |\n|---|{'---|' * len(variants)}")
    print(f"| AUC R_full | {' | '.join(str(auc[v]['R_full']) for v in variants)} |")
    print(f"| AUC R_lead | {' | '.join(str(auc[v]['R_lead']) for v in variants)} |")
    print(f"| corr(R_full) vs rev | · | {' | '.join(str(series_stats[v]['corr_R_full_vs_rev']) for v in variants[1:])} |")
    print(f"| mean abs ΔR_full vs rev | · | {' | '.join(str(series_stats[v]['mean_abs_diff_R_full']) for v in variants[1:])} |")
    gt05 = " | ".join("%.1f%%" % (series_stats[v]["share_days_abs_diff_gt_0p05"] * 100) for v in variants[1:])
    gt10 = " | ".join("%.1f%%" % (series_stats[v]["share_days_abs_diff_gt_0p10"] * 100) for v in variants[1:])
    print(f"| days abs Δ > 0.05 | · | {gt05} |")
    print(f"| days abs Δ > 0.10 | · | {gt10} |")
    for thr, key in (("R_full ≥ 0.50", "lead_full_0p50"), ("R_full ≥ 0.70", "lead_full_0p70"), ("R_lead ≥ 0.55", "lead_lead_0p55")):
        print(f"\nLead (trading days before peak) — {thr}\n| episode peak | DD | {hdr} |\n|---|---|{'---|' * len(variants)}")
        for r in leads:
            print(f"| {r['peak']} | {r['drawdown_pct']:.1f}% | {' | '.join(str(r[f'{key}_{v}']) for v in variants)} |")
    if dd:
        print(f"\nMax drawdown / DD reduction vs SPY / CAGR net / Sharpe net\n| tier | {hdr} |\n|---|{'---|' * len(variants)}")
        for tid in TIERS:
            cells = []
            for v in variants:
                if v in dd[tid]:
                    a = dd[tid][v]; cells.append(f"{a['max_dd']*100:.1f}% / {a['dd_reduction_vs_spy']*100:.1f}% / {a['cagr_net']*100:.2f}% / {a['sharpe_net']:.2f}")
                else:
                    cells.append("·")
            print(f"| {tid} | {' | '.join(cells)} |")
    print(f"\nCoverage (mean n_full_indicators by year)\n| year | {hdr} |\n|---|{'---|' * len(variants)}")
    for y, r in coverage.items():
        print(f"| {y} | {' | '.join(str(r[v]) for v in variants)} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
