#!/usr/bin/env python3
"""
walkforward_test.py — Task D of the free-analyst-data order (7 October 2026): the walk-forward test of the analyst
variables, with the pass rule fixed before the run (section D2) and the look-ahead checks (section D3).

Design (section D1). Universe: the S&P 500 members at each month-end from data/analyst/sp500_membership_history.parquet
(the Wikipedia revision in force at that month-end; the survivorship-free data is not installed — the report says so).
Features at month-end t use only what was known at the close of t: the analyst variables of task B2 (ranked within
the members of the month) and a base set from prices alone (12-1 momentum, the 1-month return, 12-month volatility,
the distance from the 12-month high on split-adjusted closes, log 20-session dollar volume on split-adjusted prices),
each ranked within the month to [-0.5, 0.5]. Outcomes: the 12-month (primary) and 1-month forward return on
dividend-adjusted closes, in excess of the average member of the month. Test years 2014 to 2026; the models are
retrained each January on month-ends whose 12-month outcome was complete before the test year. Two models: ridge
(primary, the form a candidate score could use) and a boosted tree (sklearn HistGradientBoosting), each with and
without the analyst variables. The top tenth and top fifth of each month's predictions, equal-weighted, against the
average member; a round trip of 10 basis points per trade (20 bps per 12-month holding; monthly turnover x 10 bps
at the 1-month horizon); Newey-West t-statistics (11 lags for the overlapping 12-month returns, 1 lag at 1 month).

Pass rule (section D2, fixed before the run): the analyst variables enter the candidate score only if the ridge
model with them shows, at the 12-month horizon and after costs, a top tenth more than 2 points a year above the
average member, with a Newey-West t-statistic above 3, and a positive paired difference against the same model
without them. The boosted tree is reported beside it.

Look-ahead checks (section D3): no feature reads the current membership list (the historical file is the only
membership input; no sector); dollar volume uses split-adjusted prices only; two placebo runs (each analyst variable
replaced by its value 12 months later, then 12 months earlier); no analyst row after a month-end enters that
month's variables (a unit test plants a future row: tests/test_analyst_lookahead.py).

Outputs: data/analyst/walkforward_test.json (every table and the outcome) and the printed summary.

Usage:  python scripts/analyst/walkforward_test.py [--stamp 2026-10-07] [--quick]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
AN = REPO / "data" / "analyst"
OUT = AN / "walkforward_test.json"
AN_VARS = ["an_net_up_90", "an_pt_rev_90", "an_pt_gap", "an_n_act_90", "an_surprise", "an_sue", "an_surprise_streak"]
BASE_VARS = ["mom_12_1", "ret_1m", "vol_12m", "hi_12m", "log_dv"]
TEST_YEARS = list(range(2014, 2027))
COST_BPS = 10.0
RIDGE_LAMBDA = 1.0


def log(m: str) -> None:
    print(f"[walkforward] {m}", flush=True)


def latest_stamp() -> str:
    st = sorted(p.name[len("monthly_prices_"):-len(".parquet")] for p in (AN / "history").glob("monthly_prices_*.parquet"))
    return "+".join(st)


def monthly_prices() -> pd.DataFrame:
    """The union of every download's month-end table, the latest download per name."""
    sys.path.insert(0, str(HERE))
    import build_panel as bp
    return bp.read_all("monthly_prices", bp.all_stamps())


def rank_scaled(s: pd.Series) -> pd.Series:
    n = s.notna().sum()
    if n < 2:
        return pd.Series(np.nan, index=s.index)
    return (s.rank(method="average") - 1) / (n - 1) - 0.5


def newey_west_t(x: np.ndarray, lags: int) -> tuple[float, float, int]:
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return float("nan"), float("nan"), n
    mu = x.mean(); e = x - mu
    g0 = float(np.dot(e, e) / n)
    var = g0
    for l in range(1, min(lags, n - 1) + 1):
        gl = float(np.dot(e[l:], e[:-l]) / n)
        var += 2.0 * (1.0 - l / (lags + 1.0)) * gl
    se = np.sqrt(max(var, 1e-18) / n)
    return float(mu), float(mu / se), n


def ridge_fit(X: np.ndarray, y: np.ndarray, lam: float = RIDGE_LAMBDA) -> np.ndarray:
    Xb = np.column_stack([np.ones(len(X)), X])
    A = Xb.T @ Xb + lam * np.eye(Xb.shape[1]); A[0, 0] -= lam
    return np.linalg.solve(A, Xb.T @ y)


def ridge_predict(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(len(X)), X]) @ beta


