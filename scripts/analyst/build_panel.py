#!/usr/bin/env python3
"""
build_panel.py — Task B2 of the free-analyst-data order (7 October 2026): the analyst variables at each month-end
from the raw history (task B1), ranked across the index members of that month.

At each month-end t (the last session of the calendar month), using only rows whose timestamp is at or before the
close of t (16:00 ET; rating timestamps are UTC in the raw file and converted):

  an_net_up_90         (upgrades - downgrades) in the last 90 days / the number of rating actions in the window;
                       missing with no action
  an_pt_rev_90         median of (current target / prior target - 1) over the price-target CHANGES of the window
                       (both targets present and different; a reiterated target is not a change)
  an_pt_gap            median current target of the window / the price at t - 1, both on the share basis of t
                       (targets are nominal at their date: a split between the row and t divides the target; the
                       split-adjusted close at t is multiplied back by the splits after t)
  an_n_act_90          the number of analyst actions in the window (attention)
  an_surprise          surprise % at the latest report at or before t, if that report is within 100 days of t
  an_sue               (reported - estimate) at the latest report / the standard deviation of that difference over
                       the previous 8 reports (at least 4 of them)
  an_surprise_streak   consecutive positive surprises up to the latest report

An earnings row counts only with a reported EPS and an effective date at or before t; a report after the close
(16:00 ET or later) is effective the next trading day. Each variable is ranked across the S&P 500 members of the
month (data/analyst/sp500_membership_history.parquet) and scaled to [-0.5, 0.5] (average ranks for ties, the
lowest -0.5, the highest +0.5); a name that is not a member that month gets its position within the members'
distribution and member=False. The coverage report counts members only.

Outputs: data/analyst/panel_monthly.parquet (month_end, ticker, member, price, the raw variables, their ranks
         `<var>_rk`, and the inputs behind them) and data/analyst/coverage.json (coverage by year per variable; the
         first year in which the price-target columns are filled for at least half of the members).

Usage:  python scripts/analyst/build_panel.py [--stamp 2026-10-07] [--from 2012-01-31]
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
sys.path.insert(0, str(HERE.parent))
REPO = HERE.parent.parent
AN = REPO / "data" / "analyst"
HIST = AN / "history"
MEMBERS = AN / "sp500_membership_history.parquet"
OUT = AN / "panel_monthly.parquet"
COVER = AN / "coverage.json"
ET = "America/New_York"
VARS = ["an_net_up_90", "an_pt_rev_90", "an_pt_gap", "an_n_act_90", "an_surprise", "an_sue", "an_surprise_streak"]
WINDOW_DAYS, SURPRISE_DAYS, SUE_PRIOR, SUE_MIN = 90, 100, 8, 4


def log(m: str) -> None:
    print(f"[build_panel] {m}", flush=True)


def all_stamps() -> list[str]:
    """Every download in data/analyst/history, oldest first (a later download of a name supersedes an earlier one)."""
    stamps = sorted(p.name[len("upgrades_downgrades_"):-len(".parquet")] for p in HIST.glob("upgrades_downgrades_*.parquet"))
    if not stamps:
        raise SystemExit("no raw history in data/analyst/history (run fetch_history.py first)")
    return stamps


def read_all(name: str, stamps: list[str]) -> pd.DataFrame:
    """The union of the downloads of one table: a ticker's rows come from the latest download that holds it."""
    frames = {}
    for st in stamps:
        p = HIST / f"{name}_{st}.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        if not len(df):
            continue
        df["ticker"] = df["ticker"].astype(str)
        for tk, g in df.groupby("ticker"):
            frames[tk] = g
    cols = list(df.columns) if frames else ["ticker"]
    return pd.concat(frames.values(), ignore_index=True) if frames else pd.DataFrame(columns=cols)


