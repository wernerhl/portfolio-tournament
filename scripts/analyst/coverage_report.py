#!/usr/bin/env python3
"""
coverage_report.py — members with prices by year, 2005 to 2026, and the member-months still without prices split by
cause (second follow-up order of 7 October 2026, G2 acceptance).

For every (month-end, member) of data/analyst/sp500_membership_history.parquet, mapped to its current symbol:
  with prices                 the provider's month-end bar exists for the current symbol
  ticker change not mapped    no bar under the symbol, but the SEC's company list knows the member's CIK under a
                              different ticker that has bars (a change the table does not carry) or the symbol
                              appears as `old` in the change table without a mapped current symbol with bars
  no bars at the provider     the current symbol (after mapping) has no bars at all — delisted, or never at the
                              provider

Output: data/analyst/membership_coverage.json (by year: members in the file, with prices, the two causes) and the
printed table.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_panel as bp   # noqa: E402

REPO = HERE.parent.parent
AN = REPO / "data" / "analyst"
OUT = AN / "membership_coverage.json"


def main() -> int:
    mem = pd.read_parquet(AN / "sp500_membership_history.parquet"); mem["month_end"] = pd.to_datetime(mem["month_end"])
    cur = mem["ticker_current"] if "ticker_current" in mem.columns else mem["ticker"]
    mp = bp.read_all("monthly_prices", bp.all_stamps()); mp["p"] = pd.to_datetime(mp["month_end"]).dt.to_period("M")
    have = set(zip(mp["p"], mp["ticker"])); has_any = set(mp["ticker"])
    changes = pd.read_csv(AN / "ticker_changes.csv") if (AN / "ticker_changes.csv").exists() else pd.DataFrame(columns=["old", "new", "current"])
    olds = set(changes["old"].astype(str).str.upper())
    sec_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    sec_cik = {}
    if sec_path and sec_path.exists():
        for v in json.load(open(sec_path)).values():
            sec_cik.setdefault(int(v["cik_str"]), []).append(str(v["ticker"]).upper().replace(".", "-"))
    rows = []
    for me, tk, tc, cik in zip(mem["month_end"], mem["ticker"], cur, mem["cik"] if "cik" in mem.columns else [None] * len(mem)):
        p = me.to_period("M")
        if (p, tc) in have:
            cls = "with prices"
        else:
            alt = [t for t in sec_cik.get(int(cik), []) if t != tc and t in has_any] if cik is not None and pd.notna(cik) else []
            cls = "ticker change not mapped" if (alt or (tk in olds and tc not in has_any and tk != tc)) else "no bars at the provider"
        rows.append((me.year, cls))
    df = pd.DataFrame(rows, columns=["year", "cls"])
    tab = df.groupby(["year", "cls"]).size().unstack(fill_value=0)
    for c in ("with prices", "ticker change not mapped", "no bars at the provider"):
        if c not in tab.columns:
            tab[c] = 0
    months = mem.groupby(mem["month_end"].dt.year)["month_end"].nunique()
    out = {}
    for y in tab.index:
        n = int(months.get(y, 1))
        tot = int(tab.loc[y].sum())
        out[int(y)] = {"member_months": tot, "members_per_month": round(tot / n, 1), "with_prices_per_month": round(int(tab.loc[y, "with prices"]) / n, 1),
                       "share_with_prices": round(int(tab.loc[y, "with prices"]) / tot, 3),
                       "ticker_change_not_mapped": int(tab.loc[y, "ticker change not mapped"]), "no_bars_at_the_provider": int(tab.loc[y, "no bars at the provider"])}
    # J1 (fourth follow-up, 8 Oct 2026): the average member with prices against RSP, the equal-weighted S&P 500 fund,
    # over the registered test's formation months - the measured size of the free data's survivorship tilt (RSP holds
    # every member, including the companies that later disappeared)
    tilt = None
    try:
        import walkforward_test as wf
        T, _ = wf.build_table(wf.latest_stamp(), shift_analyst=0, hold_delisted=True)
        M = T[T["fwd12"].notna() & (T["p"] >= pd.Period("2014-01", freq="M"))].groupby("p")["fwd12"].mean()
        etf = wf.etf_returns(12)
        rows = [(str(p), float(v), etf["RSP"].get(p), etf["SPY"].get(p)) for p, v in M.items() if etf["RSP"].get(p) is not None and etf["SPY"].get(p) is not None]
        if rows:
            R = pd.DataFrame(rows, columns=["p", "avg_member", "rsp", "spy"])
            mu, t, n = wf.newey_west_t((R["avg_member"] - R["rsp"]).values, 11)
            tilt = {"formation_months": f"{R['p'].min()} to {R['p'].max()}", "months": int(n),
                    "average_member_with_prices_12m_pct": round(float(R["avg_member"].mean()) * 100, 2), "RSP_12m_pct": round(float(R["rsp"].mean()) * 100, 2), "SPY_12m_pct": round(float(R["spy"].mean()) * 100, 2),
                    "gap_pts_per_year": round(mu * 100, 2), "t_nw": round(t, 2), "lags": 11,
                    "reading": "RSP holds every member, including the companies that later disappeared, and charges about 0.2% a year; the gap is the survivorship tilt of the free data (members with prices only)"}
    except Exception as e:  # noqa: BLE001
        tilt = {"error": f"could not compute ({type(e).__name__}: {str(e)[:80]})"}
    OUT.write_text(json.dumps({"cadence": "static", "as_of": datetime.now().strftime("%Y-%m-%d"), "order": "second follow-up of 7 Oct 2026, G2; J1 of the fourth follow-up (the RSP gap)",
                               "survivorship_tilt_vs_RSP": tilt,
                               "definitions": {"ticker change not mapped": "no bar under the mapped symbol while the SEC lists the member's CIK under another ticker that has bars, or the symbol is an `old` of the change table whose current symbol has no bars",
                                               "no bars at the provider": "the current symbol has no bars at all (delisted, or never at the provider)"},
                               "by_year": out}, indent=1))
    print(f"{'year':>6} {'members/mo':>10} {'with prices':>12} {'share':>6} {'unmapped':>9} {'no bars':>8}")
    for y, v in out.items():
        print(f"{y:>6} {v['members_per_month']:>10} {v['with_prices_per_month']:>12} {v['share_with_prices']:>6.2f} {v['ticker_change_not_mapped']:>9} {v['no_bars_at_the_provider']:>8}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