def gbm_fit(X: np.ndarray, y: np.ndarray):
    from sklearn.ensemble import HistGradientBoostingRegressor
    m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_depth=3, min_samples_leaf=100,
                                      l2_regularization=1.0, random_state=0)
    return m.fit(X, y)


def load_revision_features(as_of_months: pd.PeriodIndex | None = None) -> tuple[pd.DataFrame, dict]:
    """F4 (7-Oct-2026): the consensus-revision rows the test may use — observed rows of data/analyst/consensus_history.parquet
    only (provider-reported rows are cards-only), each attached to a month-end t only when its available_from <= t.
    Returns the frame (p, ticker, an_eps_rev_30 ...) and the counts of rows by source that entered and were excluded;
    the referee's analyst:provider_rows_in_test is CRITICAL if a provider-reported row ever enters."""
    p_hist = AN / "consensus_history.parquet"
    info = {"observed_rows": 0, "provider_reported_rows_excluded": 0, "provider_reported_rows_in_test": 0, "rows_after_availability": 0, "months_with_values": 0}
    if not p_hist.exists():
        return pd.DataFrame(columns=["p", "ticker"]), info
    h = pd.read_parquet(p_hist)
    if not len(h):
        return pd.DataFrame(columns=["p", "ticker"]), info
    prov = h[h["source"] != "observed"]
    info["provider_reported_rows_excluded"] = int(len(prov))
    obs = h[(h["source"] == "observed") & (h["period"] == "0y")].copy()
    info["observed_rows"] = int(len(obs))
    obs["available_from"] = pd.to_datetime(obs["available_from"])
    # the row serves the month-end at or after its availability: p = the month of available_from, the latest row per month
    obs["p"] = obs["available_from"].dt.to_period("M")
    me = obs["available_from"].dt.to_period("M").dt.to_timestamp("M")
    obs = obs[obs["available_from"] <= me]                              # available on or before that month's end
    info["rows_after_availability"] = int(len(obs))
    out = obs.sort_values("available_from").groupby(["p", "ticker"]).tail(1)[["p", "ticker", "eps_consensus", "eps_n", "up30", "down30", "rev_mean"]]
    info["months_with_values"] = int(out["p"].nunique())
    return out, info


def shift_analyst_frame(an: pd.DataFrame, k: int) -> pd.DataFrame:
    """The placebo shift: with k = +12 the value observed 12 months LATER is placed on month t (information from
    the future); with k = -12 the value observed 12 months earlier. k = 0 leaves the frame as it is."""
    if k:
        an = an.copy(); an["p"] = an["p"] - k
    return an


