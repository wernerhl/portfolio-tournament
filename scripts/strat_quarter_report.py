#!/usr/bin/env python3
"""
strat_quarter_report.py — item 7 of J6 (execution order of 8 October 2026): each quarter-end the report gives the
STRATIFIED paper tier's return since inception against QQQ, SPY and RSP. No verdict rule: the figures are reported,
not judged.

Reads data/tournament.json (the as-published rows; the tier's NAV and the inception-anchored SPY and QQQ benchmark
NAVs of the same rows) and the served price stores for RSP. RSP is not in the price store today
(data/source/prices_daily.parquet, data/source/sector_etfs.parquet); the report then says "RSP: not in the price
store" — nothing is fetched here. One block per quarter-end session since the tier's first session (the last row at
or before that session) and one block as of the last row. Runs nightly after compute_nav.py and runs cleanly before
any session exists (status "no session yet").

Output: data/tournament/strat_quarter_report.json
Usage:  python scripts/strat_quarter_report.py [--tournament PATH] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATA = REPO / "data"
sys.path.insert(0, str(HERE))
import strat_tier  # noqa: E402

OUT = DATA / "tournament" / "strat_quarter_report.json"
RSP_NOTE = "RSP: not in the price store (data/source/prices_daily.parquet, data/source/sector_etfs.parquet); not fetched here"


def log(m: str) -> None:
    print(f"[strat_quarter_report] {m}", flush=True)


def rsp_closes():
    """RSP's closes from the served stores when a store carries them; (None, note) otherwise. Never fetched."""
    try:
        import pandas as pd
    except ImportError:
        return None, RSP_NOTE
    for name, col in (("prices_daily.parquet", "RSP"), ("sector_etfs.parquet", "rsp")):
        p = DATA / "source" / name
        if not p.exists():
            continue
        try:
            df = pd.read_parquet(p)
            if col in df.columns:
                s = df[col].dropna(); s.index = pd.to_datetime(s.index)
                return s, f"data/source/{name} ({col})"
        except Exception:  # noqa: BLE001
            continue
    return None, RSP_NOTE


def pct(a, b):
    try:
        a = float(a); b = float(b)
    except (TypeError, ValueError):
        return None
    return round((a / b - 1.0) * 100.0, 2) if (a > 0 and b > 0) else None


def _rsp_return(rsp, d0: str, d1: str):
    s, _ = rsp
    if s is None or len(s) == 0:
        return None
    a = s[s.index <= d0]; b = s[s.index <= d1]
    if a.empty or b.empty or str(a.index[-1].date()) != d0 or str(b.index[-1].date()) != d1:
        return None
    return pct(float(b.iloc[-1]), float(a.iloc[-1]))


def block(first: dict, row: dict, tid: str, rsp, n_sessions: int, quarter_end_session: str | None = None) -> dict:
    t0, t1 = first["tiers"][tid], row["tiers"][tid]
    tier_ret = pct(t1.get("nav"), t0.get("nav"))
    out = {"quarter_end_session": quarter_end_session, "session": str(row["date"])[:10], "sessions": n_sessions,
           "tier": {"nav": t1.get("nav"), "return_pct": tier_ret, "n_positions": t1.get("n_positions"),
                    "holdings_month_end": t1.get("holdings_month_end")}}
    for key, store in (("QQQ", "qqq"), ("SPY", "spy")):
        b0 = ((first.get("benchmarks") or {}).get(store) or {}).get("nav"); b1 = ((row.get("benchmarks") or {}).get(store) or {}).get("nav")
        r = pct(b1, b0)
        out[key] = {"return_pct": r, "difference_pts": round(tier_ret - r, 2) if (r is not None and tier_ret is not None) else None,
                    "source": "tournament.json benchmarks (inception-anchored NAV of the same rows)"}
    r = _rsp_return(rsp, str(first["date"])[:10], str(row["date"])[:10])
    out["RSP"] = {"return_pct": r, "difference_pts": round(tier_ret - r, 2) if (r is not None and tier_ret is not None) else None,
                  "source": rsp[1] if rsp[0] is not None else None, "note": None if r is not None else (rsp[1] if rsp[0] is None else "no RSP close on both dates")}
    return out