def load_raw(stamp: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    stamps = [stamp] if stamp else all_stamps()
    r, e, s, m = (read_all(n, stamps) for n in ("upgrades_downgrades", "earnings_dates", "splits", "monthly_prices"))
    r["ts_et"] = pd.to_datetime(r["grade_date_utc"]).dt.tz_localize("UTC").dt.tz_convert(ET).dt.tz_localize(None)
    r["ticker"] = r["ticker"].astype(str); e["ticker"] = e["ticker"].astype(str)
    s["ticker"] = s["ticker"].astype(str); m["ticker"] = m["ticker"].astype(str)
    return r, e, s, m


def effective_dates(e: pd.DataFrame) -> pd.DataFrame:
    """A report at or after 16:00 ET is effective the next trading day."""
    from trading_calendar import is_trading_day
    from datetime import timedelta
    ts = pd.to_datetime(e["earnings_date_et"])
    eff = []
    for t in ts:
        d = t.date()
        if (t.hour, t.minute) >= (16, 0):
            d = d + timedelta(days=1)
            while not is_trading_day(d):
                d = d + timedelta(days=1)
        eff.append(pd.Timestamp(d))
    e = e.copy(); e["effective"] = eff
    return e


def month_ends(m: pd.DataFrame, start: str) -> list[pd.Timestamp]:
    """The last session of each calendar month, from the month-end bars across tickers (the latest bar of the month)."""
    me = m["month_end"]
    last = me.groupby(me.dt.to_period("M")).max()
    today = pd.Timestamp.today().normalize()
    out = [d for d in last if d >= pd.Timestamp(start) and d.to_period("M") < today.to_period("M")]   # completed months only
    return sorted(out)


def split_factor_after(splits: pd.DataFrame, tk: str, after: pd.Timestamp, upto: pd.Timestamp | None = None) -> float:
    s = splits[(splits["ticker"] == tk) & (splits["date"] > after)]
    if upto is not None:
        s = s[s["date"] <= upto]
    return float(np.prod(s["ratio"].values)) if len(s) else 1.0


def rank_scaled(values: pd.Series, member: pd.Series) -> pd.Series:
    """Ranks within the members, scaled to [-0.5, 0.5]; non-members placed within the members' distribution."""
    out = pd.Series(np.nan, index=values.index)
    mv = values[member & values.notna()]
    n = len(mv)
    if n == 0:
        return out
    if n == 1:
        out[mv.index] = 0.0
    else:
        rk = mv.rank(method="average")
        out[mv.index] = (rk - 1) / (n - 1) - 0.5
    others = values[(~member) & values.notna()]
    if len(others):
        arr = np.sort(mv.values)
        lo = np.searchsorted(arr, others.values, side="left"); hi = np.searchsorted(arr, others.values, side="right")
        pos = (lo + hi) / 2.0                                   # the average rank position among members (0..n)
        out[others.index] = (pos / max(n - 1, 1)) - 0.5 if n > 1 else 0.0
        out[others.index] = out[others.index].clip(-0.5, 0.5)
    return out


def month_variables(tk: str, t: pd.Timestamp, g: pd.DataFrame | None, ge: pd.DataFrame | None, splits: pd.DataFrame,
                    price: float, member: bool = True) -> dict:
    """The analyst variables of one name at the month-end t, from its rating rows g (ts_et, action, pt_current,
    pt_prior), its reported earnings rows ge (effective, eps_estimate, reported_eps, surprise_pct) and the split
    table, using only rows at or before the close of t (16:00 ET). Pure: a row after the close changes nothing."""
    cutoff = t + pd.Timedelta(hours=16)
    w0 = cutoff - pd.Timedelta(days=WINDOW_DAYS)
    rec = {"month_end": t, "ticker": tk, "member": bool(member), "price": float(price)}
    if g is not None and len(g):
        w = g[(g["ts_et"] > w0) & (g["ts_et"] <= cutoff)]
        n_act = len(w)
        rec["an_n_act_90"] = float(n_act)
        if n_act:
            up = int((w["action"] == "up").sum()); dn = int((w["action"] == "down").sum())
            rec["an_net_up_90"] = (up - dn) / n_act
            rec["n_up_90"], rec["n_down_90"] = up, dn
            ch = w[(w["pt_current"] > 0) & (w["pt_prior"] > 0) & (w["pt_current"] != w["pt_prior"])]
            if len(ch):
                rec["an_pt_rev_90"] = float(np.median(ch["pt_current"] / ch["pt_prior"] - 1.0))
                rec["n_pt_changes_90"] = int(len(ch))
            cur = w[w["pt_current"] > 0]
            if len(cur):
                # targets to the share basis of t, the close at t to its nominal basis
                adj = [float(v) / split_factor_after(splits, tk, ts, t) for v, ts in zip(cur["pt_current"], cur["ts_et"])]
                nominal_t = float(price) * split_factor_after(splits, tk, t)
                rec["pt_median_90"] = float(np.median(adj)); rec["price_nominal"] = nominal_t
                rec["an_pt_gap"] = float(np.median(adj)) / nominal_t - 1.0 if nominal_t > 0 else np.nan
                rec["n_pt_90"] = int(len(cur))
        else:
            rec["an_net_up_90"] = np.nan
    else:
        rec["an_n_act_90"] = 0.0
    if ge is not None and len(ge):
        past = ge[(ge["effective"] <= t) & ge["reported_eps"].notna()]
        if len(past):
            last = past.iloc[-1]
            age = (t - last["effective"]).days
            rec["last_report"] = last["effective"]; rec["last_report_age_days"] = int(age)
            if age <= SURPRISE_DAYS and pd.notna(last["surprise_pct"]):
                rec["an_surprise"] = float(last["surprise_pct"])
            diff = (past["reported_eps"] - past["eps_estimate"]).dropna()
            if len(diff) >= SUE_MIN + 1 and pd.notna(last["eps_estimate"]):
                prev = diff.iloc[-1 - SUE_PRIOR:-1]
                sd = float(prev.std(ddof=1)) if len(prev) >= SUE_MIN else np.nan
                if np.isfinite(sd) and sd > 0:
                    rec["an_sue"] = float(diff.iloc[-1]) / sd
            streak = 0
            for v in diff.iloc[::-1]:
                if v > 0:
                    streak += 1
                else:
                    break
            rec["an_surprise_streak"] = float(streak)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default=None, help="one download only (default: the union of every download, latest per name)")
    ap.add_argument("--from", dest="start", default="2012-01-31")
    a = ap.parse_args()
    stamp = a.stamp or "+".join(all_stamps())
    r, e, s, m = load_raw(a.stamp)
    e = effective_dates(e)
    e = e[e["reported_eps"].notna()].copy()                    # a row counts only with a reported EPS
    members = pd.read_parquet(MEMBERS) if MEMBERS.exists() else pd.DataFrame(columns=["month_end", "ticker"])
    members["month_end"] = pd.to_datetime(members["month_end"])
    _mcol = "ticker_current" if "ticker_current" in members.columns else "ticker"     # G2: members by their current symbol
    mem_by_month = {p: set(g[_mcol]) for p, g in members.groupby(members["month_end"].dt.to_period("M"))}
    tickers = sorted(set(m["ticker"]))
    mes = month_ends(m, a.start)
    log(f"raw {stamp}: {len(r)} rating rows, {len(e)} reported earnings rows, {len(s)} splits, {len(tickers)} tickers; "
        f"{len(mes)} month-ends {mes[0].date()}..{mes[-1].date()}; membership months {len(mem_by_month)}")
    r_by = {tk: g.sort_values("ts_et") for tk, g in r.groupby("ticker")}
    e_by = {tk: g.sort_values("effective") for tk, g in e.groupby("ticker")}
    px = m.set_index(["ticker", "month_end"])["close"]
    rows = []
    for t in mes:
        cutoff = t + pd.Timedelta(hours=16)                     # the close of t, ET
        w0 = cutoff - pd.Timedelta(days=WINDOW_DAYS)
        mem = mem_by_month.get(t.to_period("M"), set())
        for tk in tickers:
            price = px.get((tk, t))
            if price is None or not np.isfinite(price):
                continue
            rows.append(month_variables(tk, t, r_by.get(tk), e_by.get(tk), s, float(price), tk in mem))
    df = pd.DataFrame(rows)
    for v in VARS:
        if v not in df.columns:
            df[v] = np.nan
    parts = []
    for t, g in df.groupby("month_end"):
        g = g.copy()
        for v in VARS:
            g[v + "_rk"] = rank_scaled(g[v], g["member"])
        g["n_members_ranked"] = int(g["member"].sum())
        parts.append(g)
    df = pd.concat(parts, ignore_index=True).sort_values(["month_end", "ticker"]).reset_index(drop=True)
    AN.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    # coverage by year, members only
    mem_df = df[df["member"]]
    cov = {}
    for y, g in mem_df.groupby(mem_df["month_end"].dt.year):
        n_mem = g.groupby("month_end").size().mean()
        cov[int(y)] = {"members_with_price_avg": round(float(n_mem), 1),
                       **{v: round(float(g[v].notna().groupby(g["month_end"]).mean().mean()), 3) for v in VARS}}
    # the first year in which the price-target columns are filled for at least half of the members
    r_year = r.copy(); r_year["year"] = r_year["ts_et"].dt.year
    pt_year = {}
    for y, g in r_year.groupby("year"):
        mem_y = set().union(*[mem_by_month.get(p, set()) for p in pd.period_range(f"{y}-01", f"{y}-12", freq="M")]) if mem_by_month else set(g["ticker"])
        gm = g[g["ticker"].isin(mem_y)]
        with_rows = set(gm["ticker"]); with_pt = set(gm[gm["pt_current"] > 0]["ticker"])
        pt_year[int(y)] = {"members_with_rating_rows": len(with_rows), "members_with_a_price_target": len(with_pt),
                           "share": round(len(with_pt) / len(with_rows), 3) if with_rows else None}
    first_pt_year = next((y for y in sorted(pt_year) if (pt_year[y]["share"] or 0) >= 0.5 and pt_year[y]["members_with_rating_rows"] >= 100), None)
    report = {
        "cadence": "static", "as_of": datetime.now().strftime("%Y-%m-%d"), "raw_stamp": stamp,
        "order": "free-analyst-data order (7 October 2026), task B2/B3",
        "panel": {"file": "data/analyst/panel_monthly.parquet", "rows": int(len(df)), "month_ends": len(mes),
                  "first": str(mes[0].date()), "last": str(mes[-1].date()), "tickers": int(df["ticker"].nunique())},
        "ranking": "within the S&P 500 members of the month, average ranks, scaled to [-0.5, 0.5]; non-members placed within the members' distribution",
        "coverage_by_year_members": cov,
        "price_target_columns_by_year": pt_year,
        "first_year_price_targets_filled_for_half_of_members": first_pt_year,
        "earnings_rule": "a report counts only with a reported EPS and an effective date at or before t; at or after 16:00 ET it is effective the next trading day",
        "membership": "data/analyst/sp500_membership_history.parquet (Wikipedia revisions in force at each month-end)",
    }
    COVER.write_text(json.dumps(report, indent=1, default=str))
    log(f"panel {len(df)} rows, {df['ticker'].nunique()} tickers; first year with targets for half the members: {first_pt_year}")
    for y in sorted(cov):
        if y % 2 == 0 or y >= 2024:
            log(f"  {y}: " + ", ".join(f"{v[3:]} {cov[y][v]:.2f}" for v in VARS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