# ── the table ────────────────────────────────────────────────────────────────────────────────
def build_table(stamp: str, shift_analyst: int = 0) -> tuple[pd.DataFrame, dict]:
    """One row per (month, member) with features, outcomes and the excess over the average member.
    shift_analyst: the placebo shift in months of the analyst variables (+12 = values from the future)."""
    panel = pd.read_parquet(AN / "panel_monthly.parquet")
    mp = monthly_prices()
    mem = pd.read_parquet(AN / "sp500_membership_history.parquet")
    for df in (panel, mp, mem):
        df["month_end"] = pd.to_datetime(df["month_end"])
    panel["p"] = panel["month_end"].dt.to_period("M"); mp["p"] = mp["month_end"].dt.to_period("M"); mem["p"] = mem["month_end"].dt.to_period("M")
    mp = mp[mp["sessions"] >= 15]                               # a month with fewer bars is not a month-end observation
    adj = mp.pivot_table(index="p", columns="ticker", values="adj_close")
    cl = mp.pivot_table(index="p", columns="ticker", values="close")
    dv = mp.pivot_table(index="p", columns="ticker", values="dollar_volume_20")
    full = pd.period_range(adj.index.min(), adj.index.max(), freq="M")
    adj, cl, dv = adj.reindex(full), cl.reindex(full), dv.reindex(full)
    r1 = adj / adj.shift(1) - 1
    feats = {
        "mom_12_1": adj.shift(1) / adj.shift(12) - 1,
        "ret_1m": r1,
        "vol_12m": r1.rolling(12, min_periods=9).std(),
        "hi_12m": cl / cl.rolling(12, min_periods=9).max() - 1,                 # split-adjusted closes only
        "log_dv": np.log(dv.where(dv > 0)),                                     # split-adjusted close x volume
    }
    # a name whose bars end inside the horizon (delisted, acquired) is held to its last month-end instead of being
    # dropped: the return to the last price counts, so an acquisition premium or a collapse stays in the outcome
    last_adj = adj.ffill()
    ends_before_end = adj.notna().iloc[::-1].cumsum().iloc[::-1].eq(0)        # True after a name's last bar
    delisted = ends_before_end.any(axis=0)
    def fwd(h):
        f = adj.shift(-h) / adj - 1
        gone = ends_before_end.shift(-h).fillna(False) & adj.notna()            # no bar h months on, name since ended
        gone = gone & delisted & (last_adj.shift(-h).notna())
        fill = last_adj.shift(-h) / adj - 1
        return f.where(~gone, fill)
    outs = {"fwd12": fwd(12), "fwd1": fwd(1)}
    long = []
    for k, v in {**feats, **outs}.items():
        s = v.stack(); s.name = k; long.append(s)
    T = pd.concat(long, axis=1).reset_index().rename(columns={"level_0": "p", "level_1": "ticker"})
    if "p" not in T.columns:
        T = T.rename(columns={T.columns[0]: "p", T.columns[1]: "ticker"})
    mem_set = mem[["p", "ticker"]].drop_duplicates(); mem_set["member"] = True
    T = T.merge(mem_set, on=["p", "ticker"], how="left"); T["member"] = T["member"].fillna(False).astype(bool)
    an = shift_analyst_frame(panel[["p", "ticker"] + AN_VARS].copy(), shift_analyst)
    T = T.merge(an, on=["p", "ticker"], how="left")
    T = T[T["member"]].copy()
    T["month_end"] = T["p"].dt.to_timestamp("M")
    # ranks within the members of each month: base features and (re-ranked after any shift) analyst variables
    for v in BASE_VARS + AN_VARS:
        T[v + "_rk"] = T.groupby("p")[v].transform(rank_scaled)
    T["an_present"] = T[["an_n_act_90", "an_surprise", "an_sue"]].notna().any(axis=1).astype(float)
    for h in ("fwd12", "fwd1"):
        T[h + "_x"] = T[h] - T.groupby("p")[h].transform("mean")                # excess over the average member
    info = {"months": int(T["p"].nunique()), "rows": int(len(T)), "first": str(T["p"].min()), "last": str(T["p"].max()),
            "members_per_month_avg": round(float(T.groupby("p").size().mean()), 1),
            "members_without_12m_outcome_share": round(float(T["fwd12"].isna().mean()), 4),
            "members_in_file_without_prices": int(len(mem_set) - len(mem_set.merge(T[["p", "ticker"]], on=["p", "ticker"])))}
    return T, info


# ── evaluation ───────────────────────────────────────────────────────────────────────────────
def portfolio_series(T: pd.DataFrame, score: str, horizon: str, top_share: float) -> pd.DataFrame:
    """Per month: the top-share equal-weighted excess return of the horizon, before and after costs, and turnover."""
    rows, prev = [], set()
    for p, g in T[T[score].notna() & T[horizon + "_x"].notna()].groupby("p"):
        n = len(g)
        k = max(int(round(n * top_share)), 1)
        top = g.nlargest(k, score)
        names = set(top["ticker"])
        turnover = 1.0 if not prev else (len(names - prev) + len(prev - names)) / (2.0 * len(names))     # one-way share
        ex = float(top[horizon + "_x"].mean())
        cost = 2 * COST_BPS / 1e4 if horizon == "fwd12" else 2 * turnover * COST_BPS / 1e4
        rows.append({"p": str(p), "n": n, "k": k, "excess": ex, "excess_net": ex - cost, "turnover": turnover})
        prev = names
    return pd.DataFrame(rows)


def summarize_series(ps: pd.DataFrame, horizon: str) -> dict:
    lags = 11 if horizon == "fwd12" else 1
    ann = 1.0 if horizon == "fwd12" else 12.0
    mu, t, n = newey_west_t(ps["excess_net"].values, lags)
    mu_g, t_g, _ = newey_west_t(ps["excess"].values, lags)
    return {"months": n, "excess_pts_per_year_net": round(mu * ann * 100, 2), "t_nw_net": round(t, 2),
            "excess_pts_per_year_gross": round(mu_g * ann * 100, 2), "t_nw_gross": round(t_g, 2),
            "turnover_one_way_avg": round(float(ps["turnover"].mean()), 3) if len(ps) else None,
            "lags": lags}


