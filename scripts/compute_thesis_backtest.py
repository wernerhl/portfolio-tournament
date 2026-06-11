"""
compute_thesis_backtest.py — B5: thesis exposure + allocation-vs-selection
attribution over the FULL BACKTEST, where n is large enough to mean something.

Method (monthly, matching the backtest's rebalance cadence):
  - data/backtest_holdings_log.csv rows: date, tier, cash_pct, holdings (equal-
    weight within the equity sleeve, matching backtest.py's construction).
  - For each rebalance period [t, t+1): start-of-period thesis weights =
    equal-weight names × registry membership weights; cash from cash_pct.
  - Thesis basket monthly return = equal-weight ALL registry members priced
    that month (same basket definition as the live layer).
  - r_tier over the period from data/backtest_equity_curves.csv.
  - selection = r_tier − implied(thesis baskets + cash) — the residual.
  - active_vs_SPY = cash_eff + alloc_eff + selection, identity by construction.

CAVEATS carried into the artifact (do not strip):
  - Survivorship: the 537-ticker price store is today's survivors; the paper's
    backtest caveat applies to every basket return here.
  - Registry v1 is applied RETROSPECTIVELY — descriptive lens, not the registry
    in force historically (none existed). Flagged per the vintage convention.

Output: data/thesis_backtest.json
"""
from __future__ import annotations
import json, math
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO   = Path(__file__).resolve().parent.parent
DATA   = REPO / "data"
SOURCE = DATA / "source"

UNCLASSIFIED = "unclassified"


