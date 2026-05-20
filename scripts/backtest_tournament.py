"""
Historical equity-curve backtest for the tournament.

Run once locally — uses Phase 1 data from ../phase1_data/output/.
Holdings are FIXED per tier (from config.json). The only active element is the
regime overlay adjusting the cash sleeve. Tickers that didn't exist yet at a given
rebalance date get zero weight; their weight is redistributed equally.

Outputs:
  data/backtest_equity_curves.csv   daily NAV for each tier + benchmarks
  data/backtest_metrics.json        CAGR / Sharpe / MaxDD / Calmar per tier
  charts/backtest_tournament.pdf    log-scale equity + drawdown ribbons (Palatino)
"""
from __future__ import annotations
import argparse, json, time, warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from scipy.stats import norm

warnings.filterwarnings("ignore")

# Palatino
matplotlib.rcParams["font.family"] = "serif"
matplotlib.rcParams["font.serif"] = ["Palatino", "Palatino Linotype", "Book Antiqua", "serif"]
matplotlib.rcParams["mathtext.fontset"] = "stix"
matplotlib.rcParams["axes.grid"] = True
matplotlib.rcParams["grid.alpha"] = 0.3
matplotlib.rcParams["axes.spines.top"]   = False
matplotlib.rcParams["axes.spines.right"] = False
matplotlib.rcParams["axes.linewidth"]    = 0.6
matplotlib.rcParams["figure.dpi"]        = 110

REPO_ROOT  = Path(__file__).resolve().parent.parent
DATA_DIR   = REPO_ROOT / "data"
CHARTS_DIR = REPO_ROOT / "charts"
DATA_DIR.mkdir(exist_ok=True); CHARTS_DIR.mkdir(exist_ok=True)

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
        "final_nav": round(float(nav.iloc[-1]), 4),
    }


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="../phase1_data/output",
                    help="Path to Phase 1 fetched parquet files")
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--end",   default="2026-04-30")
    return ap.parse_args()


def build_ews_R(vol: pd.DataFrame, vold: pd.DataFrame, fred: pd.DataFrame,
                fredd: pd.DataFrame, breadth: pd.DataFrame,
                trading_days: pd.DatetimeIndex) -> pd.Series:
    """Reproduce Phase 1 equal-weight R_t (16 indicators)."""
    ind_specs = [
        ("VIX",  vol["vix"],  +1),
        ("VVIX/VIX", vold["vvix_vix"], +1),
        ("VIX term (1m-3m)", vold["vix_term"], +1),
        ("SKEW", vol["skew"], +1),
        ("SPX realized vol 20d", vold["spx_realized_vol_20d"], +1),
        ("HYG/LQD ratio", vold["hyg_lqd_ratio"], -1),
        ("Baa-Aaa spread", fredd["baa_aaa_spread"], +1),
        ("Initial claims (4w)", fred["claims_4wk"], +1),
        ("Claims dist from low", fredd["claims_dist_from_low"], +1),
        ("Yield 2s10s", fredd["yield_2s10s"], -1),
        ("NFCI", fred["nfci"], +1),
        ("ANFCI", fred["anfci"], +1),
        ("Gold/SPX", vold["gold_spx"], +1),
        ("TLT/SPX", vold["tlt_spx"], +1),
        ("Defensive/Cyclical", breadth["def_cyc"], +1),
        ("SPX return 60d", vold["spx_return_60d"], -1),
        ("SPX drawdown", vold["spx_drawdown"], -1),
    ]
    ind_df = pd.DataFrame(index=trading_days)
    for label, s, _ in ind_specs:
        ind_df[label] = s.reindex(trading_days).ffill()
    mu  = ind_df.rolling(252, min_periods=126).mean()
    sig = ind_df.rolling(252, min_periods=126).std()
    z   = (ind_df - mu) / sig
    signs = pd.Series({label: s for label, _, s in ind_specs})
    phi = pd.DataFrame(norm.cdf(z.multiply(signs, axis=1).values),
                       index=z.index, columns=z.columns)
    return phi.mean(axis=1).rename("R_t")