def walk_forward(T: pd.DataFrame, feats: list[str], target: str, model: str, label: str) -> str:
    """Predictions for every test year, retrained each January on month-ends whose 12-month outcome was complete
    before the test year. Returns the name of the score column."""
    col = f"score_{label}"
    T[col] = np.nan
    for Y in TEST_YEARS:
        cutoff = pd.Period(f"{Y - 1}-12", freq="M") - 12                        # t + 12 months <= Dec of Y-1
        tr = T[(T["p"] <= cutoff) & T["fwd12"].notna() & T[target].notna()]
        te = T["p"].dt.year == Y
        if len(tr) < 500 or not te.any():
            continue
        Xtr = tr[feats].fillna(0.0).values; ytr = tr[target].values
        Xte = T.loc[te, feats].fillna(0.0).values
        if model == "ridge":
            T.loc[te, col] = ridge_predict(ridge_fit(Xtr, ytr), Xte)
        else:
            T.loc[te, col] = gbm_fit(Xtr, ytr).predict(Xte)
    return col


def single_variable_table(T: pd.DataFrame, horizon: str) -> dict:
    out = {}
    for v in AN_VARS:
        rk = v + "_rk"
        rec = {}
        for name, (y0, y1) in {"2014-2019": (2014, 2019), "2020-2026": (2020, 2026)}.items():
            sub = T[(T["p"].dt.year >= y0) & (T["p"].dt.year <= y1) & T[rk].notna() & T[horizon + "_x"].notna()]
            ics, tops = [], []
            for p, g in sub.groupby("p"):
                if len(g) < 30:
                    continue
                ics.append(g[rk].corr(g[horizon + "_x"], method="spearman"))
                k = max(int(round(len(g) * 0.2)), 1)
                tops.append(float(g.nlargest(k, rk)[horizon + "_x"].mean()))
            ann = 1.0 if horizon == "fwd12" else 12.0
            lags = 11 if horizon == "fwd12" else 1
            ic_mu, ic_t, n = newey_west_t(np.array(ics), lags)
            tp_mu, tp_t, _ = newey_west_t(np.array(tops), lags)
            rec[name] = {"months": n, "ic_mean": round(ic_mu, 4), "ic_t_nw": round(ic_t, 2),
                         "top_fifth_pts_per_year": round(tp_mu * ann * 100, 2), "top_fifth_t_nw": round(tp_t, 2),
                         "coverage": round(float(T[(T["p"].dt.year >= y0) & (T["p"].dt.year <= y1)][v].notna().mean()), 3)}
        out[v] = rec
    return out


