#!/usr/bin/env python3
"""
twins_e_report.py — order of 8 October 2026, J7 (item 8): the registered comparison of the entry-state twins
1e–4e with their c twins, data/tournament/twins_e_comparison.json (fixed before any data).

From twins.json (the daily NAVs of the eight twins: twins[1c..4c] and entry_state_twins.twins[1e..4e]):
  series    per tier, the daily return of the e twin minus its c twin, after costs, on the pair's common
            sessions from the first common session (the base session; the first difference falls on the
            session after it); the pooled series is the average across the four tiers
  monthly   the pooled and per-tier differences annualised (mean × 252) with the Newey-West t (5 lags, the
            formula of scripts/analyst/walkforward_test.py), the largest drawdown of each twin, the pooled
            largest drawdown of the e twins and of the c twins (equal-weight index rebased at the base
            session); one row per month-end session from the first month
  power     after three months: the tracking volatility of the pooled difference and the smallest annual
            difference that reaches t = 2 at 12 and at 24 months (2 × σ_LR × √(252/n), n = 252 and 504)
  verdict   none before 12 months; at the session nearest 12 months after the start the rules HELP when the
            pooled difference is positive with t above 2 and the pooled e drawdown is no deeper than the
            pooled c drawdown, HURT when negative with t below −2, otherwise no difference is shown; the
            same rule once more, for the last time, at 24 months. Later sessions never change a verdict.

Writes data/tournament/twins_e_comparison_report.json and prints a readable summary. With no e data yet it
reports "no sessions yet". No automatic consequence for any tier or page: the result enters the owner's
diagnostic table. Descriptive record of a rule-driven paper tournament; nothing here is a recommendation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
from trading_calendar import is_trading_day  # noqa: E402

TDIR = REPO / "data" / "tournament"
LAGS = 5
ANN = 252
E_BLOCK = "entry_state_twins"
VERDICT_MONTHS = (12, 24)
POWER_MONTHS = 3
ET = ZoneInfo("America/New_York")


def log(m: str) -> None:
    print(f"[twins_e_report] {m}", flush=True)


# ── statistics ────────────────────────────────────────────────────────────────────────────
def newey_west(x, lags: int = LAGS) -> dict:
    """mean, Newey-West t (Bartlett weights 1 − k/(lags+1)), n, the long-run variance and the plain sample
    standard deviation of a daily series — the same formula as scripts/analyst/walkforward_test.newey_west_t."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    out = {"n": int(n), "mean": None, "t": None, "lrv": None, "sd": None}
    if n < 3:
        return out
    mu = float(x.mean())
    e = x - mu
    g0 = float(np.dot(e, e) / n)
    var = g0
    for k in range(1, min(lags, n - 1) + 1):
        gk = float(np.dot(e[k:], e[:-k]) / n)
        var += 2.0 * (1.0 - k / (lags + 1.0)) * gk
    se = math.sqrt(max(var, 1e-18) / n)
    out.update({"mean": mu, "t": mu / se, "lrv": max(var, 0.0), "sd": float(x.std(ddof=1))})
    return out


def max_drawdown(navs) -> float | None:
    """The deepest peak-to-trough decline (≤ 0) of a NAV path."""
    v = [float(x) for x in navs if x is not None]
    if not v:
        return None
    peak, dd = v[0], 0.0
    for x in v:
        peak = max(peak, x)
        dd = min(dd, x / peak - 1.0)
    return dd


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    last = (date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last))


def months_elapsed(start: date, latest: date) -> int:
    n = 0
    while add_months(start, n + 1) <= latest:
        n += 1
    return n


def nearest_session(target: date) -> date:
    """The NYSE session nearest the date: the smallest distance in calendar days, an equal distance taking
    the earlier session."""
    for k in range(0, 15):
        for cand in (target - timedelta(days=k), target + timedelta(days=k)):
            if is_trading_day(cand):
                return cand
    return target


# ── the series ────────────────────────────────────────────────────────────────────────────
def histories(twins_json: dict, as_of: str | None = None) -> tuple[dict, dict, dict]:
    """{twin_id: {session: nav}} for the c twins and the e twins (sessions ≤ as_of), plus the e block."""
    c = {}
    for tid, w in (twins_json.get("twins") or {}).items():
        c[tid] = {str(h["date"])[:10]: float(h["nav"]) for h in (w.get("history") or []) if h.get("nav") is not None}
    e_blk = twins_json.get(E_BLOCK) or {}
    e = {}
    for tid, w in (e_blk.get("twins") or {}).items():
        e[tid] = {str(h["date"])[:10]: float(h["nav"]) for h in (w.get("history") or []) if h.get("nav") is not None}
    if as_of:
        c = {t: {s: v for s, v in h.items() if s <= as_of} for t, h in c.items()}
        e = {t: {s: v for s, v in h.items() if s <= as_of} for t, h in e.items()}
    return c, e, e_blk


