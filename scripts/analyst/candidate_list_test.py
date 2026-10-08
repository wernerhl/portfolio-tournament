#!/usr/bin/env python3
"""
candidate_list_test.py — the registered candidate-list test (second follow-up order of 7 October 2026, G4), on the
single harness (walkforward_test.py). Every parameter is the registration's
(data/analyst/candidate_list_test_registration.json, committed with its sha256 before this ran):

  universe     S&P 500 members at each month-end (June 2004 on), tickers mapped to their current symbols; no filter on
               today's list or labels (current_universe_only off)
  variables    the 43 (names with fundamentals; primary); the 21 price variables alone, trained from January 2005 (beside)
  score        the mean of the within-month percentile ranks of the ridge and the boosted-tree predictions
  target       the within-month percentile rank of the 12-month return (primary); the excess return beside
  ridge        penalty 100 on features and target ranked to [-0.5, 0.5]; 10 and 1,000 as sensitivity (no part in the verdict)
  tree         walkforward_test.gbm_fit, frozen
  training     expanding window from June 2010 (43) / January 2005 (21), month-ends whose 12-month outcome ended before
               the test year; retrained each January; test years 2014-2026; 12-month primary, 1-month beside
  portfolio    top tenth, equal weight, formed every month (primary); at quarter-ends only (beside)
  delisted     held to the last price (primary); dropped (beside)
  cost         10 bps a trade, both ways
  statistic    Newey-West t: 11 lags monthly, 3 lags quarter-end
  pass         top tenth > 2 points a year after costs, t > 3, and a paired difference against the 12-1 momentum top
               tenth positive with t > 2
  checks       placebo shifts of +12 and -12 months on all 43 variables; current_universe_only off

Output: data/analyst/candidate_list_test_result.json (or --out). Label: free data, members with prices only.
Reporting (H4, third follow-up): momentum_12_1_top_tenth_test_months summarises the momentum top tenth on the
candidate series' own test months - the figure the paired difference is measured against.
"""
from __future__ import annotations

import hashlib
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
AN = REPO / "data" / "analyst"
REG = AN / "candidate_list_test_registration.json"
OUT = AN / "candidate_list_test_result.json"
TRAIN_FROM = {"ext43": "2010-06", "ext21": "2005-01"}


def log(m: str) -> None:
    print(f"[candidate_list_test] {m}", flush=True)


def fit_scores(T: pd.DataFrame, feats: list[str], target: str, train_from: str, lam: float, label: str) -> str:
    """Ridge (penalty lam, ranked target) and the boosted tree, retrained each January on month-ends from train_from
    whose 12-month outcome ended before the test year; the score is the mean of the two within-month percentile ranks."""
    Tt = T[T["p"] >= pd.Period(train_from, freq="M")].copy()
    if target + "_rk" not in Tt.columns:
        Tt[target + "_rk"] = Tt.groupby("p")[target].transform(lambda s: s.rank(pct=True) - 0.5)
    rcol = wf.walk_forward(Tt, feats, target, "ridge", f"cl_ridge_{label}", rank_target=True, lam=lam)
    gcol = wf.walk_forward(Tt, feats, target, "gbm", f"cl_gbm_{label}", rank_target=True)
    col = f"score_cl_{label}"
    Tt[col] = (Tt.groupby("p")[rcol].rank(pct=True) + Tt.groupby("p")[gcol].rank(pct=True)) / 2.0
    T[col] = Tt[col]
    T[rcol] = Tt[rcol]; T[gcol] = Tt[gcol]
    return col


def quarter_end_series(T: pd.DataFrame, score: str, horizon: str) -> pd.DataFrame:
    """The top tenth formed at quarter-ends only (March, June, September, December)."""
    Q = T[T["p"].dt.month.isin([3, 6, 9, 12])]
    return wf.portfolio_series(Q, score, horizon, 0.10)


def summarize_q(ps: pd.DataFrame, horizon: str) -> dict:
    ann = 1.0 if horizon == "fwd12" else 4.0
    mu, t, n = wf.newey_west_t(ps["excess_net"].values, 3)
    return {"quarters": n, "excess_pts_per_year_net": round(mu * ann * 100, 2), "t_nw_net": round(t, 2), "lags": 3}


def momentum_top_tenth(T: pd.DataFrame, horizon: str) -> pd.DataFrame:
    return wf.portfolio_series(T, "mom_12_1_rk", horizon, 0.10)


def paired(a: pd.DataFrame, b: pd.DataFrame, horizon: str, lags: int) -> dict:
    d = (a.set_index("p")["excess_net"] - b.set_index("p")["excess_net"]).dropna()
    ann = 1.0 if horizon == "fwd12" else 12.0
    mu, t, n = wf.newey_west_t(d.values, lags)
    return {"months": n, "pts_per_year": round(mu * ann * 100, 2), "t_nw": round(t, 2)}


