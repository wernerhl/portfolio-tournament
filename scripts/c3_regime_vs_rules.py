#!/usr/bin/env python3
"""c3_regime_vs_rules.py — pre-registered test (order 9-Sept, C3).

Specification: reports/c3_registration.md (frozen before the run). Every constant
below is the registered value; the script asserts the window and stops on any
mismatch rather than silently running a different test.

Usage:
  python scripts/c3_regime_vs_rules.py                      # registered window (decision)
  C3_CONTEXT_WINDOW=2005-01-03:2026-09-04 python scripts/c3_regime_vs_rules.py   # context run, no decision
"""
from __future__ import annotations
import json, os, subprocess, sys
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"; SOURCE = DATA / "source"; OUT = DATA / "c3"

REG = {
    "window": ["2010-02-01", "2026-05-21"],
    "index_series": "data/source/sector_etfs.parquet:spy (dividend-adjusted)",
    "cash_series": "data/source/fred_indicators.parquet:effr, rate/252/100 per session",
    "regime_series": "data/regime_v2_daily.csv:R_full (as-published inputs)",
    "rebalance": "first trading session of each calendar month; signals through t-1 close",
    "sma_months": 10, "mom_lookback_months": 12, "mom_skip_months": 1,
    "vol_target": 0.10, "vol_window_days": 60, "vol_cap": 1.0,
    "cost_one_way_bps": 10,
    "bootstrap": {"resamples": 1000, "block_days": 60, "ci": 0.90, "seed": 20260909},
    "decision_tier": "4_tactical",
    "decision_rule": ("regime passes iff RpV(regime) - RpV(best rule) > half-width of regime's 90% RpV interval "
                      "AND DDred(regime) >= DDred(best rule); point estimates; best rule = highest RpV among (ii)-(iv)"),
}
CONTESTANTS = ["regime", "sma10", "tsmom_12_1", "vol_target_10", "buy_and_hold"]
RULES = ["sma10", "tsmom_12_1", "vol_target_10"]


def load_inputs():
    cfg = json.load(open(REPO / "config.json"))
    tiers = {tid: {k: float(cfg["tiers"][tid][k]) for k in ("cash_floor", "cash_slope", "cash_max")} for tid in cfg["tiers"]}
    sect = pd.read_parquet(SOURCE / "sector_etfs.parquet"); sect.index = pd.to_datetime(sect.index)
    spy = sect["spy"].dropna().astype(float)
    fred = pd.read_parquet(SOURCE / "fred_indicators.parquet"); fred.index = pd.to_datetime(fred.index)
    effr = fred["effr"].astype(float)
    reg = pd.read_csv(DATA / "regime_v2_daily.csv", index_col="date", parse_dates=["date"])["R_full"].astype(float)
    # Registered window = the served backtest equity curves' first and last session (B2).
    eq = pd.read_csv(DATA / "backtest_equity_curves.csv", index_col=0, parse_dates=True)
    start, end = pd.Timestamp(eq.index.min()), pd.Timestamp(eq.index.max())
    return tiers, spy, effr, reg, start, end


def signals_at(rd: pd.Timestamp, spy: pd.Series, reg: pd.Series, month_end: pd.Series) -> dict:
    """Exposures (before tier mapping) using information through the session before rd."""
    hist = spy.loc[:rd].iloc[:-1]                       # through t-1
    me = month_end[month_end.index < rd]                # month-end closes strictly before rd
    out = {}
    # (i) regime: last available R_full at t-1
    r_hist = reg.loc[:hist.index[-1]].dropna()
    out["regime_R"] = float(r_hist.iloc[-1]) if len(r_hist) else np.nan
    # (ii) SMA10 on month-end closes (including the most recent month-end)
    out["sma10"] = float(me.iloc[-1] > me.iloc[-REG["sma_months"]:].mean()) if len(me) >= REG["sma_months"] else np.nan
    # (iii) 12-1 momentum: P_{m-1} / P_{m-12} - 1
    L, S = REG["mom_lookback_months"], REG["mom_skip_months"]
    out["tsmom_12_1"] = float(me.iloc[-1 - S] / me.iloc[-1 - L] - 1.0 > 0) if len(me) >= L + 1 else np.nan
    # (iv) vol targeting: 60 daily log returns through t-1
    lr = np.log(hist).diff().dropna().iloc[-REG["vol_window_days"]:]
    sig = float(lr.std(ddof=1) * np.sqrt(252)) if len(lr) >= REG["vol_window_days"] else np.nan
    out["vol_target_10"] = min(REG["vol_cap"], REG["vol_target"] / sig) if sig and sig > 0 else np.nan
    out["buy_and_hold"] = 1.0
    return out