def quarter_end_sessions(d0: str, d1: str, months) -> list[str]:
    """The last trading session of each quarter-end month between d0 and d1 (inclusive)."""
    out = []
    y, m = int(d0[:4]), int(d0[5:7])
    while f"{y:04d}-{m:02d}" <= d1[:7]:
        if m in months:
            qe = strat_tier.quarter_end_session_for(strat_tier.month_end_of(f"{y:04d}-{m:02d}-01"))
            if d0 <= qe <= d1:
                out.append(qe)
        m += 1
        if m > 12:
            m = 1; y += 1
    return out


def build_report(tournament: dict, spec: dict, rsp=(None, RSP_NOTE), computed_at: str | None = None) -> dict:
    tid = spec.get("id") or strat_tier.TIER_ID
    history = tournament.get("history") or []
    rows = [r for r in history if ((r.get("tiers") or {}).get(tid) or {}).get("nav")]
    payload = {
        "cadence": "daily",
        "session_date": str(history[-1]["date"])[:10] if history else (os.environ.get("PUBLISH_SESSION") or None),
        "computed_at": computed_at or datetime.now().isoformat(timespec="seconds"),
        "tier": tid, "name": spec.get("short") or "STRATIFIED",
        "label": spec.get("label") or strat_tier.LABEL,
        "weights": spec.get("weights") or strat_tier.WEIGHTS,
        "rule": "no verdict rule (order 8-Oct-2026, J6 item 7): at each quarter-end the tier's return since inception is given against QQQ, SPY and RSP; the figures are reported, not judged",
        "definitions": {"return_pct": "last NAV / first-session NAV - 1, as-published rows, net of the C1 cost on every trade",
                        "difference_pts": "the tier's return less the benchmark's over the same sessions, percentage points",
                        "QQQ_SPY": "the inception-anchored benchmark NAVs of the same tournament rows (price returns)",
                        "RSP": rsp[1]},
        "quarters": [], "latest": None,
    }
    if not rows:
        payload["status"] = "no session yet"
        payload["first_session_planned"] = spec.get("first_session")
        payload["seed_month_end"] = spec.get("seed_month_end")
        return payload
    first = rows[0]
    payload["status"] = "live"
    payload["first_session"] = str(first["date"])[:10]
    payload["inception"] = {"date": str(first["date"])[:10], "nav": first["tiers"][tid].get("nav"),
                            "holdings_file": first["tiers"][tid].get("holdings_file")}
    by_date = {str(r["date"])[:10]: r for r in rows}
    dates = sorted(by_date)
    for qe in quarter_end_sessions(dates[0], dates[-1], tuple(spec.get("rebalance_months") or (3, 6, 9, 12))):
        at = [d for d in dates if d <= qe]
        if not at:
            continue
        payload["quarters"].append(block(first, by_date[at[-1]], tid, rsp, len(at), quarter_end_session=qe))
    payload["latest"] = block(first, by_date[dates[-1]], tid, rsp, len(dates))
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description="the STRATIFIED paper tier's quarter-end report (no verdict rule)")
    ap.add_argument("--tournament", default=str(DATA / "tournament.json"))
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    tp = Path(a.tournament)
    tournament = json.load(open(tp)) if tp.exists() else {"history": []}
    cfg_p = REPO / "config.json"
    cfg = json.load(open(cfg_p)) if cfg_p.exists() else {}
    spec = strat_tier.load_spec(cfg) or dict(strat_tier.DEFAULT_SPEC)
    payload = build_report(tournament, spec, rsp_closes())
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, default=str))
    if payload["status"] == "no session yet":
        log(f"no session yet (first session planned {payload.get('first_session_planned')}); wrote {out}")
    else:
        lt = payload["latest"]
        log(f"since {payload['first_session']}: tier {lt['tier']['return_pct']:+.2f}% · vs QQQ {lt['QQQ']['difference_pts']} pts · vs SPY {lt['SPY']['difference_pts']} pts · "
            f"RSP {lt['RSP']['return_pct'] if lt['RSP']['return_pct'] is not None else 'not in the price store'} · {len(payload['quarters'])} quarter-end(s); wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