def main():
    args = parse_args()
    data_root = Path(args.data_dir).resolve()
    log(f"data_dir: {data_root}")
    log("loading Phase 1 data...")

    prices = pd.read_parquet(data_root / "prices_daily.parquet")
    if "SPY_volume" in prices.columns:
        prices = prices.drop(columns=["SPY_volume"])
    prices.index = pd.to_datetime(prices.index)
    fred  = pd.read_parquet(data_root / "fred_indicators.parquet"); fred.index = pd.to_datetime(fred.index)
    fredd = pd.read_parquet(data_root / "fred_derived.parquet");   fredd.index = pd.to_datetime(fredd.index)
    vol   = pd.read_parquet(data_root / "vol_indicators.parquet"); vol.index = pd.to_datetime(vol.index)
    vold  = pd.read_parquet(data_root / "vol_derived.parquet");    vold.index = pd.to_datetime(vold.index)
    sect  = pd.read_parquet(data_root / "sector_etfs.parquet");    sect.index = pd.to_datetime(sect.index)
    breadth = pd.read_parquet(data_root / "breadth_indicators.parquet"); breadth.index = pd.to_datetime(breadth.index)

    spx = vol["spx"].dropna()
    trading_days = spx.index
    log(f"  prices: {prices.shape}, trading days: {len(trading_days)}")

    log("computing R_t...")
    R_t = build_ews_R(vol, vold, fred, fredd, breadth, trading_days)
    log(f"  R_t range: {R_t.min():.3f} → {R_t.max():.3f}")

    log("loading config.json...")
    with open(REPO_ROOT / "config.json") as f:
        config = json.load(f)

    # EFFR daily cash return series (Phase 1 fetched it)
    effr = fred["effr"].reindex(trading_days).ffill().fillna(0)
    daily_cash_ret = effr / 252.0 / 100.0

    # Backtest window
    START = pd.Timestamp(args.start)
    END   = pd.Timestamp(args.end)
    months = pd.date_range(START, END, freq="MS")
    rebalance_dates = []
    for ms in months:
        after = prices.index[prices.index >= ms]
        if len(after) > 0 and after[0] <= END:
            rebalance_dates.append(after[0])
    rebalance_dates = pd.DatetimeIndex(rebalance_dates)
    log(f"  {len(rebalance_dates)} rebalances {rebalance_dates[0].date()} → {rebalance_dates[-1].date()}")

    def run_tier(tier_cfg: dict, color: str, tier_id: str):
        """Walk daily for this tier. Equal-weight inside the tier's holdings list,
           with cash sleeve sized by the tier's cash_formula(R_t). Tickers absent
           from the universe at date d are dropped from the weight set and weight
           is redistributed equally."""
        holdings_list = list(tier_cfg.get("holdings", {}).keys())
        # Restrict to tickers we have prices for
        avail = [t for t in holdings_list if t in prices.columns]
        if not avail:
            log(f"  WARN tier {tier_id}: no tickers found in price data")
            return None
        cash_formula = tier_cfg["cash_formula"]
        cash_floor   = float(tier_cfg["cash_floor"])

        def eval_cash_pct(R):
            try:
                return max(float(eval(cash_formula,
                                      {"__builtins__": {}, "min": min, "max": max, "R": R})),
                           cash_floor)
            except Exception:
                return min(1.0, cash_floor + R * (1.0 - cash_floor))

        nav = 1.0
        cash_value = 0.0
        equity_value = 1.0
        daily_nav = pd.Series(index=trading_days, dtype=float)

        # initial NAV at first rebal
        first = rebalance_dates[0]
        # Eligible tickers at first rebal (≥252 prior trading days of price history)
        eligible_now = [t for t in avail if prices[t].loc[:first].dropna().shape[0] >= 252]
        if not eligible_now:
            return None

        for i, rd in enumerate(rebalance_dates):
            eligible = [t for t in avail if prices[t].loc[:rd].dropna().shape[0] >= 200]
            if not eligible:
                continue
            R_rd = float(R_t.loc[:rd].iloc[-1]) if R_t.loc[:rd].notna().any() else 0.5
            cash_pct = eval_cash_pct(R_rd)
            equity_pct = 1.0 - cash_pct
            # rebalance: equal-weight on eligible tickers
            equity_value = nav * equity_pct
            cash_value   = nav * cash_pct
            daily_nav.loc[rd] = nav

            end_hold = rebalance_dates[i + 1] if i + 1 < len(rebalance_dates) else END
            hold_idx = prices.loc[rd:end_hold].index
            if len(hold_idx) < 2:
                continue
            sub = prices.loc[hold_idx, eligible]
            # Daily return of equal-weight portfolio
            daily_ret = sub.pct_change().iloc[1:].mean(axis=1)
            for d, r in daily_ret.items():
                equity_value *= (1 + r)
                cash_value   *= (1 + daily_cash_ret.get(d, 0))
                nav = equity_value + cash_value
                daily_nav.loc[d] = nav
        return daily_nav.dropna()

    tier_navs = {}
    for tier_id, tier_cfg in config["tiers"].items():
        log(f"--- tier {tier_id}: {tier_cfg['name']} ---")
        tier_navs[tier_id] = run_tier(tier_cfg, tier_cfg["color"], tier_id)
        if tier_navs[tier_id] is not None:
            p = perf(tier_navs[tier_id])
            log(f"   CAGR={p['cagr']:.2%}  Sharpe={p['sharpe']:.2f}  MaxDD={p['max_drawdown']:.1%}")

    # Benchmarks
    log("building benchmarks...")
    spy = sect["spy"].dropna().reindex(trading_days).ffill().loc[rebalance_dates[0]:END]
    spy = spy / spy.iloc[0]
    qqq = sect["qqq"].dropna().reindex(trading_days).ffill().loc[rebalance_dates[0]:END]
    qqq = qqq / qqq.iloc[0]
    # Synthetic SSO = 1.5× SPY daily
    spy_full = sect["spy"].dropna().reindex(trading_days).ffill()
    sso_full = (1 + 1.5 * spy_full.pct_change().fillna(0)).cumprod().loc[rebalance_dates[0]:END]
    sso = sso_full / sso_full.iloc[0]
    # 60/40 SPY/TLT monthly rebalance
    tlt = vol["tlt"].dropna().reindex(trading_days).ffill()
    bench_6040 = pd.Series(index=trading_days, dtype=float)
    nav = 1.0
    for i, rd in enumerate(rebalance_dates):
        if rd not in spy_full.index or rd not in tlt.index: continue
        spu = (nav * 0.6) / spy_full.loc[rd]
        ttu = (nav * 0.4) / tlt.loc[rd]
        end_hold = rebalance_dates[i + 1] if i + 1 < len(rebalance_dates) else END
        for d in spy_full.loc[rd:end_hold].index:
            if d in tlt.index:
                bench_6040.loc[d] = spu * spy_full.loc[d] + ttu * tlt.loc[d]
        if not pd.isna(bench_6040.loc[spy_full.loc[rd:end_hold].index[-1]]):
            nav = bench_6040.loc[spy_full.loc[rd:end_hold].index[-1]]
    bench_6040 = bench_6040.dropna()
    bench_6040 = bench_6040 / bench_6040.iloc[0]

    equity_curves = pd.DataFrame({**tier_navs,
                                  "spy": spy, "qqq": qqq, "sso": sso, "60_40": bench_6040})
    equity_curves = equity_curves.dropna(how="all").ffill()
    equity_curves.index.name = "date"
    equity_curves.to_csv(DATA_DIR / "backtest_equity_curves.csv")
    log(f"  saved data/backtest_equity_curves.csv  ({equity_curves.shape})")

    metrics = {}
    for col in equity_curves.columns:
        metrics[col] = perf(equity_curves[col])
    metrics["_meta"] = {
        "rebalance_start": str(rebalance_dates[0].date()),
        "rebalance_end":   str(rebalance_dates[-1].date()),
        "n_rebalances":    len(rebalance_dates),
        "cash_yield":      "EFFR daily",
    }
    with open(DATA_DIR / "backtest_metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    log(f"  saved data/backtest_metrics.json")

    # --- Chart ---
    chart_pdf = CHARTS_DIR / "backtest_tournament.pdf"
    with PdfPages(chart_pdf) as pdf:
        fig, axes = plt.subplots(2, 1, figsize=(12, 9), sharex=True,
                                 gridspec_kw={"height_ratios": [3, 1.4]})
        ax1, ax2 = axes
        ax1.plot(equity_curves.index, equity_curves["spy"], color="#6b7280", linestyle="--",
                 linewidth=1.0, label=f"SPY (CAGR {metrics['spy']['cagr']:.1%})")
        for tier_id, cfg in config["tiers"].items():
            if tier_id not in equity_curves: continue
            p = metrics[tier_id]
            ax1.plot(equity_curves.index, equity_curves[tier_id], color=cfg["color"],
                     linewidth=1.3,
                     label=f"{cfg['name']} (CAGR {p['cagr']:.1%}, Sharpe {p['sharpe']:.2f})")
        ax1.set_yscale("log"); ax1.set_ylabel("NAV (log, start=1.0)")
        ax1.set_title(f"Tournament Backtest  {rebalance_dates[0].date()} → {rebalance_dates[-1].date()}")
        ax1.legend(loc="upper left", frameon=False, fontsize=9)

        dd_spy = (equity_curves["spy"] / equity_curves["spy"].cummax() - 1) * 100
        ax2.fill_between(dd_spy.index, dd_spy.values, 0, color="#6b7280", alpha=0.15, label="SPY")
        for tier_id, cfg in config["tiers"].items():
            if tier_id not in equity_curves: continue
            nav = equity_curves[tier_id]
            dd = (nav / nav.cummax() - 1) * 100
            ax2.plot(dd.index, dd.values, color=cfg["color"], linewidth=0.9, label=cfg["name"])
        ax2.set_ylabel("Drawdown (%)")
        ax2.axhline(-10, color="#dc2626", linewidth=0.5, linestyle=":")
        ax2.legend(loc="lower left", frameon=False, fontsize=8, ncol=3)
        fig.tight_layout(); pdf.savefig(fig); plt.close(fig)
    log(f"  saved {chart_pdf}")

    log(f"total elapsed: {time.time() - T0:.1f}s")
    log("DONE")


if __name__ == "__main__":
    main()
