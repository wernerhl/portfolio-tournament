#!/usr/bin/env python3
"""
reconcile.py — reconcile the two implementations of the stratification test (follow-up order of 7 October 2026, F5).

Both find about +2.6 points a year for the ridge top tenth at twelve months; the design workspace reported a
Newey-West t of 2.1 (research/ml_stratification_test/res_all.csv: 'all' set, 43 variables), the repository 0.76
(scripts/analyst/walkforward_test.py, 5 price variables). Starting from the repository's configuration, each
difference is removed in turn, cumulatively, and the ridge top tenth (12 months) is reported after each step:

  0  the repository's result: 5 base variables, 10 bps a trade (20 bps per holding), a delisted name held to its last
     price, the excess return as the training target, ridge penalty 1
  1  no cost
  2  the workspace's return treatment: a name whose prices end inside the horizon is dropped; returns capped at 300%
  3  the workspace's fit: the within-month percentile rank of the outcome as the training target, ridge penalty 100
  4  the workspace's universe filters: 63-day dollar volume of at least $3 million, and a current sector label (which
     drops the delisted names)
  5  the workspace's 21 price variables
  6  the workspace's 43 variables (price and fundamentals)

The months in the sample (141 twelve-month test months, 2014-01 to 2025-09) and the Newey-West code (the same
Bartlett-weighted formula; the workspace's function is run on the repository's series as a check) are reported
beside the table. Output: data/analyst/reconciliation.json and the printed table.

Usage:  python scripts/analyst/reconcile.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import walkforward_test as wf   # noqa: E402

REPO = HERE.parent.parent
OUT = REPO / "data" / "analyst" / "reconciliation.json"


def log(m: str) -> None:
    print(f"[reconcile] {m}", flush=True)


def workspace_nw_t(x, lag):
    """research/ml_stratification_test/ml2.py nw_t, verbatim."""
    x = np.asarray(x, float); x = x[~np.isnan(x)]; n = len(x); mu = x.mean(); e = x - mu; s = (e @ e) / n
    for l in range(1, lag + 1):
        s += 2 * (1 - l / (lag + 1)) * (e[l:] @ e[:-l]) / n
    return mu / np.sqrt(s / n)


def step(label: str, T: pd.DataFrame, feats: list[str], cost_bps: float, rank_target: bool, lam: float) -> dict:
    col = wf.walk_forward(T, feats, "fwd12_x", "ridge", f"rec_{abs(hash(label)) % 10**6}", rank_target=rank_target, lam=lam)
    ps = wf.portfolio_series(T, col, "fwd12", 0.10, cost_bps=cost_bps)
    summ = wf.summarize_series(ps, "fwd12")
    mu_ws = float(np.mean(ps["excess_net"])) * 100
    t_ws = float(workspace_nw_t(ps["excess_net"].values, 11))
    out = {"step": label, "months": summ["months"], "top_tenth_pts_per_year": summ["excess_pts_per_year_net"], "t_nw": summ["t_nw_net"],
           "t_nw_workspace_formula": round(t_ws, 2), "members_per_month": round(float(T.groupby("p").size().mean()), 1), "features": len(feats)}
    log(f"{label}: top tenth {out['top_tenth_pts_per_year']:+.2f} pts/yr, t {out['t_nw']:.2f} (workspace formula {t_ws:.2f}), {out['members_per_month']} members/month, {len(feats)} features, {summ['months']} months")
    return out


def main() -> int:
    stamp = wf.latest_stamp()
    base_feats = [v + "_rk" for v in wf.BASE_VARS]
    rows = []
    T0, info0 = wf.build_table(stamp)
    rows.append(step("0 repository result (5 variables, 20 bps a holding, delisted held to the last price, excess-return target, penalty 1)", T0, base_feats, wf.COST_BPS, False, wf.RIDGE_LAMBDA))
    rows.append(step("1 no cost", T0, base_feats, 0.0, False, wf.RIDGE_LAMBDA))
    T2, _ = wf.build_table(stamp, hold_delisted=False, clip=3.0)
    rows.append(step("2 + the workspace's return treatment (delisted dropped, returns capped at 300%)", T2, base_feats, 0.0, False, wf.RIDGE_LAMBDA))
    rows.append(step("3 + the workspace's fit (percentile-rank target, penalty 100)", T2, base_feats, 0.0, True, 100.0))
    T4, info4 = wf.build_table(stamp, hold_delisted=False, clip=3.0, ext=True, liquid_only=True, sector_known_only=True)
    rows.append(step("4 + the workspace's universe filters (dollar volume >= $3M, a current sector label)", T4, base_feats, 0.0, True, 100.0))
    ext21 = [v + "_rk" for v in wf.EXT_PRICE_VARS if v + "_rk" in T4.columns]
    rows.append(step("5 + the workspace's 21 price variables", T4, ext21, 0.0, True, 100.0))
    ext43 = [v + "_rk" for v in (wf.EXT_PRICE_VARS + wf.EXT_FUND_VARS) if v + "_rk" in T4.columns]
    T4f = T4[T4["has_fund"].fillna(False)].copy() if "has_fund" in T4.columns else T4
    rows.append(step("6 + the 22 fundamental variables (43 in all; names with fundamentals)", T4f, ext43, 0.0, True, 100.0))
    ws = {}
    for f in ("res_all.csv", "res_price.csv"):
        p = REPO / "research" / "ml_stratification_test" / f
        if p.exists():
            r = pd.read_csv(p); x = r[(r.h == 12) & (r.model == "ridge") & (r.period == "2014-26")]
            if len(x):
                ws[f] = {"set": x.iloc[0]["set"], "months": int(x.iloc[0]["n"]), "top_tenth_pts_per_year": round(float(x.iloc[0]["top10th_ex"]) * 100, 2), "t_nw": round(float(x.iloc[0]["t10"]), 2)}
    payload = {"cadence": "static", "as_of": datetime.now().strftime("%Y-%m-%d"), "order": "follow-up order of 7 October 2026, F5",
               "repository_table": info0, "workspace_filtered_table": info4, "steps": rows, "workspace_reported": ws,
               "newey_west": "the same Bartlett-weighted formula in both (ml2.py nw_t run on the repository's series gives the t beside each step)",
               "months": "141 twelve-month test months in both (2014-01 to 2025-09)"}
    OUT.write_text(json.dumps(payload, indent=1, default=str))
    log(f"workspace reported: {ws}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