def run_models(T: pd.DataFrame, horizons: tuple[str, ...], models: tuple[str, ...]) -> dict:
    res = {}
    for h in horizons:
        res[h] = {}
        for m in models:
            s_base = walk_forward(T, [v + "_rk" for v in BASE_VARS], h + "_x", m, f"{m}_{h}_base")
            s_full = walk_forward(T, [v + "_rk" for v in BASE_VARS] + [v + "_rk" for v in AN_VARS] + ["an_present"], h + "_x", m, f"{m}_{h}_full")
            r = {}
            for lbl, sc in (("without_analyst", s_base), ("with_analyst", s_full)):
                r[lbl] = {"top_tenth": summarize_series(portfolio_series(T, sc, h, 0.10), h),
                          "top_fifth": summarize_series(portfolio_series(T, sc, h, 0.20), h)}
            a = portfolio_series(T, s_full, h, 0.10).set_index("p")["excess_net"]
            b = portfolio_series(T, s_base, h, 0.10).set_index("p")["excess_net"]
            d = (a - b).dropna()
            lags = 11 if h == "fwd12" else 1; ann = 1.0 if h == "fwd12" else 12.0
            mu, t, n = newey_west_t(d.values, lags)
            r["paired_top_tenth_with_minus_without"] = {"months": n, "pts_per_year": round(mu * ann * 100, 2), "t_nw": round(t, 2)}
            res[h][m] = r
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default=None)
    ap.add_argument("--quick", action="store_true", help="ridge only, no placebos")
    a = ap.parse_args()
    stamp = a.stamp or latest_stamp()
    models = ("ridge",) if a.quick else ("ridge", "gbm")
    T, info = build_table(stamp)
    log(f"table: {info}")
    single = {h: single_variable_table(T, h) for h in ("fwd12", "fwd1")}
    models_res = run_models(T, ("fwd12", "fwd1"), models)
    placebo = {}
    if not a.quick:
        for name, sh in (("future_12m", 12), ("past_12m", -12)):
            Tp, _ = build_table(stamp, shift_analyst=sh)
            placebo[name] = {"single_fwd12": single_variable_table(Tp, "fwd12"),
                             "models_fwd12": run_models(Tp, ("fwd12",), ("ridge",))["fwd12"]}
    # the pass rule, on the primary model at the primary horizon
    prim = models_res["fwd12"]["ridge"]
    top = prim["with_analyst"]["top_tenth"]; pair = prim["paired_top_tenth_with_minus_without"]
    checks = {"top_tenth_above_2_pts_net": top["excess_pts_per_year_net"] > 2.0,
              "t_nw_above_3": top["t_nw_net"] > 3.0,
              "after_costs": True,
              "better_than_without_paired": pair["pts_per_year"] > 0.0}
    passed = all(checks.values())
    sentence = (f"The pass rule {'is met' if passed else 'fails'}: the ridge model with the analyst variables puts its top tenth "
                f"{top['excess_pts_per_year_net']:+.2f} points a year against the average member after costs (Newey-West t {top['t_nw_net']:.2f}; "
                f"the rule needs more than 2 points and t above 3), and the paired difference against the same model without them is "
                f"{pair['pts_per_year']:+.2f} points (t {pair['t_nw']:.2f}).")
    _rev, rev_info = load_revision_features()
    payload = {
        "cadence": "static", "as_of": datetime.now().strftime("%Y-%m-%d"), "raw_stamp": stamp,
        "order": "free-analyst-data order (7 October 2026), task D",
        "inputs": {"consensus_rows": rev_info,
                   "note": "F4: revision features enter only from observed snapshot rows available at the month-end; none are in the model until 12 months of snapshots exist"},
        "design": {"universe": "S&P 500 members at each month-end from the Wikipedia revision history (survivorship-free data not installed)",
                   "test_years": TEST_YEARS, "retrain": "each January on month-ends whose 12-month outcome was complete before the test year",
                   "base_features": BASE_VARS, "analyst_features": AN_VARS + ["an_present"], "ranking": "within the members of the month, [-0.5, 0.5]",
                   "outcome": "forward return on dividend-adjusted closes in excess of the average member of the month",
                   "costs": f"{COST_BPS:.0f} bps per trade: 20 bps per 12-month holding; monthly turnover x 10 bps at 1 month",
                   "t_stat": "Newey-West, 11 lags for the overlapping 12-month returns, 1 lag at 1 month",
                   "models": {"ridge": f"ridge regression, lambda {RIDGE_LAMBDA}, on the ranked features (primary)",
                              "gbm": "sklearn HistGradientBoostingRegressor(max_iter=300, lr=0.05, depth=3, min_leaf=100, l2=1)"}},
        "table": info,
        "pass_rule": {"text": "top tenth > 2 points a year above the average member after 10 bps per trade, Newey-West t > 3, and a positive paired difference against the same model without the analyst variables; judged on the ridge model at the 12-month horizon",
                      "checks": checks, "passed": passed, "sentence": sentence},
        "single_variable": single,
        "models": models_res,
        "placebo": placebo,
        "lookahead_checks": {
            "membership": "the only membership input is data/analyst/sp500_membership_history.parquet (dated revisions); no sector label; data/universe.txt is not read",
            "dollar_volume": "log_dv = log of the 20-session mean of split-adjusted close x volume (task B1 monthly table); dividend-adjusted closes are used for outcomes only",
            "placebo_future": "each analyst variable replaced by its value 12 months later: the effect should rise",
            "placebo_past": "each analyst variable replaced by its value 12 months earlier: the effect should fall toward zero",
            "timestamp": "tests/test_analyst_lookahead.py plants a rating row after the month-end and asserts the month's variables are unchanged",
        },
    }
    OUT.write_text(json.dumps(payload, indent=1, default=str))
    log(sentence)
    for h in ("fwd12", "fwd1"):
        for m in models:
            r = models_res[h][m]
            log(f"{h} {m}: without {r['without_analyst']['top_tenth']['excess_pts_per_year_net']:+.2f} (t {r['without_analyst']['top_tenth']['t_nw_net']:.2f}) · "
                f"with {r['with_analyst']['top_tenth']['excess_pts_per_year_net']:+.2f} (t {r['with_analyst']['top_tenth']['t_nw_net']:.2f}) · "
                f"paired {r['paired_top_tenth_with_minus_without']['pts_per_year']:+.2f} (t {r['paired_top_tenth_with_minus_without']['t_nw']:.2f})")
    for v in AN_VARS:
        s = single["fwd12"][v]
        log(f"  {v}: IC {s['2014-2019']['ic_mean']:+.3f}/{s['2020-2026']['ic_mean']:+.3f} · top fifth {s['2014-2019']['top_fifth_pts_per_year']:+.2f}/{s['2020-2026']['top_fifth_pts_per_year']:+.2f} pts/yr")
    for name, pl in placebo.items():
        r = pl["models_fwd12"]["ridge"]["with_analyst"]["top_tenth"]
        log(f"placebo {name}: ridge with analyst top tenth {r['excess_pts_per_year_net']:+.2f} (t {r['t_nw_net']:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