def pair_series(e_hist: dict, c_hist: dict) -> dict:
    """The pair's common sessions, both daily return series between consecutive common sessions, and their
    difference (e − c). The first common session is the base: it carries no return."""
    common = sorted(set(e_hist) & set(c_hist))
    rows = []
    for i in range(1, len(common)):
        s0, s1 = common[i - 1], common[i]
        re_, rc_ = e_hist[s1] / e_hist[s0] - 1.0, c_hist[s1] / c_hist[s0] - 1.0
        rows.append({"session": s1, "e": re_, "c": rc_, "diff": re_ - rc_})
    return {"base": common[0] if common else None, "common": common, "rows": rows}


def pooled_series(pairs: dict) -> list[dict]:
    """The pooled difference per session: the mean over the pairs with a difference on that session."""
    by = {}
    for tid, p in pairs.items():
        for r in p["rows"]:
            by.setdefault(r["session"], []).append(r["diff"])
    return [{"session": s, "diff": float(np.mean(v)), "n_pairs": len(v)} for s, v in sorted(by.items())]


def pooled_index(hists: dict, base: str, through: str) -> list[float]:
    """The equal-weight index of the twins' NAVs, each rebased to 1 at the base session, on the sessions
    from the base through `through` (the mean over the twins with a NAV on the session)."""
    sessions = sorted({s for h in hists.values() for s in h if base <= s <= through})
    out = []
    for s in sessions:
        vals = [h[s] / h[base] for h in hists.values() if s in h and base in h and h[base]]
        if vals:
            out.append(float(np.mean(vals)))
    return out


def r4(x, nd=4):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), nd)


def stats_through(pairs: dict, pooled: list[dict], c_hist: dict, e_hist: dict, base: str, through: str) -> dict:
    """Everything the monthly report states, on the sessions from the base session through `through`."""
    per_tier = {}
    for tid, p in sorted(pairs.items()):
        d = [r["diff"] for r in p["rows"] if r["session"] <= through]
        nw = newey_west(d)
        per_tier[tid] = {"c": p["c"], "n": nw["n"], "ann_diff_pct": r4(None if nw["mean"] is None else nw["mean"] * ANN * 100),
                         "t_nw5": r4(nw["t"], 3), "first_common_session": p["base"]}
    pd_ = [r["diff"] for r in pooled if r["session"] <= through]
    nw = newey_west(pd_)
    lr_sd_ann = None if nw["lrv"] is None else math.sqrt(nw["lrv"] * ANN)
    pooled_out = {"n": nw["n"], "ann_diff_pct": r4(None if nw["mean"] is None else nw["mean"] * ANN * 100), "t_nw5": r4(nw["t"], 3),
                  "tracking_vol_pct": r4(None if nw["sd"] is None else nw["sd"] * math.sqrt(ANN) * 100),
                  "lr_sd_ann_pct": r4(None if lr_sd_ann is None else lr_sd_ann * 100)}
    dd = {}
    for tid, h in sorted(list(e_hist.items()) + list(c_hist.items())):
        path = [h[s] for s in sorted(h) if base <= s <= through]
        dd[tid] = r4(max_drawdown(path))
    dd["pooled_e"] = r4(max_drawdown(pooled_index(e_hist, base, through)))
    dd["pooled_c"] = r4(max_drawdown(pooled_index(c_hist, base, through)))
    return {"through": through, "per_tier": per_tier, "pooled": pooled_out, "largest_drawdown": dd}


def verdict_of(st: dict) -> tuple[str, dict]:
    p, dd = st["pooled"], st["largest_drawdown"]
    basis = {"pooled_ann_diff_pct": p["ann_diff_pct"], "pooled_t_nw5": p["t_nw5"],
             "pooled_largest_drawdown_e": dd.get("pooled_e"), "pooled_largest_drawdown_c": dd.get("pooled_c")}
    if p["ann_diff_pct"] is None or p["t_nw5"] is None:
        return "no difference shown", {**basis, "note": "too few sessions for the statistic"}
    dd_ok = dd.get("pooled_e") is not None and dd.get("pooled_c") is not None and dd["pooled_e"] >= dd["pooled_c"] - 1e-12
    if p["ann_diff_pct"] > 0 and p["t_nw5"] > 2.0 and dd_ok:
        return "help", basis
    if p["ann_diff_pct"] < 0 and p["t_nw5"] < -2.0:
        return "hurt", basis
    return "no difference shown", basis