def exposure_for(name: str, sig: dict, spec: dict) -> float:
    fl, sl, mx = spec["cash_floor"], spec["cash_slope"], spec["cash_max"]
    if name == "regime":
        R = sig["regime_R"]
        cash = min(mx, fl + (0.5 if np.isnan(R) else R) * sl); cash = max(cash, fl)
        return 1.0 - cash
    if name == "buy_and_hold":
        return 1.0 - fl
    e = sig[name]
    if np.isnan(e):
        e = 1.0                                          # insufficient history → invested (never happens in-window)
    return 1.0 - (fl + (1.0 - e) * (mx - fl))


def simulate(name: str, spec: dict, days: pd.DatetimeIndex, rebal: set, spy: pd.Series, effr_d: pd.Series,
             reg: pd.Series, month_end: pd.Series, bps: float):
    r_spy = spy.pct_change().reindex(days).fillna(0.0)
    nav, eq, cash = 1.0, 0.0, 1.0
    navs, rets, turn = [], [], 0.0
    prev_nav = nav
    for i, d in enumerate(days):
        if i > 0:                                        # accrue the day's return at yesterday's positions
            eq *= 1.0 + float(r_spy.loc[d]); cash *= 1.0 + float(effr_d.loc[d]); nav = eq + cash
        if d in rebal:
            sig = signals_at(d, spy, reg, month_end)
            e_new = exposure_for(name, sig, spec)
            w_pre = eq / nav if nav > 0 else 0.0
            t1 = abs(e_new - w_pre)
            if name == "buy_and_hold" and i > 0:
                t1 = 0.0                                 # true buy-and-hold in the pure overlay; constant-mix tiers rebalance
                if spec["cash_floor"] > 0:
                    t1 = abs(e_new - w_pre)
            cost = nav * bps * t1
            nav -= cost; turn += t1
            if not (name == "buy_and_hold" and i > 0 and spec["cash_floor"] == 0):
                eq, cash = nav * e_new, nav * (1.0 - e_new)
            else:
                eq, cash = eq - cost * (eq / (eq + cash)), cash - cost * (cash / (eq + cash))
        navs.append(nav); rets.append(nav / prev_nav - 1.0); prev_nav = nav
    nav_s = pd.Series(navs, index=days, name=name)
    ret_s = pd.Series(rets, index=days, name=name)
    return nav_s, ret_s, turn


def metrics_from_returns(ret: np.ndarray, bench_ret: np.ndarray | None) -> dict:
    nav = np.cumprod(1.0 + ret); N = len(ret)
    cagr = nav[-1] ** (252.0 / N) - 1.0
    vol = ret.std(ddof=1) * np.sqrt(252)
    mdd = float((nav / np.maximum.accumulate(nav) - 1.0).min())
    out = {"max_drawdown": mdd, "ann_return": float(cagr), "ann_vol": float(vol),
           "return_per_vol": float(cagr / vol) if vol > 0 else np.nan}
    if bench_ret is not None:
        bnav = np.cumprod(1.0 + bench_ret); bmdd = float((bnav / np.maximum.accumulate(bnav) - 1.0).min())
        out["dd_reduction_vs_bh"] = float(1.0 - mdd / bmdd) if bmdd < 0 else np.nan
    return out


def block_bootstrap_idx(N: int, block: int, rng: np.random.Generator) -> np.ndarray:
    n_blocks = int(np.ceil(N / block))
    starts = rng.integers(0, N, size=n_blocks)
    idx = (starts[:, None] + np.arange(block)[None, :]).ravel() % N
    return idx[:N]


