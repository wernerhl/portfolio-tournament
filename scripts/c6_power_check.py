#!/usr/bin/env python3
"""c6_power_check.py — C6 (Tournament Audit and Execution Order of 30 September 2026, 4.2):
the discriminating-power check of the registered decision rule, applied FIRST to the two
monthly tiers against each other, before the real comparison (monthly versus banded-continuous)
runs. → data/tournament/c6_power_check.json and the section of the registration report.

The registered rule (reports/c6_registration_continuous_vs_monthly_2026-09-30.md, section D):
the challenger is preferred when, on common block-bootstrap resamples of the two contestants'
daily returns (C1 cost model, point-in-time inputs), the 90 percent paired interval of the
difference in return per unit of volatility lies above zero AND the paired interval of the
difference in maximum drawdown does not lie below zero (the challenger must not draw down
more) AND the challenger's turnover is under three times the control's. A rule that cannot
tell two DIFFERENT monthly tiers apart on their own backtests has no power and must not be used
to judge the twins; the check reports, for every pair of monthly tiers, whether the rule
discriminates and in which direction.

Inputs: data/backtest_equity_curves.csv (net of the C1 cost model), data/backtest_metrics.json
(turnover per tier). Bootstrap: 1000 resamples, 60-session blocks, seed 20260930, common indices
across contestants (paired), as in C3.
Usage:  python scripts/c6_power_check.py [--print] [--allow-non-trading]
"""
from __future__ import annotations
import argparse
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATA = REPO / "data"
sys.path.insert(0, str(HERE))
from trading_calendar import now_et  # noqa: E402

OUT = DATA / "tournament" / "c6_power_check.json"
TIERS = ["1_cap_pres", "2_balanced", "3_aggressive", "4_tactical"]
REG = {"resamples": 1000, "block_days": 60, "ci": 0.90, "seed": 20260930,
       "rule": {"return_per_vol_interval_above_zero": True, "max_drawdown_interval_not_below_zero": True, "turnover_ratio_max": 3.0}}


def log(m: str) -> None:
    print(f"[c6_power_check] {m}", flush=True)


def block_idx(N: int, block: int, rng: np.random.Generator) -> np.ndarray:
    n_blocks = int(np.ceil(N / block))
    starts = rng.integers(0, N, size=n_blocks)
    idx = (starts[:, None] + np.arange(block)[None, :]).ravel() % N
    return idx[:N]


def metrics(ret: np.ndarray) -> dict:
    mu, sd = ret.mean() * 252, ret.std(ddof=1) * np.sqrt(252)
    nav = np.cumprod(1 + ret); dd = float((nav / np.maximum.accumulate(nav) - 1).min())
    return {"ret_per_vol": float(mu / sd) if sd > 0 else 0.0, "max_dd": dd, "ann_return": float(mu), "ann_vol": float(sd)}