def run_set(stamp: str, which: str, hold: bool, shift: int = 0) -> tuple[dict, dict]:
    T, info = wf.build_table(stamp, shift_analyst=0, hold_delisted=hold, ext=True)
    if shift:
        # the placebo: every one of the 43 variables replaced by its value `shift` months later (+) or earlier (-)
        X = T[["p", "ticker"] + [v for v in wf.EXT_PRICE_VARS + wf.EXT_FUND_VARS if v in T.columns]].copy()
        X["p"] = X["p"] - shift
        T = T.drop(columns=[v for v in wf.EXT_PRICE_VARS + wf.EXT_FUND_VARS if v in T.columns]).merge(X, on=["p", "ticker"], how="left")
        for v in wf.EXT_PRICE_VARS + wf.EXT_FUND_VARS:
            if v in T.columns:
                T[v + "_rk"] = T.groupby("p")[v].transform(wf.rank_scaled)
    if which == "ext43":
        T = T[T["has_fund"].fillna(False)].copy()
        feats = [v + "_rk" for v in wf.EXT_PRICE_VARS + wf.EXT_FUND_VARS if v + "_rk" in T.columns]
    else:
        feats = [v + "_rk" for v in wf.EXT_PRICE_VARS if v + "_rk" in T.columns]
    out = {"variables": which, "features": len(feats), "train_from": TRAIN_FROM[which], "hold_delisted": hold, "placebo_shift_months": shift,
           "members_per_month": round(float(T.groupby("p").size().mean()), 1), "months": int(T["p"].nunique())}
    for h in ("fwd12", "fwd1"):
        lags = 11 if h == "fwd12" else 1
        res = {}
        for lam in (100.0, 10.0, 1000.0):
            col = fit_scores(T, feats, h + "_x", TRAIN_FROM[which], lam, f"{which}_{h}_{int(lam)}_{int(hold)}_{shift}")
            ps = wf.portfolio_series(T, col, h, 0.10)
            r = {"top_tenth_monthly": wf.summarize_series(ps, h)}
            if lam == 100.0:
                r["top_tenth_quarter_end"] = summarize_q(quarter_end_series(T, col, h), h)
                r["top_fifth_monthly"] = wf.summarize_series(wf.portfolio_series(T, col, h, 0.20), h)
                mom = momentum_top_tenth(T, h)
                r["paired_vs_momentum_12_1_top_tenth"] = paired(ps, mom, h, lags)
                r["momentum_12_1_top_tenth"] = wf.summarize_series(mom, h)                       # every month with a momentum rank
                r["momentum_12_1_top_tenth_test_months"] = wf.summarize_series(mom[mom["p"].isin(set(ps["p"]))], h)   # H4: the candidate series' test months, what the paired difference is measured against
                r["excess_return_target_ridge_only"] = wf.summarize_series(wf.portfolio_series(T, wf.walk_forward(T[T["p"] >= pd.Period(TRAIN_FROM[which], freq="M")].copy(), feats, h + "_x", "ridge", f"cl_raw_{which}_{h}_{int(hold)}", rank_target=False, lam=lam), h, 0.10), h) if False else None
            res[f"penalty_{int(lam)}"] = r
        out[h] = res
    return out, info


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="the primary configuration only")
    ap.add_argument("--out", default=None, help="result path (default data/analyst/candidate_list_test_result.json; a rerun beside a published result names its own file)")
    a = ap.parse_args()
    reg = json.loads(REG.read_text()); reg_sha = hashlib.sha256(REG.read_bytes()).hexdigest()
    stamp = wf.latest_stamp()
    runs = {}
    runs["primary_43_held"], info43 = run_set(stamp, "ext43", True)
    if not a.quick:
        runs["43_dropped"], _ = run_set(stamp, "ext43", False)
        runs["21_price_held"], info21 = run_set(stamp, "ext21", True)
        runs["placebo_future_12m_43"], _ = run_set(stamp, "ext43", True, shift=12)
        runs["placebo_past_12m_43"], _ = run_set(stamp, "ext43", True, shift=-12)
    prim = runs["primary_43_held"]["fwd12"]["penalty_100"]
    top = prim["top_tenth_monthly"]; pr = prim["paired_vs_momentum_12_1_top_tenth"]
    checks = {"top_tenth_above_2_pts_net": top["excess_pts_per_year_net"] > 2.0, "t_nw_above_3": top["t_nw_net"] > 3.0,
              "paired_vs_momentum_positive_t_above_2": pr["pts_per_year"] > 0 and pr["t_nw"] > 2.0}
    passed = all(checks.values())
    sentence = (f"The candidate-list test {'is met' if passed else 'fails'} on free data: the 43-variable score's top tenth, formed monthly and held to the last price, "
                f"is {top['excess_pts_per_year_net']:+.2f} points a year against the average member after costs (Newey-West t {top['t_nw_net']:.2f}; the rule needs "
                f"more than 2 points and t above 3), and its paired difference against the 12-1 momentum top tenth is {pr['pts_per_year']:+.2f} points (t {pr['t_nw']:.2f}; "
                f"the rule needs a positive difference with t above 2).")
    payload = {"cadence": "static", "as_of": datetime.now().strftime("%Y-%m-%d"), "label": "free data, members with prices only",
               "registration": {"path": str(REG.relative_to(REPO)), "sha256": reg_sha},
               "options": {"current_universe_only": False, "hold_delisted_primary": True, "cost_bps": wf.COST_BPS},
               "table": {"primary": info43, "options": info43.get("options")}, "runs": runs,
               "pass_rule": {"checks": checks, "passed": passed, "sentence": sentence},
               "consequence": ("the candidate list stays out of the score (the proposal's fallback is the 50 largest members)" if not passed
                               else "a pass on free data stays out of the score until it is confirmed on Sharadar or Norgate")}
    out = Path(a.out) if a.out else OUT
    out.write_text(json.dumps(payload, indent=1, default=str))
    log(sentence)
    for k, r in runs.items():
        t12 = r["fwd12"]["penalty_100"]["top_tenth_monthly"]; q = r["fwd12"]["penalty_100"]["top_tenth_quarter_end"]
        log(f"{k}: 12m top tenth {t12['excess_pts_per_year_net']:+.2f} (t {t12['t_nw_net']:.2f}); quarter-end {q['excess_pts_per_year_net']:+.2f} (t {q['t_nw_net']:.2f}); "
            f"1m {r['fwd1']['penalty_100']['top_tenth_monthly']['excess_pts_per_year_net']:+.2f} (t {r['fwd1']['penalty_100']['top_tenth_monthly']['t_nw_net']:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