def run(window: tuple[pd.Timestamp, pd.Timestamp], tag: str, decision: bool) -> dict:
    tiers, spy, effr, reg, start, end = load_inputs()
    if decision:
        assert [str(start.date()), str(end.date())] == REG["window"], \
            f"engine window {start.date()}→{end.date()} != registered {REG['window']} — stop, re-register"
        w0, w1 = start, end
    else:
        w0, w1 = window
    days = spy.loc[w0:w1].index
    effr_d = (effr.reindex(days).ffill().fillna(0.0) / 252.0 / 100.0)
    month_end = spy.resample("ME").last().dropna()
    months = pd.date_range(w0, w1, freq="MS")
    rebal = set()
    for ms in months:
        after = days[days >= ms]
        if len(after) and after[0] <= w1:
            rebal.add(after[0])
    bps = REG["cost_one_way_bps"] / 1e4
    OUT.mkdir(parents=True, exist_ok=True)
    B = REG["bootstrap"]; rng = np.random.default_rng(B["seed"])
    N = len(days)
    boot_idx = [block_bootstrap_idx(N, B["block_days"], rng) for _ in range(B["resamples"])]
    lo, hi = (1 - B["ci"]) / 2 * 100, (1 + B["ci"]) / 2 * 100

    result = {"cadence": "on_change", "as_of": datetime.now().strftime("%Y-%m-%d"), "tag": tag,
              "window": [str(days[0].date()), str(days[-1].date())], "n_sessions": int(N), "n_rebalances": len(rebal),
              "registration": REG, "tiers": {}, "decision": None}
    for tid, spec in tiers.items():
        navs, rets, turns = {}, {}, {}
        for name in CONTESTANTS:
            navs[name], rets[name], turns[name] = simulate(name, spec, days, rebal, spy, effr_d, reg, month_end, bps)
        R = np.column_stack([rets[n].values for n in CONTESTANTS])
        pd.DataFrame(navs).to_csv(OUT / f"nav_{tid}{tag}.csv")
        point = {}
        for j, name in enumerate(CONTESTANTS):
            m = metrics_from_returns(R[:, j], R[:, CONTESTANTS.index("buy_and_hold")])
            m["turnover_one_way_annual"] = float(turns[name] / (N / 252.0))
            point[name] = m
        # bootstrap (joint blocks)
        keys = ["max_drawdown", "ann_return", "return_per_vol", "dd_reduction_vs_bh"]
        samples = {n: {k: [] for k in keys} for n in CONTESTANTS}
        diffs = {n: {"return_per_vol": [], "dd_reduction_vs_bh": []} for n in RULES}
        for idx in boot_idx:
            Rb = R[idx, :]
            mb = {n: metrics_from_returns(Rb[:, j], Rb[:, CONTESTANTS.index("buy_and_hold")]) for j, n in enumerate(CONTESTANTS)}
            for n in CONTESTANTS:
                for k in keys:
                    samples[n][k].append(mb[n][k])
            for n in RULES:
                for k in ("return_per_vol", "dd_reduction_vs_bh"):
                    diffs[n][k].append(mb["regime"][k] - mb[n][k])
        ci = {n: {k: [float(np.nanpercentile(samples[n][k], lo)), float(np.nanpercentile(samples[n][k], hi))] for k in keys} for n in CONTESTANTS}
        dci = {n: {k: [float(np.nanpercentile(diffs[n][k], lo)), float(np.nanpercentile(diffs[n][k], hi))] for k in diffs[n]} for n in RULES}
        result["tiers"][tid] = {"spec": spec, "point": point, "ci90": ci, "paired_diff_regime_minus_rule_ci90": dci}

    if decision:
        t = result["tiers"][REG["decision_tier"]]
        best = max(RULES, key=lambda n: t["point"][n]["return_per_vol"])
        rpv_reg, rpv_best = t["point"]["regime"]["return_per_vol"], t["point"][best]["return_per_vol"]
        half = (t["ci90"]["regime"]["return_per_vol"][1] - t["ci90"]["regime"]["return_per_vol"][0]) / 2.0
        margin = rpv_reg - rpv_best
        dd_reg, dd_best = t["point"]["regime"]["dd_reduction_vs_bh"], t["point"][best]["dd_reduction_vs_bh"]
        cond1, cond2 = margin > half, dd_reg >= dd_best
        result["decision"] = {
            "tier": REG["decision_tier"], "best_rule": best,
            "return_per_vol_regime": rpv_reg, "return_per_vol_best_rule": rpv_best, "margin": margin,
            "half_width_regime_ci90": half, "condition_margin_gt_half_width": bool(cond1),
            "dd_reduction_regime": dd_reg, "dd_reduction_best_rule": dd_best, "condition_dd_reduction_ge": bool(cond2),
            "regime_passes": bool(cond1 and cond2),
            "paired_diff_ci90_context": t["paired_diff_regime_minus_rule_ci90"][best],
        }
    try:
        result["regime_csv_blob"] = subprocess.check_output(["git", "rev-parse", "HEAD:data/regime_v2_daily.csv"], cwd=REPO, text=True).strip()[:12]
        result["head"] = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, text=True).strip()
    except Exception:
        pass
    out_path = DATA / (f"c3_results{tag}.json")
    json.dump(result, open(out_path, "w"), indent=2, default=str)
    return result


