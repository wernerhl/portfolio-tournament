"""
Walk-forward backtest 2010-01-04 → 2026-04-30 for the four algorithmic tiers + benchmarks.

Each tier starts at $100,000 on 2010-01-04. At every month start:
  1. Compute R_t from trailing indicator data (no look-ahead).
  2. Score every eligible ticker (≥252 prior days of prices) using the same logic as
     score_universe.py — but with trailing prices only. Fundamentals use the snapshot
     (acknowledged Phase 1 limitation: look-ahead in fundamentals).
  3. Select top-N per tier with tier-specific filter + factor weights.
  4. Buy at market, equal-weight on the equity sleeve. Cash sleeve sized by R_t.
  5. Pay 10 bps × one-way turnover at rebalance.
  6. Walk daily until next rebalance; cash earns EFFR.

Outputs:
  data/backtest_equity_curves.csv     daily NAV per tier + benchmarks
  data/backtest_metrics.json           per-tier performance summary
  data/backtest_holdings_log.csv       per-rebalance picks + turnover + R_t
"""
from __future__ import annotations
import json, time, warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

warnings.filterwarnings("ignore")

REPO   = Path(__file__).resolve().parent.parent
DATA   = REPO / "data"
SOURCE = DATA / "source"

T0 = time.time()
def log(msg): print(f"[{time.time()-T0:6.1f}s] {msg}", flush=True)


def perf(nav: pd.Series) -> dict:
    nav = nav.dropna()
    if len(nav) < 30: return {}
    rets = nav.pct_change().dropna()
    n_years = (nav.index[-1] - nav.index[0]).days / 365.25
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / n_years) - 1 if n_years > 0 else 0
    ann_vol = rets.std() * np.sqrt(252)
    sharpe = (rets.mean() * 252) / ann_vol if ann_vol > 0 else 0
    max_dd = float((nav / nav.cummax() - 1).min())
    calmar = (cagr / abs(max_dd)) if max_dd < 0 else float("inf")
    m = nav.resample("ME").last().pct_change().dropna()
    return {
        "cagr": round(float(cagr), 4),
        "ann_vol": round(float(ann_vol), 4),
        "sharpe": round(float(sharpe), 3),
        "max_drawdown": round(max_dd, 4),
        "calmar": round(float(calmar), 3),
        "monthly_win_rate": round(float((m > 0).mean()), 3) if len(m) else None,
        "n_years": round(float(n_years), 2),
        "final_nav": round(float(nav.iloc[-1]), 2),
    }