def compare(ra: np.ndarray, rb: np.ndarray, turn_a: float | None, turn_b: float | None, rng_seed: int) -> dict:
    """a = challenger, b = control; paired block bootstrap on common resamples."""
    N = len(ra); rng = np.random.default_rng(rng_seed)
    d_rpv, d_dd = [], []
    for _ in range(REG["resamples"]):
        idx = block_idx(N, REG["block_days"], rng)
        ma, mb = metrics(ra[idx]), metrics(rb[idx])
        d_rpv.append(ma["ret_per_vol"] - mb["ret_per_vol"]); d_dd.append(ma["max_dd"] - mb["max_dd"])
    lo = (1 - REG["ci"]) / 2 * 100; hi = 100 - lo
    rpv_ci = [float(np.percentile(d_rpv, lo)), float(np.percentile(d_rpv, hi))]
    dd_ci = [float(np.percentile(d_dd, lo)), float(np.percentile(d_dd, hi))]
    point_a, point_b = metrics(ra), metrics(rb)
    p_rpv = float(np.mean(np.array(d_rpv) > 0)); p_dd = float(np.mean(np.array(d_dd) > 0))
    turn_ok = (turn_a is None or turn_b is None or turn_b == 0) or (turn_a / turn_b <= REG["rule"]["turnover_ratio_max"])
    # the drawdown condition: the interval of (dd_a − dd_b) must not lie entirely below zero (a deeper drawdown for the challenger)
    dd_ok = not (dd_ci[1] < 0)
    # Candidate rules, evaluated on the controls first (the order's discriminating-power check):
    #   R1 interval: the 90% paired interval of Δ(return/vol) above zero, drawdown not worse, turnover under 3×
    #   R2 probability: the paired-resample probability of Δ(return/vol) > 0 at least 0.80, drawdown not worse, turnover under 3×
    #   R3 composite: R2, or the 90% paired interval of Δ(max drawdown) above zero (a shallower drawdown) with the
    #      probability of Δ(return/vol) > 0 at least 0.50, turnover under 3×
    r1 = (rpv_ci[0] > 0) and dd_ok and turn_ok
    r2 = (p_rpv >= 0.80) and dd_ok and turn_ok
    r3 = r2 or ((dd_ci[0] > 0) and (p_rpv >= 0.50) and turn_ok)
    return {"point": {"challenger": point_a, "control": point_b},
            "delta_return_per_vol": {"point": point_a["ret_per_vol"] - point_b["ret_per_vol"], "ci90": rpv_ci, "p_positive": p_rpv},
            "delta_max_drawdown": {"point": point_a["max_dd"] - point_b["max_dd"], "ci90": dd_ci, "p_positive": p_dd},
            "turnover": {"challenger": turn_a, "control": turn_b, "ratio": (turn_a / turn_b) if (turn_a and turn_b) else None},
            "rules": {"R1_interval": bool(r1), "R2_probability": bool(r2), "R3_composite": bool(r3)},
            "rule_prefers_challenger": bool(r1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", dest="do_print", action="store_true")
    ap.add_argument("--allow-non-trading", action="store_true")
    args = ap.parse_args()
    eq = pd.read_csv(DATA / "backtest_equity_curves.csv", index_col=0, parse_dates=True)
    rets = eq[TIERS].pct_change().dropna()
    mets = json.load(open(DATA / "backtest_metrics.json"))
    turn = {t: (mets.get(t) or {}).get("turnover_one_way_annual") for t in TIERS}
    pairs = {}
    k = 0
    for a, b in itertools.permutations(TIERS, 2):
        k += 1
        pairs[f"{a}_vs_{b}"] = compare(rets[a].to_numpy(), rets[b].to_numpy(), turn.get(a), turn.get(b), REG["seed"] + k)
    # unordered pairs: does each candidate rule tell the two monthly tiers apart in at least one direction?
    unordered, power = {}, {}
    for rule in ("R1_interval", "R2_probability", "R3_composite"):
        n = 0
        for a, b in itertools.combinations(TIERS, 2):
            if pairs[f"{a}_vs_{b}"]["rules"][rule] or pairs[f"{b}_vs_{a}"]["rules"][rule]:
                n += 1
        power[rule] = {"pairs_discriminated": n, "of": len(list(itertools.combinations(TIERS, 2)))}
    for a, b in itertools.combinations(TIERS, 2):
        ab, ba = pairs[f"{a}_vs_{b}"], pairs[f"{b}_vs_{a}"]
        unordered[f"{a} | {b}"] = {"delta_rpv_ci90_a_minus_b": ab["delta_return_per_vol"]["ci90"], "p_rpv_a_over_b": ab["delta_return_per_vol"]["p_positive"],
                                   "delta_dd_ci90_a_minus_b": ab["delta_max_drawdown"]["ci90"],
                                   "R1": {"a": ab["rules"]["R1_interval"], "b": ba["rules"]["R1_interval"]},
                                   "R2": {"a": ab["rules"]["R2_probability"], "b": ba["rules"]["R2_probability"]},
                                   "R3": {"a": ab["rules"]["R3_composite"], "b": ba["rules"]["R3_composite"]}}
    n_pairs = len(unordered)
    registered = "R1_interval"
    n_r1 = power["R1_interval"]["pairs_discriminated"]
    verdict = (f"the registered interval rule (R1) discriminates in {n_r1} of {n_pairs} pairs of monthly tiers: it lacks power and must be revised by a new registration before the real comparison runs; "
               f"the probability rule (R2) discriminates in {power['R2_probability']['pairs_discriminated']}, the composite (R3) in {power['R3_composite']['pairs_discriminated']}"
               if n_r1 < 3 else f"the registered rule discriminates in {n_r1} of {n_pairs} pairs; it has power and may be applied to the twins")
    out = {"cadence": "on_change", "as_of": now_et().strftime("%Y-%m-%d"), "computed_at": now_et().isoformat(timespec="seconds"),
           "registration": "reports/c6_registration_continuous_vs_monthly_2026-09-30.md", "inputs": {"equity_curves": "data/backtest_equity_curves.csv", "window": [str(rets.index[0].date()), str(rets.index[-1].date())], "n_sessions": int(len(rets))},
           "bootstrap": REG, "candidate_rules": {"R1_interval": "90% paired interval of Δ(return/vol) above zero; drawdown not worse; turnover under 3× the control's",
                                                  "R2_probability": "paired-resample probability of Δ(return/vol) > 0 at least 0.80; drawdown not worse; turnover under 3×",
                                                  "R3_composite": "R2, or the 90% interval of Δ(max drawdown) above zero with the probability of Δ(return/vol) > 0 at least 0.50; turnover under 3×"},
           "registered_rule": registered, "power": power, "monthly_vs_monthly": pairs, "pairs_unordered": unordered, "n_pairs": n_pairs,
           "verdict": verdict, "real_comparison": "not run: the banded-continuous backtest is registered, not built; the twins accrue out-of-sample evidence meanwhile",
           "note": "a check of the rules' power on the controls; no contestant is judged here"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    log(f"wrote {OUT.relative_to(REPO)} — {verdict}")
    if args.do_print:
        for k_, v in unordered.items():
            print(f"  {k_:30s} Δrpv90 [{v['delta_rpv_ci90_a_minus_b'][0]:+.3f}, {v['delta_rpv_ci90_a_minus_b'][1]:+.3f}] P(a>b) {v['p_rpv_a_over_b']:.2f} Δdd90 [{v['delta_dd_ci90_a_minus_b'][0]:+.3f}, {v['delta_dd_ci90_a_minus_b'][1]:+.3f}] "
                  f"R1 {v['R1']['a'] or v['R1']['b']!s:5s} R2 {v['R2']['a'] or v['R2']['b']!s:5s} R3 {v['R3']['a'] or v['R3']['b']!s:5s}")
        print("  power:", power)
    return 0


if __name__ == "__main__":
    sys.exit(main())