def print_markdown(res: dict) -> None:
    print(f"window {res['window'][0]} → {res['window'][1]} ({res['n_sessions']} sessions, {res['n_rebalances']} rebalances){' — CONTEXT, NOT DECISION' if res['tag'] else ''}")
    for tid, t in res["tiers"].items():
        sp = t["spec"]
        print(f"\n### {tid} (cash floor {sp['cash_floor']:.2f} / slope {sp['cash_slope']:.2f} / max {sp['cash_max']:.2f})")
        print("| contestant | max DD [90% CI] | ann. return [90% CI] | return/vol [90% CI] | turnover (1-way/yr) | DD reduction vs B&H [90% CI] |\n|---|---|---|---|---|---|")
        for n in CONTESTANTS:
            p, c = t["point"][n], t["ci90"][n]
            ddr = f"{p['dd_reduction_vs_bh']*100:.1f}% [{c['dd_reduction_vs_bh'][0]*100:.1f}, {c['dd_reduction_vs_bh'][1]*100:.1f}]" if n != "buy_and_hold" else "—"
            print(f"| {n} | {p['max_drawdown']*100:.1f}% [{c['max_drawdown'][0]*100:.1f}, {c['max_drawdown'][1]*100:.1f}] | "
                  f"{p['ann_return']*100:.2f}% [{c['ann_return'][0]*100:.2f}, {c['ann_return'][1]*100:.2f}] | "
                  f"{p['return_per_vol']:.3f} [{c['return_per_vol'][0]:.3f}, {c['return_per_vol'][1]:.3f}] | "
                  f"{p['turnover_one_way_annual']:.2f} | {ddr} |")
        print("paired differences (regime − rule), 90% CI: " + "; ".join(
            f"{n}: RpV [{t['paired_diff_regime_minus_rule_ci90'][n]['return_per_vol'][0]:+.3f}, {t['paired_diff_regime_minus_rule_ci90'][n]['return_per_vol'][1]:+.3f}], "
            f"DDred [{t['paired_diff_regime_minus_rule_ci90'][n]['dd_reduction_vs_bh'][0]*100:+.1f}, {t['paired_diff_regime_minus_rule_ci90'][n]['dd_reduction_vs_bh'][1]*100:+.1f}] pts"
            for n in RULES))
    if res.get("decision"):
        d = res["decision"]
        print(f"\n### Decision ({d['tier']}, registered rule)")
        print(f"best one-line rule: {d['best_rule']} (return/vol {d['return_per_vol_best_rule']:.3f}); regime {d['return_per_vol_regime']:.3f}; "
              f"margin {d['margin']:+.3f} vs half-width {d['half_width_regime_ci90']:.3f} → condition 1 {'MET' if d['condition_margin_gt_half_width'] else 'NOT MET'}")
        print(f"drawdown reduction: regime {d['dd_reduction_regime']*100:.1f}% vs best rule {d['dd_reduction_best_rule']*100:.1f}% → condition 2 {'MET' if d['condition_dd_reduction_ge'] else 'NOT MET'}")
        print(f"paired difference (regime − {d['best_rule']}) 90% CI, context: RpV [{d['paired_diff_ci90_context']['return_per_vol'][0]:+.3f}, {d['paired_diff_ci90_context']['return_per_vol'][1]:+.3f}]")
        print(f"**REGIME {'PASSES' if d['regime_passes'] else 'FAILS'}**")


def main() -> int:
    ctx = os.environ.get("C3_CONTEXT_WINDOW")
    if ctx:
        a, b = ctx.split(":")
        res = run((pd.Timestamp(a), pd.Timestamp(b)), "_context", decision=False)
    else:
        res = run(None, "", decision=True)
    print_markdown(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