def main():
    log("loading source data...")
    prices = pd.read_parquet(SOURCE / "prices_daily.parquet")
    if "SPY_volume" in prices.columns:
        prices = prices.drop(columns=["SPY_volume"])
    prices.index = pd.to_datetime(prices.index)
    fund    = pd.read_parquet(SOURCE / "fundamentals_snapshot.parquet")
    fred    = pd.read_parquet(SOURCE / "fred_indicators.parquet"); fred.index = pd.to_datetime(fred.index)
    vol     = pd.read_parquet(SOURCE / "vol_indicators.parquet");  vol.index = pd.to_datetime(vol.index)
    vold    = pd.read_parquet(SOURCE / "vol_derived.parquet");     vold.index = pd.to_datetime(vold.index)
    sect    = pd.read_parquet(SOURCE / "sector_etfs.parquet");     sect.index = pd.to_datetime(sect.index)

    spx = vol["spx"].dropna()
    trading_days = spx.index
    log(f"  prices: {prices.shape}, trading days: {len(trading_days)}")

    cfg = json.load(open(REPO / "config.json"))
    SETTINGS = cfg["system_settings"]
    TIER_SPECS = cfg["tier_specs"]
    INITIAL_CAP = float(SETTINGS["inception_capital_per_tier"])
    COST_RT     = SETTINGS["transaction_cost_bps"] / 10000.0

    START = pd.Timestamp(SETTINGS["backtest_start"])
    END   = pd.Timestamp(SETTINGS["backtest_end"])

    # -------- EWS R_t (equal-weight composite, 12 indicators, 252d z-score) --------
    log("building R_t...")
    ind_specs = [
        ("vix",          vol["vix"],                   +1),
        ("vvix",         vol["vvix"],                  +1),
        ("skew",         vol["skew"],                  -1),  # lower SKEW = riskier (per existing compute_regime)
        ("realized_vol", vold["spx_realized_vol_20d"], +1),
        ("hyg_lqd",      vold["hyg_lqd_ratio"],        -1),
        ("gold_spx",     vold["gold_spx"],             +1),
        ("tlt_spx",      vold["tlt_spx"],              +1),
        ("def_cyc",      pd.read_parquet(SOURCE / "vol_derived.parquet").get("spx_drawdown", pd.Series(dtype=float)), -1),
        ("spx_ret_60d",  vold["spx_return_60d"],       -1),
        ("spx_drawdown", vold["spx_drawdown"],         -1),
        ("oil_60d_vel", vold["oil_60d_vel"],           +1),
        ("dxy",          vol["dxy"],                   +1),
    ]
    ind_df = pd.DataFrame(index=trading_days)
    for label, s, _ in ind_specs:
        ind_df[label] = s.reindex(trading_days).ffill()
    mu  = ind_df.rolling(252, min_periods=126).mean()
    sig = ind_df.rolling(252, min_periods=126).std()
    z = (ind_df - mu) / sig
    signs = pd.Series({label: s for label, _, s in ind_specs})
    phi = pd.DataFrame(norm.cdf(z.multiply(signs, axis=1).values),
                       index=z.index, columns=z.columns)
    R_t = phi.mean(axis=1).rename("R_t")
    log(f"  R_t range: {R_t.min():.3f} → {R_t.max():.3f}")

    # EFFR daily cash return
    effr = fred["effr"].reindex(trading_days).ffill().fillna(0)
    daily_cash = effr / 252.0 / 100.0

    # -------- Trailing scoring + selection helpers --------
    fund_metrics = [
        ("forwardPE",       -1),
        ("revenueGrowth",   +1),
        ("grossMargins",    +1),
        ("returnOnEquity",  +1),
        ("operatingMargins",+1),
    ]
    fund_components = pd.DataFrame(index=fund.index)
    for col, sign in fund_metrics:
        if col not in fund.columns: continue
        s = pd.to_numeric(fund[col], errors="coerce")
        lo, hi = s.quantile(0.02), s.quantile(0.98)
        s = s.clip(lo, hi)
        r = s.rank(pct=True)
        if sign == -1: r = 1 - r
        fund_components[col] = r
    FUND_SCORE = (fund_components.mean(axis=1) * 25).fillna(12.5)  # constant across backtest

    # Pre-compute pieces we need at each rebalance
    spx_aligned = spx.reindex(prices.index).ffill()

    def score_asof(d: pd.Timestamp, universe: list[str]) -> pd.DataFrame:
        """Compute tech_score for each ticker as of date d using only data ≤ d."""
        # Only tickers with ≥252 prior days of non-null prices through d
        eligible = []
        for t in universe:
            hist = prices[t].loc[:d].dropna()
            if len(hist) >= 252:
                eligible.append(t)
        if not eligible:
            return pd.DataFrame()

        sub = prices.loc[:d, eligible]
        last = sub.iloc[-1]
        ma200 = sub.iloc[-200:].mean()
        # RSI(14)
        diff = sub.diff().iloc[-15:]
        gain = diff.clip(lower=0).mean()
        loss = (-diff.clip(upper=0)).mean()
        rs   = gain / loss.replace(0, np.nan)
        rsi  = 100 - 100 / (1 + rs)
        # 6m return
        if len(sub) < 127:
            return pd.DataFrame()
        ret_6m_stock = last / sub.iloc[-127] - 1
        ret_6m_spx_v = float(spx_aligned.loc[:d].iloc[-1] / spx_aligned.loc[:d].iloc[-127] - 1)

        df = pd.DataFrame(index=eligible)
        df["ma200_dist"] = last / ma200 - 1
        df["rsi"]        = rsi
        df["rel_str_6m"] = ret_6m_stock - ret_6m_spx_v
        # Ranks
        df["ma200_rank"] = 1.0 - df["ma200_dist"].rank(pct=True)
        df["rsi_rank"]   = 1.0 - df["rsi"].rank(pct=True)
        df["rs6m_rank"]  = df["rel_str_6m"].rank(pct=True)
        # Join fundamental components (constant)
        df["sector"]       = fund["sector"].reindex(df.index)
        df["grossMargins"] = pd.to_numeric(fund["grossMargins"], errors="coerce").reindex(df.index)
        df["freeCashflow"] = pd.to_numeric(fund["freeCashflow"], errors="coerce").reindex(df.index)
        df["fund_score"]   = FUND_SCORE.reindex(df.index).fillna(12.5)
        return df

    def select_for_tier(scored: pd.DataFrame, spec: dict) -> list[str]:
        if scored.empty: return []
        cand = scored.copy()
        f = spec.get("universe_filter")
        if f:
            if "sectors" in f:
                cand = cand[cand["sector"].isin(f["sectors"])]
            if "min_gross_margin" in f:
                cand = cand[cand["grossMargins"].fillna(-1) >= f["min_gross_margin"]]
            if f.get("require_positive_fcf"):
                cand = cand[cand["freeCashflow"].fillna(0) > 0]
        if cand.empty: return []
        w = spec["factor_weights"]
        total_w = w["ma200"] + w["rsi"] + w["rs6m"]
        cand = cand.assign(
            tier_tech = (cand["ma200_rank"].fillna(0.5) * w["ma200"] +
                         cand["rsi_rank"].fillna(0.5)   * w["rsi"] +
                         cand["rs6m_rank"].fillna(0.5)  * w["rs6m"]) / total_w * 25
        )
        cand["tier_composite"] = cand["tier_tech"] + cand["fund_score"]
        return cand.nlargest(spec["n_holdings"], "tier_composite").index.tolist()

    # -------- Rebalance calendar --------
    months = pd.date_range(START, END, freq="MS")
    rebal = []
    for ms in months:
        after = prices.index[prices.index >= ms]
        if len(after) > 0 and after[0] <= END:
            rebal.append(after[0])
    rebal = pd.DatetimeIndex(rebal)
    log(f"  {len(rebal)} rebalances {rebal[0].date()} → {rebal[-1].date()}")

    universe_all = list(prices.columns)

    # -------- Run each tier --------
    tier_navs = {}
    holdings_log_rows = []

    for tier_id, spec in TIER_SPECS.items():
        log(f"--- {tier_id}: {spec['name']} ---")
        nav = INITIAL_CAP
        equity_value, cash_value = 0.0, INITIAL_CAP
        daily_nav = pd.Series(index=trading_days, dtype=float)
        prev_holdings = set()

        for i, rd in enumerate(rebal):
            # 1. Score + select
            scored = score_asof(rd, universe_all)
            picks = select_for_tier(scored, spec)
            if len(picks) < 3:
                continue

            # 2. Regime overlay
            R_rd = float(R_t.loc[:rd].iloc[-1]) if R_t.loc[:rd].notna().any() else 0.5
            cash_pct = min(spec["cash_max"], spec["cash_floor"] + R_rd * spec["cash_slope"])
            cash_pct = max(cash_pct, spec["cash_floor"])
            equity_pct = 1.0 - cash_pct

            # 3. Cost (one-way turnover × 10 bps)
            new_set = set(picks)
            if i == 0:
                turn = 1.0 if equity_pct > 0 else 0.0
            else:
                # Symmetric difference / (2 × N) is one-way ratio over the equity sleeve
                sym = len(prev_holdings ^ new_set)
                turn = sym / (2 * max(len(new_set), 1)) if new_set else 0.0
            cost = COST_RT * turn * equity_pct
            nav *= (1 - cost)
            equity_value = nav * equity_pct
            cash_value   = nav * cash_pct
            daily_nav.loc[rd] = nav

            # Log
            holdings_log_rows.append({
                "date": rd.date(), "tier": tier_id, "R_t": round(R_rd, 3),
                "cash_pct": round(cash_pct, 3), "n_holdings": len(picks),
                "turnover": round(turn, 3),
                "holdings": ",".join(picks),
            })

            # 4. Walk daily through next rebalance
            end_hold = rebal[i + 1] if i + 1 < len(rebal) else END
            hold_idx = prices.loc[rd:end_hold].index
            if len(hold_idx) < 2:
                prev_holdings = new_set
                continue
            # Daily return of equal-weight portfolio
            sub = prices.loc[hold_idx, picks]
            day_ret = sub.pct_change().iloc[1:].mean(axis=1)
            for d, r in day_ret.items():
                if pd.isna(r): r = 0
                equity_value *= (1 + r)
                cash_value   *= (1 + daily_cash.get(d, 0))
                nav = equity_value + cash_value
                daily_nav.loc[d] = nav
            prev_holdings = new_set

        tier_navs[tier_id] = daily_nav.dropna()
        p = perf(tier_navs[tier_id])
        log(f"   CAGR={p['cagr']:.2%}  Sharpe={p['sharpe']:.2f}  MaxDD={p['max_drawdown']:.1%}  FinalNAV ${p['final_nav']:,.0f}")

    # -------- Benchmarks ($100K notional, buy & hold/rebalance) --------
    log("building benchmarks...")
    inception = rebal[0]
    spy_full = sect["spy"].dropna().reindex(trading_days).ffill()
    qqq_full = sect["qqq"].dropna().reindex(trading_days).ffill()
    tlt_full = vol["tlt"].dropna().reindex(trading_days).ffill()
    def bh(series, start_cap=INITIAL_CAP):
        sub = series.loc[inception:END]
        return (sub / sub.iloc[0]) * start_cap
    spy_nav = bh(spy_full)
    qqq_nav = bh(qqq_full)
    # 60/40 rebalanced monthly
    nav = INITIAL_CAP
    s_60_40 = pd.Series(index=trading_days, dtype=float)
    for i, rd in enumerate(rebal):
        if rd not in spy_full.index or rd not in tlt_full.index: continue
        spu = (nav * 0.6) / spy_full.loc[rd]
        ttu = (nav * 0.4) / tlt_full.loc[rd]
        end_hold = rebal[i + 1] if i + 1 < len(rebal) else END
        idx = spy_full.loc[rd:end_hold].index
        for d in idx:
            if d in tlt_full.index:
                s_60_40.loc[d] = spu * spy_full.loc[d] + ttu * tlt_full.loc[d]
        last = idx[-1]
        if not pd.isna(s_60_40.loc[last]):
            nav = s_60_40.loc[last]
    s_60_40 = s_60_40.dropna()
    # SSO synthetic 1.5x SPY daily return
    rr = spy_full.pct_change().fillna(0)
    sso_nav_full = (1 + 1.5 * rr).cumprod()
    sso_nav = (sso_nav_full.loc[inception:END] / sso_nav_full.loc[inception]) * INITIAL_CAP

    eq = pd.DataFrame({**tier_navs, "spy": spy_nav, "qqq": qqq_nav, "60_40": s_60_40, "sso": sso_nav})
    eq = eq.dropna(how="all").ffill()
    eq.index.name = "date"
    eq.to_csv(DATA / "backtest_equity_curves.csv")
    log(f"  saved data/backtest_equity_curves.csv ({eq.shape})")

    metrics = {col: perf(eq[col]) for col in eq.columns}
    # Info ratio vs benchmark per tier
    bench_map = {"1_cap_pres": "60_40", "2_balanced": "spy",
                 "3_aggressive": "qqq", "4_tactical": "sso"}
    for tid, bcol in bench_map.items():
        if tid in eq.columns and bcol in eq.columns:
            n = eq[tid].pct_change().dropna()
            b = eq[bcol].pct_change().reindex(n.index).dropna()
            n, b = n.reindex(b.index), b
            active = (n - b).dropna()
            ir = (active.mean() / active.std()) * np.sqrt(252) if active.std() > 0 else 0
            metrics[tid]["info_ratio_vs_benchmark"] = round(float(ir), 3)
            # Beta
            if b.var() > 0:
                metrics[tid]["beta_to_benchmark"] = round(float(np.cov(n, b)[0,1] / b.var()), 3)
            metrics[tid]["benchmark"] = bcol

    metrics["_meta"] = {
        "start": str(rebal[0].date()),
        "end":   str(rebal[-1].date()),
        "n_rebalances": len(rebal),
        "initial_capital_per_tier": INITIAL_CAP,
        "transaction_cost_bps": int(COST_RT * 10000),
        "limitations": [
            "Fundamentals use a current snapshot — look-ahead bias by construction (Phase 1).",
            "Universe = current S&P 500 + 50 midcaps → survivorship bias.",
        ],
    }
    with open(DATA / "backtest_metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    pd.DataFrame(holdings_log_rows).to_csv(DATA / "backtest_holdings_log.csv", index=False)
    log(f"  saved data/backtest_metrics.json + backtest_holdings_log.csv")
    log(f"total elapsed: {time.time() - T0:.1f}s")
    log("DONE")


if __name__ == "__main__":
    main()