def main():
    registry = json.load(open(DATA / "thesis_registry.json"))
    nw: dict[str, dict[str, float]] = {}
    for tid, th in registry["theses"].items():
        for name, w in th["members"].items():
            nw.setdefault(name, {})[tid] = float(w)
    members = {tid: list(th["members"].keys()) for tid, th in registry["theses"].items()}

    prices = pd.read_parquet(SOURCE / "prices_daily.parquet")
    if "SPY_volume" in prices.columns: prices = prices.drop(columns=["SPY_volume"])
    prices.index = pd.to_datetime(prices.index)

    hold = pd.read_csv(DATA / "backtest_holdings_log.csv", parse_dates=["date"])
    eq = pd.read_csv(DATA / "backtest_equity_curves.csv", parse_dates=["date"]).set_index("date")

    def period_return(series: pd.Series, t0, t1) -> float | None:
        sub = series[(series.index > t0) & (series.index <= t1)].dropna()
        if sub.empty: return None
        base = series[series.index <= t0].dropna()
        if base.empty: return None
        return float(sub.iloc[-1] / base.iloc[-1] - 1)

    # Pre-compute basket cumulative price level (equal-weight daily rebalanced)
    basket_level: dict[str, pd.Series] = {}
    for tid, mem in members.items():
        cols = [m for m in mem if m in prices.columns]
        r = prices[cols].pct_change().mean(axis=1).fillna(0)
        basket_level[tid] = (1 + r).cumprod()
    # SPY closes live in sector_etfs.parquet (the ticker price store carries
    # only SPY_volume).
    sect = pd.read_parquet(SOURCE / "sector_etfs.parquet")
    sect.index = pd.to_datetime(sect.index)
    spy_level = sect["spy"].dropna()

    tiers = sorted(hold["tier"].unique())
    out_tiers = {}
    for tier in tiers:
        rows = hold[hold["tier"] == tier].sort_values("date").reset_index(drop=True)
        if tier not in eq.columns: continue
        nav = eq[tier].dropna()
        periods = []
        cum = {"active": 0.0, "cash_eff": 0.0, "alloc_eff": 0.0, "selection": 0.0}
        exposure_series = []
        for i in range(len(rows) - 1):
            t0, t1 = rows.loc[i, "date"], rows.loc[i + 1, "date"]
            names = [h.strip() for h in str(rows.loc[i, "holdings"]).split(",") if h.strip()]
            cash_w = float(rows.loc[i, "cash_pct"])
            inv_w = 1.0 - cash_w
            if not names: continue
            per_name = inv_w / len(names)
            # Thesis weights (share of NAV)
            w_theta: dict[str, float] = {}
            for nm in names:
                splits = nw.get(nm, {})
                assigned = 0.0
                for tid, w in splits.items():
                    w_theta[tid] = w_theta.get(tid, 0.0) + per_name * w
                    assigned += w
                if assigned < 1.0 - 1e-9:
                    w_theta[UNCLASSIFIED] = w_theta.get(UNCLASSIFIED, 0.0) + per_name * (1 - assigned)
            r_tier = period_return(nav, t0, t1)
            r_spy = period_return(spy_level, t0, t1)
            if r_tier is None or r_spy is None: continue
            # Unclassified bucket return = equal-weight the unclassified names themselves
            uncl_names = [nm for nm in names if not nw.get(nm)]
            r_uncl = None
            cols = [n for n in uncl_names if n in prices.columns]
            if cols:
                lvl = (1 + prices[cols].pct_change().mean(axis=1).fillna(0)).cumprod()
                r_uncl = period_return(lvl, t0, t1)
            cash_rate = 0.04 / 12.0   # backtest used EFFR ≈ 4% ann; monthly approx
            implied = cash_w * cash_rate
            alloc = 0.0
            for tid, w in w_theta.items():
                if tid == UNCLASSIFIED:
                    r_t = r_uncl if r_uncl is not None else r_spy
                else:
                    r_t = period_return(basket_level[tid], t0, t1)
                    if r_t is None: r_t = r_spy
                implied += w * r_t
                alloc += w * (r_t - r_spy)
            cash_eff = cash_w * (cash_rate - r_spy)
            selection = r_tier - implied
            active = r_tier - r_spy
            cum["active"] += active; cum["cash_eff"] += cash_eff
            cum["alloc_eff"] += alloc; cum["selection"] += selection
            periods.append({"d": t0.strftime("%Y-%m"), "active": round(active, 5),
                             "cash_eff": round(cash_eff, 5), "alloc_eff": round(alloc, 5),
                             "selection": round(selection, 5)})
            exposure_series.append({"d": t0.strftime("%Y-%m"),
                                     **{k: round(v, 4) for k, v in w_theta.items()},
                                     "cash": round(cash_w, 4)})
        # Average exposure across the backtest
        if exposure_series:
            keys = set().union(*[set(e.keys()) - {"d"} for e in exposure_series])
            avg_exp = {k: round(float(np.mean([e.get(k, 0.0) for e in exposure_series])), 4)
                       for k in keys}
        else:
            avg_exp = {}
        out_tiers[tier] = {
            "n_periods": len(periods),
            "cum": {k: round(v, 4) for k, v in cum.items()},
            "avg_exposure": dict(sorted(avg_exp.items(), key=lambda kv: -kv[1])),
            "periods_tail": periods[-12:],
        }

    payload = {
        "updated": datetime.now().isoformat(),
        "registry_version": registry["version"],
        "caveats": [
            "SURVIVORSHIP: basket returns come from today's surviving 537-ticker universe — "
            "the same inflation source quantified in the paper applies here.",
            "RETROSPECTIVE REGISTRY: registry v1 is applied to history where no registry "
            "existed. Descriptive lens only, per the vintage convention.",
            "Cash rate approximated at 4% annualized over the backtest (matches backtest.py's EFFR sleeve).",
            "Cumulative components are arithmetic sums of monthly arithmetic effects.",
        ],
        "tiers": out_tiers,
    }

    def _clean(o):
        if isinstance(o, dict):  return {k: _clean(v) for k, v in o.items()}
        if isinstance(o, list):  return [_clean(v) for v in o]
        if isinstance(o, float) and (math.isnan(o) or math.isinf(o)): return None
        if isinstance(o, (np.floating,)):
            x = float(o); return None if (math.isnan(x) or math.isinf(x)) else x
        if isinstance(o, (np.integer,)): return int(o)
        return o

    with open(DATA / "thesis_backtest.json", "w") as f:
        json.dump(_clean(payload), f, indent=2, allow_nan=False)
    print(f"  saved data/thesis_backtest.json")
    for tier, t in out_tiers.items():
        c = t["cum"]
        print(f"  {tier:14s} {t['n_periods']} periods · cum active {c['active']*100:+7.1f}% = "
              f"cash {c['cash_eff']*100:+7.1f}% + alloc {c['alloc_eff']*100:+7.1f}% + sel {c['selection']*100:+7.1f}%")


if __name__ == "__main__":
    main()
