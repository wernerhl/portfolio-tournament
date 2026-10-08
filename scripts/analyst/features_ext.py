#!/usr/bin/env python3
"""
features_ext.py — the design workspace's 43 variables as an optional feature set of the single harness (follow-up
order of 7 October 2026, F5; adapted from research/ml_stratification_test/feats2.py).

Price variables (21), from the provider's daily bars (dividend-adjusted closes for returns, split-adjusted closes
for dollar volume, volume) and SPY: mom_12_1, mom_6_1, mom_12_7, rev_1m, mom_36_13, vol_63, beta_252, ivol_126,
resmom_12_1, hi52, dd_3y, d200, skew_126, pctpos_252, dvol, volchg, max5, ejump, mom_accel, season, sec_mom.
Fundamental variables (22), from the EDGAR trailing-twelve-month records (scripts/analyst/sec_facts.py) joined to
each month-end by their filing date with merge_asof (at most 200 days old): f_ey, f_fcfy, f_sy, f_bm, f_gpa, f_roe,
f_opm, f_cfoa, f_rev_g, f_rev_gq, f_rev_acc, f_oi_g, f_ni_g, f_sue, f_ag, f_capex_a, f_capex_g, f_acc, f_sh_g, f_rd_s,
f_lev, f_size.

Two deliberate departures from feats2.py, both look-ahead repairs the first run of that test had shown: the
membership comes from the dated membership file (never the current list), and the sector momentum uses the
provider's current sector label only where the name has one, WITHOUT dropping names that lack it (feats2 dropped
them, which removed the delisted names: `memb & secs.notna()`); a name without a sector gets sec_mom missing.
The liquidity filter (63-day dollar volume of at least $3 million) is kept as a flag `liquid`, not a filter, so the
harness can apply it as one of the reconciliation steps.

Inputs: the daily bars dumped by fetch_history (--daily-dump, kept outside the repository), data/source/sector_etfs.parquet
(SPY), the raw history (splits), data/analyst/history/sec_fund_records_*.parquet, the membership file, and the
canonical fundamentals' sector labels.
Output: data/analyst/panel_ext_monthly.parquet (month_end, ticker, member, liquid, the 43 raw variables).

Usage:  python scripts/analyst/features_ext.py --daily A.parquet [--daily B.parquet ...]
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
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
REPO = HERE.parent.parent
AN = REPO / "data" / "analyst"
OUT = AN / "panel_ext_monthly.parquet"
PRICE_VARS = ["mom_12_1", "mom_6_1", "mom_12_7", "rev_1m", "mom_36_13", "vol_63", "beta_252", "ivol_126", "resmom_12_1", "hi52", "dd_3y", "d200",
              "skew_126", "pctpos_252", "dvol", "volchg", "max5", "ejump", "mom_accel", "season", "sec_mom"]
FUND_VARS = ["f_ey", "f_fcfy", "f_sy", "f_bm", "f_gpa", "f_roe", "f_opm", "f_cfoa", "f_rev_g", "f_rev_gq", "f_rev_acc", "f_oi_g", "f_ni_g", "f_sue",
             "f_ag", "f_capex_a", "f_capex_g", "f_acc", "f_sh_g", "f_rd_s", "f_lev", "f_size"]
ALL_VARS = PRICE_VARS + FUND_VARS


def log(m: str) -> None:
    print(f"[features_ext] {m}", flush=True)


def load_daily(paths: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    frames = [pd.read_parquet(p) for p in paths]
    d = pd.concat(frames)
    d.index = pd.to_datetime(d.index).tz_localize(None) if getattr(d.index, "tz", None) is not None else pd.to_datetime(d.index)
    d = d[~d.reset_index().duplicated(subset=["date", "ticker"] if "date" in d.reset_index().columns else [d.index.name or "index", "ticker"], keep="last").values]
    C = d.pivot_table(index=d.index, columns="ticker", values="Adj Close")
    U = d.pivot_table(index=d.index, columns="ticker", values="Close")
    V = d.pivot_table(index=d.index, columns="ticker", values="Volume")
    return C.sort_index(), U.sort_index(), V.sort_index()


def price_features(C: pd.DataFrame, U: pd.DataFrame, V: pd.DataFrame, spy: pd.Series, sectors: pd.Series, me: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    r = C.pct_change(fill_method=None); r = r.where(r.abs() < 1.5)
    m = spy.reindex(C.index).pct_change(fill_method=None)
    F = {}
    F["mom_12_1"] = C.shift(21) / C.shift(252) - 1
    F["mom_6_1"] = C.shift(21) / C.shift(126) - 1
    F["mom_12_7"] = C.shift(126) / C.shift(252) - 1
    F["rev_1m"] = C / C.shift(21) - 1
    F["mom_36_13"] = C.shift(252) / C.shift(756) - 1
    F["vol_63"] = r.rolling(63, min_periods=40).std()
    cov = r.rolling(252, min_periods=150).cov(m); var = m.rolling(252, min_periods=150).var()
    beta = cov.div(var, axis=0); F["beta_252"] = beta
    res = r - beta.shift(1).mul(m, axis=0)
    F["ivol_126"] = res.rolling(126, min_periods=80).std()
    rs = res.rolling(231, min_periods=150).sum().shift(21); rsd = res.rolling(231, min_periods=150).std().shift(21)
    F["resmom_12_1"] = rs / (rsd * np.sqrt(231))
    F["hi52"] = C / C.rolling(252, min_periods=150).max()
    F["dd_3y"] = C / C.rolling(756, min_periods=250).max()
    F["d200"] = C / C.rolling(200, min_periods=150).mean() - 1
    F["skew_126"] = r.rolling(126, min_periods=80).skew()
    F["pctpos_252"] = (r > 0).where(r.notna()).rolling(252, min_periods=150).mean()
    dv = U * V
    F["dvol"] = np.log(dv.rolling(63, min_periods=40).mean().replace(0, np.nan))
    F["volchg"] = V.rolling(21, min_periods=15).mean() / V.rolling(252, min_periods=150).mean()
    Fm = {k: v.reindex(me) for k, v in F.items()}
    # max5 and ejump at month-ends only (feats2's loop)
    ra, va = r.values, V.values
    idx = {d: i for i, d in enumerate(C.index)}
    max5 = pd.DataFrame(index=me, columns=C.columns, dtype=float); ej = max5.copy()
    vrel = (V / V.rolling(63, min_periods=40).mean().shift(1)).values
    for d in me:
        i = idx.get(d)
        if i is None or i < 70:
            continue
        w = ra[i - 20:i + 1]; s = np.sort(np.nan_to_num(w, nan=-9), axis=0)[-5:]; s[s == -9] = np.nan; max5.loc[d] = np.nanmean(s, axis=0)
        vw = vrel[i - 62:i]; rw = ra[i - 62:i + 1]
        ok = ~np.all(np.isnan(vw), axis=0); j = np.zeros(vw.shape[1], dtype=int); j[ok] = np.nanargmax(np.nan_to_num(vw[:, ok], nan=-9), axis=0)
        cols = np.arange(vw.shape[1]); jr = np.nan_to_num(rw[j, cols]) + np.nan_to_num(rw[np.minimum(j + 1, rw.shape[0] - 1), cols]); jr[~ok] = np.nan; ej.loc[d] = jr
    Fm["max5"] = max5; Fm["ejump"] = ej
    Fm["mom_accel"] = Fm["mom_6_1"] - Fm["mom_12_7"]
    Pm = C.reindex(me); rm = Pm.pct_change(fill_method=None)
    Fm["season"] = sum(rm.shift(12 * k - 1) for k in range(1, 6)) / 5
    secs = sectors.reindex(C.columns)
    m6 = Fm["mom_6_1"]; secmom = pd.DataFrame(np.nan, index=me, columns=C.columns)
    for s_ in secs.dropna().unique():
        cs = secs.index[secs == s_]
        secmom[cs] = np.repeat(m6[cs].mean(axis=1).values[:, None], len(cs), axis=1)
    Fm["sec_mom"] = secmom
    return Fm


def fund_features(R: pd.DataFrame, grid: pd.DataFrame, Um: pd.DataFrame) -> pd.DataFrame:
    """feats2's fundamental ratios at each (month-end, ticker) of the grid from the latest record filed at most
    200 days before the month-end (merge_asof on the filing date)."""
    R = R.sort_values(["avail", "end"]).copy(); R["avail"] = pd.to_datetime(R["avail"]).astype("datetime64[ns]"); R = R.rename(columns={"tic": "ticker"})
    grid = grid.sort_values("date").copy(); grid["date"] = pd.to_datetime(grid["date"]).astype("datetime64[ns]")
    M = pd.merge_asof(grid, R, left_on="date", right_on="avail", by="ticker", direction="backward", tolerance=pd.Timedelta(days=200))
    px = [Um.at[d, t] if (d in Um.index and t in Um.columns) else np.nan for d, t in zip(M.date, M.ticker)]
    M["px"] = px; M["mcap"] = M.px * M.shares_adj
    pos = lambda x: x.where(x > 0)   # noqa: E731
    M["f_ey"] = M.ni / pos(M.mcap); M["f_fcfy"] = (M.cfo - M.capex.fillna(0)) / pos(M.mcap); M["f_sy"] = M.rev / pos(M.mcap); M["f_bm"] = M.equity / pos(M.mcap)
    M["f_gpa"] = M.gp / pos(M.assets); M["f_roe"] = M.ni / pos(M.equity); M["f_opm"] = M.oi / pos(M.rev); M["f_cfoa"] = M.cfo / pos(M.assets)
    M["f_rev_g"] = M.rev / pos(M.rev_l4) - 1; M["f_rev_gq"] = (M.rev - M.rev_l1) / (pos(M.rev_l4) / 4); M["f_rev_acc"] = M.f_rev_g - (M.rev_l1 / pos(M.rev_l5) - 1)
    M["f_oi_g"] = (M.oi - M.oi_l4) / pos(M.assets); M["f_ni_g"] = (M.ni - M.ni_l4) / pos(M.assets); M["f_sue"] = M.sue
    M["f_ag"] = M.assets / pos(M.assets_l4) - 1; M["f_capex_a"] = M.capex / pos(M.assets); M["f_capex_g"] = M.capex / pos(M.capex_l4) - 1
    M["f_acc"] = (M.ni - M.cfo) / pos(M.assets); M["f_sh_g"] = M.shares_adj / pos(M.sh_l4) - 1; M["f_rd_s"] = M.rd / pos(M.rev); M["f_lev"] = 1 - M.equity / pos(M.assets); M["f_size"] = np.log(pos(M.mcap))
    M["has_fund"] = M.avail.notna() & M.mcap.notna() & M.assets.notna()
    return M[["date", "ticker", "has_fund"] + FUND_VARS]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily", action="append", required=True, help="parquet of daily bars (ticker, Close, Adj Close, Volume ...), repeatable")
    ap.add_argument("--records", default=None, help="sec_fund_records parquet (default: the latest in data/analyst/history)")
    ap.add_argument("--from", dest="start", default="2012-01-31")
    a = ap.parse_args()
    C, U, V = load_daily(a.daily)
    etf = pd.read_parquet(REPO / "data" / "source" / "sector_etfs.parquet"); etf.index = pd.to_datetime(etf.index)
    spy = etf["spy"].sort_index()
    sectors = pd.Series({tk.upper(): (v or {}).get("sector") or None for tk, v in (json.loads((REPO / "data" / "canonical" / "fundamentals.json").read_text()).get("tickers") or {}).items()})
    mem = pd.read_parquet(AN / "sp500_membership_history.parquet"); mem["month_end"] = pd.to_datetime(mem["month_end"])
    me_all = C.groupby([C.index.year, C.index.month]).tail(1).index
    me = me_all[(me_all >= pd.Timestamp(a.start)) & (me_all.to_period("M") < pd.Timestamp.today().to_period("M"))]
    log(f"daily bars {C.shape}, {len(me)} month-ends {me[0].date()}..{me[-1].date()}, sectors known for {int(sectors.reindex(C.columns).notna().sum())} of {C.shape[1]} names")
    Fm = price_features(C, U, V, spy, sectors, me)
    rows = []
    for k, v in Fm.items():
        s = v.stack(); s.name = k; rows.append(s)
    P = pd.concat(rows, axis=1).reset_index(); P.columns = ["date", "ticker"] + list(Fm.keys())
    P["p"] = P["date"].dt.to_period("M")
    if "ticker_current" in mem.columns: mem = mem.assign(ticker=mem["ticker_current"])                 # G2: members by their current symbol
    mem_set = mem.assign(p=mem["month_end"].dt.to_period("M"))[["p", "ticker"]].drop_duplicates(); mem_set["member"] = True
    P = P.merge(mem_set, on=["p", "ticker"], how="left"); P["member"] = P["member"].fillna(False).astype(bool)
    P["liquid"] = P["dvol"] >= np.log(3e6)
    rec_p = Path(a.records) if a.records else sorted((AN / "history").glob("sec_fund_records_*.parquet"))[-1]
    R = pd.read_parquet(rec_p)
    Um = U.reindex(me)
    Fd = fund_features(R, P[["date", "ticker"]].copy(), Um)
    P = P.merge(Fd, on=["date", "ticker"], how="left")
    P = P.rename(columns={"date": "month_end"}).drop(columns=["p"])
    for v in ALL_VARS:
        P[v] = P[v].astype("float32")
    AN.mkdir(parents=True, exist_ok=True)
    P = P[P["member"]].reset_index(drop=True)                    # the harness uses members only; the file stays small
    P.to_parquet(OUT, index=False, compression="zstd")
    mm = P[P["member"]]
    log(f"wrote {OUT.name}: {len(P)} rows, {P['ticker'].nunique()} names; members with fundamentals by year: "
        + ", ".join(f"{y} {v:.2f}" for y, v in mm.groupby(mm["month_end"].dt.year)["has_fund"].mean().items() if y % 2 == 0 or y >= 2024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