def month_ends(sessions: list[str]) -> list[str]:
    """The last session of each calendar month in the list."""
    out, by = [], {}
    for s in sessions:
        by[s[:7]] = s
    return [by[m] for m in sorted(by)]


# ── main ──────────────────────────────────────────────────────────────────────────────────
def build(twins_json: dict, registration: dict, as_of: str | None = None) -> dict:
    c_hist, e_hist, e_blk = histories(twins_json, as_of)
    pairs_reg = (registration.get("twins") or {}).get("pairs") or (e_blk.get("twin_of") or {})
    reg_first = ((registration.get("start") or {}).get("registered_first_session")) or e_blk.get("first_session")
    base_out = {
        "cadence": "daily", "session_date": twins_json.get("session_date"),
        "computed_at": datetime.now(ET).isoformat(timespec="seconds"),
        "order": registration.get("order"), "registration": "data/tournament/twins_e_comparison.json",
        "pairs_registered": pairs_reg, "registered_first_session": reg_first,
        "newey_west_lags": LAGS, "consequence": registration.get("consequence"),
        "label": registration.get("label"),
    }
    pairs = {}
    for e_id, c_id in pairs_reg.items():
        if e_id in e_hist and c_id in c_hist and len(set(e_hist[e_id]) & set(c_hist[c_id])) >= 1:
            pairs[e_id] = {"c": c_id, **pair_series(e_hist[e_id], c_hist[c_id])}
    if not pairs:
        return {**base_out, "status": "no sessions yet",
                "note": f"the e twins start on {reg_first}; twins.json carries no e-twin history yet"
                        + ("" if not e_blk else f" (entry_state_twins active: {e_blk.get('active')})"),
                "start": {"registered_first_session": reg_first, "start_date": None, "base_session": None},
                "window": {"from": None, "through": None, "sessions": 0, "months_elapsed": 0},
                "pairs": {}, "pooled": {"n": 0}, "largest_drawdown": {}, "power": {"reported": False, "available_from_months": POWER_MONTHS},
                "verdicts": {f"{m}m": {"status": "pending", "verdict": None, "months": m} for m in VERDICT_MONTHS}, "by_month": []}
    base = min(p["base"] for p in pairs.values())
    pooled = pooled_series(pairs)
    all_sessions = sorted({s for p in pairs.values() for s in p["common"]})
    latest = all_sessions[-1]
    start_d, latest_d = date.fromisoformat(base), date.fromisoformat(latest)
    m_el = months_elapsed(start_d, latest_d)
    now = stats_through(pairs, pooled, c_hist, e_hist, base, latest)
    power = {"reported": m_el >= POWER_MONTHS, "available_from_months": POWER_MONTHS, "months_elapsed": m_el}
    if m_el >= POWER_MONTHS and now["pooled"]["lr_sd_ann_pct"] is not None:
        lr = now["pooled"]["lr_sd_ann_pct"]
        power.update({"tracking_vol_pct": now["pooled"]["tracking_vol_pct"], "lr_sd_ann_pct": lr,
                      "min_annual_diff_for_t2_pct": {"12m": r4(2.0 * lr * math.sqrt(ANN / 252.0)), "24m": r4(2.0 * lr * math.sqrt(ANN / 504.0))},
                      "rule": "2 × σ_LR × √(252/n), n = 252 and 504 sessions; σ_LR the annualised Newey-West long-run standard deviation (5 lags) of the daily pooled difference"})
    verdicts = {}
    for m in VERDICT_MONTHS:
        target = add_months(start_d, m)
        vs = nearest_session(target)
        rec = {"months": m, "target_date": target.isoformat(), "verdict_session": vs.isoformat(), "status": "pending", "verdict": None}
        if latest_d >= vs:
            st = stats_through(pairs, pooled, c_hist, e_hist, base, vs.isoformat())
            v, basis = verdict_of(st)
            rec.update({"status": "applied", "verdict": v, "basis": basis, "through": st["through"],
                        "sessions_through": st["pooled"]["n"], "final": m == VERDICT_MONTHS[-1]})
        verdicts[f"{m}m"] = rec
    by_month = []
    for me in month_ends(all_sessions):
        st = stats_through(pairs, pooled, c_hist, e_hist, base, me)
        by_month.append({"month": me[:7], "session": me, "n": st["pooled"]["n"],
                         "pooled_ann_diff_pct": st["pooled"]["ann_diff_pct"], "pooled_t_nw5": st["pooled"]["t_nw5"],
                         "per_tier": {k: {"ann_diff_pct": v["ann_diff_pct"], "t_nw5": v["t_nw5"], "n": v["n"]} for k, v in st["per_tier"].items()},
                         "largest_drawdown": st["largest_drawdown"]})
    applied = [v for v in verdicts.values() if v["status"] == "applied"]
    status = ("running — no verdict before 12 months" if not applied
              else "; ".join(f"verdict at {v['months']} months: the entry rules {v['verdict']}" if v["verdict"] in ("help", "hurt")
                             else f"verdict at {v['months']} months: no difference shown" for v in applied))
    return {**base_out, "status": status,
            "start": {"registered_first_session": reg_first, "start_date": base, "base_session": base,
                      "note": None if base == reg_first else f"the e twins' first session {base} differs from the registered {reg_first}"},
            "window": {"from": base, "through": latest, "sessions": now["pooled"]["n"], "months_elapsed": m_el},
            "pairs": now["per_tier"], "pooled": now["pooled"], "largest_drawdown": now["largest_drawdown"],
            "power": power, "verdicts": verdicts, "by_month": by_month}


def summary(rep: dict) -> str:
    lines = [f"status: {rep['status']}"]
    if rep.get("window", {}).get("sessions"):
        w, p = rep["window"], rep["pooled"]
        lines.append(f"window {w['from']} → {w['through']}: {w['sessions']} daily differences, {w['months_elapsed']} months elapsed")
        lines.append(f"pooled e − c: {p['ann_diff_pct']:+.2f}% a year, Newey-West t (5 lags) {p['t_nw5']:+.2f}, tracking vol {p['tracking_vol_pct']:.2f}%"
                     if p.get("ann_diff_pct") is not None else "pooled e − c: too few sessions for the statistic")
        for tid, v in rep["pairs"].items():
            lines.append(f"  {tid} − {v['c']}: {v['ann_diff_pct']:+.2f}% a year, t {v['t_nw5']:+.2f} (n {v['n']})"
                         if v.get("ann_diff_pct") is not None else f"  {tid} − {v['c']}: n {v['n']}")
        dd = rep["largest_drawdown"]
        lines.append("largest drawdown: " + ", ".join(f"{k} {v*100:.1f}%" for k, v in dd.items() if v is not None))
        pw = rep["power"]
        if pw.get("reported"):
            md = pw["min_annual_diff_for_t2_pct"]
            lines.append(f"power (after {pw['available_from_months']} months): tracking vol {pw['tracking_vol_pct']:.2f}%; the smallest annual difference "
                         f"reaching t 2 is {md['12m']:.2f}% at 12 months and {md['24m']:.2f}% at 24 months")
        else:
            lines.append(f"power statement: reported after {pw['available_from_months']} months ({pw.get('months_elapsed', 0)} elapsed)")
        for k, v in rep["verdicts"].items():
            lines.append(f"verdict {k}: {v['status']} (session {v['verdict_session']})" + (f" → {v['verdict']}" if v["verdict"] else ""))
    else:
        lines.append(rep.get("note") or "")
    lines.append(f"consequence: {rep.get('consequence')}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--twins", default=str(TDIR / "twins.json"))
    ap.add_argument("--registration", default=str(TDIR / "twins_e_comparison.json"))
    ap.add_argument("--out", default=str(TDIR / "twins_e_comparison_report.json"))
    ap.add_argument("--as-of", default=None, help="use the sessions up to this date only (YYYY-MM-DD)")
    ap.add_argument("--no-write", action="store_true", help="print the summary only")
    args = ap.parse_args(argv)
    tp, rp = Path(args.twins), Path(args.registration)
    if not rp.exists():
        raise SystemExit(f"registration_missing: {rp}")
    registration = json.load(open(rp))
    twins_json = json.load(open(tp)) if tp.exists() else {}
    rep = build(twins_json, registration, args.as_of)
    rep["registration_sha256"] = hashlib.sha256(rp.read_bytes()).hexdigest()
    rep["twins_file"] = str(tp.relative_to(REPO)) if str(tp).startswith(str(REPO)) else str(tp)
    print(summary(rep))
    if not args.no_write:
        op = Path(args.out)
        op.parent.mkdir(parents=True, exist_ok=True)
        with open(op, "w") as f:
            json.dump(rep, f, indent=1, allow_nan=False, default=str)
        log(f"wrote {op}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
