#!/usr/bin/env python3
"""compute_comparators.py — nightly state of the C3 one-line rules beside the regime index.

Order item 2.2: "A nightly job writes data/comparators.json: today's state of each C3 rule
on the same index, using the registration's constants verbatim ..." The dashboard strip
that reads this file is descriptive — a second opinion beside the regime reading. No rule
drives sizing.

Definitions are the registered ones (reports/c3_registration.md §B6; reference
implementation scripts/c3_regime_vs_rules.py signals_at() / exposure_for()), restated here
without re-tuning:
  (i)   regime:  e = 1 − clamp(floor + R_full × slope, floor, max), tier-4 parameters
        (floor 0 / slope 1 / max 1, §B7) so e = 1 − R_full.
  (ii)  SMA10:   month-end closes = SPY close on the last session of each calendar month;
        P_m = most recent completed month-end close; SMA10 = mean of the last 10 month-end
        closes including P_m; invested (1.0) if P_m > SMA10 else cash (0.0). Monthly.
  (iii) TSMOM 12-1: invested if P_{m−1} / P_{m−12} − 1 > 0 else cash (month-end closes;
        the most recent month is skipped). Monthly.
  (iv)  vol targeting: σ = sample std (ddof=1) of the last 60 daily log returns × √252;
        e = min(1.0, 0.10 / σ).

Timing: the rules are computed through the last COMPLETED session (trading_calendar), the
same information set the registration gives a rebalance on the next session (t−1, §B5).
SMA10 / TSMOM are monthly rules: the state in force is the one set at the last completed
month-end; a clearly-labelled provisional reading treats the latest close as the month-end.
Vol targeting is reported daily (the registered contestant re-sets it at the monthly
rebalance; that monthly reading is reported beside it). A runtime cross-check evaluates
c3_regime_vs_rules.signals_at() at the current month's rebalance session and stops the job
if the two implementations disagree.

Usage:
  python scripts/compute_comparators.py [--print] [--allow-non-trading]
"""
from __future__ import annotations
import argparse, json, sys
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATA = REPO / "data"; SOURCE = DATA / "source"
OUT_PATH = DATA / "comparators.json"
sys.path.insert(0, str(HERE))
from trading_calendar import is_trading_day, last_completed_session, now_et, require_trading_day  # noqa: E402

# Registered constants (c3_registration.md §B6; identical to c3_regime_vs_rules.REG — asserted at run time).
SMA_MONTHS = 10
MOM_LOOKBACK_MONTHS = 12
MOM_SKIP_MONTHS = 1
VOL_TARGET = 0.10
VOL_WINDOW_DAYS = 60
VOL_CAP = 1.0
DECISION_TIER = "4_tactical"
REGISTERED_TIER4 = {"cash_floor": 0.0, "cash_slope": 1.0, "cash_max": 1.0}     # §B7
RULES = ("sma10", "tsmom_12_1", "vol_target_10")

INDEX_LABEL = "SPY (data/source/sector_etfs.parquet, dividend-adjusted)"
REGISTRATION = "reports/c3_registration.md §B6 (constants verbatim; no re-tuning)"
NOTE = "descriptive second opinion; no rule drives sizing"
RULE_LABELS = {
    "sma10": "Ten-month simple moving average on SPY month-end closes; monthly; invested above, cash below",
    "tsmom_12_1": "Time-series momentum: sign of trailing twelve-month return excluding the last month "
                  "(P_{m-1} / P_{m-12} - 1 on month-end closes); monthly; invested if positive, cash otherwise",
    "vol_target_10": "Volatility targeting at 10% annualized with 60-day realized volatility "
                     "(sample std of daily log returns x sqrt(252)); exposure = min(1.0, 0.10 / sigma), capped at 100%",
}


# ----------------------------------------------------------------------------- helpers
def r4(x):
    if x is None:
        return None
    x = float(x)
    return None if np.isnan(x) else round(x, 4)


def iso(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def next_trading_day(d: date) -> date:
    d = d + timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def first_trading_day_of_month(y: int, m: int) -> date:
    d = date(y, m, 1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def last_trading_day_of_month(y: int, m: int) -> date:
    d = date(y, m, monthrange(y, m)[1])
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def add_month(y: int, m: int) -> tuple[int, int]:
    return (y + m // 12, m % 12 + 1)


def month_is_complete(through: pd.Timestamp, spy_full: pd.Series) -> bool:
    """Is `through` the last session of its calendar month? Decided from the data when a
    later session exists (exact), otherwise from the trading calendar (the live case)."""
    later = spy_full.index[spy_full.index > through]
    nxt = later[0] if len(later) else pd.Timestamp(next_trading_day(through.date()))
    return (nxt.year, nxt.month) != (through.year, through.month)


def month_end_closes(hist: pd.Series):
    """Month-end closes of `hist` — the close on the last session of each calendar month
    (§B6 ii, the same `resample("ME").last()` as the C3 script) — and the session each came
    from. The last bin is the month of hist's last session, complete or partial."""
    vals = hist.resample("ME").last().dropna()
    dates = hist.index.to_series().resample("ME").last().dropna().reindex(vals.index)
    return vals, dates


# ----------------------------------------------------------------------------- the rules
def rule_states(hist: pd.Series, spy_full: pd.Series) -> dict:
    """The three rules on `hist` = SPY closes through its last session, inclusive. Mirrors
    c3_regime_vs_rules.signals_at() line by line, with `hist` in the role of the t−1 history
    and completed month-ends in the role of `month_end[month_end.index < rd]`."""
    through = hist.index[-1]
    complete = month_is_complete(through, spy_full)
    me_all, md_all = month_end_closes(hist)
    me = me_all if complete else me_all.iloc[:-1]            # completed month-ends only
    md = md_all if complete else md_all.iloc[:-1]
    out = {"through": through, "month_complete": complete}
    L, S = MOM_LOOKBACK_MONTHS, MOM_SKIP_MONTHS

    # (ii) SMA10: P_m > mean of the last 10 month-end closes including P_m
    if len(me) >= SMA_MONTHS:
        P_m, sma = float(me.iloc[-1]), float(me.iloc[-SMA_MONTHS:].mean())
        out["sma10"] = {"P_m": P_m, "sma10": sma, "exposure": 1.0 if P_m > sma else 0.0,
                        "month_end_date": md.iloc[-1], "month": me.index[-1].strftime("%Y-%m"),
                        "closes_used": [(md.iloc[i], float(me.iloc[i])) for i in range(-SMA_MONTHS, 0)]}
    # (iii) TSMOM 12-1: P_{m-1} / P_{m-12} - 1 > 0
    if len(me) >= L + 1:
        p1, p12 = float(me.iloc[-1 - S]), float(me.iloc[-1 - L]); ret = p1 / p12 - 1.0
        out["tsmom_12_1"] = {"P_m_1": p1, "P_m_12": p12, "ret_12_1": ret, "exposure": 1.0 if ret > 0 else 0.0,
                             "P_m_1_date": md.iloc[-1 - S], "P_m_12_date": md.iloc[-1 - L],
                             "month_end_date": md.iloc[-1], "month": me.index[-1].strftime("%Y-%m")}
    # (iv) vol targeting: 60 daily log returns through the last session
    lr = np.log(hist).diff().dropna().iloc[-VOL_WINDOW_DAYS:]
    if len(lr) >= VOL_WINDOW_DAYS:
        sig = float(lr.std(ddof=1) * np.sqrt(252))
        out["vol_target_10"] = {"sigma_ann": sig, "exposure": min(VOL_CAP, VOL_TARGET / sig) if sig > 0 else np.nan,
                                "window_start": lr.index[0], "through": lr.index[-1], "n_returns": int(len(lr))}
    # provisional: the latest close treated as this month's month-end (== current when the month is complete)
    prov = {}
    if len(me_all) >= SMA_MONTHS:
        P, sma = float(me_all.iloc[-1]), float(me_all.iloc[-SMA_MONTHS:].mean())
        prov["sma10"] = {"P": P, "sma10": sma, "exposure": 1.0 if P > sma else 0.0}
    if len(me_all) >= L + 1:
        p1, p12 = float(me_all.iloc[-1 - S]), float(me_all.iloc[-1 - L]); ret = p1 / p12 - 1.0
        prov["tsmom_12_1"] = {"P_m_1": p1, "P_m_12": p12, "ret_12_1": ret, "exposure": 1.0 if ret > 0 else 0.0,
                              "P_m_1_date": md_all.iloc[-1 - S], "P_m_12_date": md_all.iloc[-1 - L]}
    out["provisional"] = prov
    return out


def regime_state(session_ts: pd.Timestamp, tier4: dict, warnings: list) -> tuple[dict, pd.Series]:
    """(i) latest R_full at or before the session, tier-4 mapping as exposure_for() does it."""
    reg = pd.read_csv(DATA / "regime_v2_daily.csv", parse_dates=["date"]).set_index("date").sort_index()
    r = reg.loc[:session_ts].dropna(subset=["R_full"])
    if r.empty:
        raise SystemExit(f"[compute_comparators] no R_full at or before {iso(session_ts)} in data/regime_v2_daily.csv")
    row = r.iloc[-1]; r_date = r.index[-1]; R = float(row["R_full"])
    fl, sl, mx = tier4["cash_floor"], tier4["cash_slope"], tier4["cash_max"]
    cash = min(mx, fl + R * sl); cash = max(cash, fl)
    ind = json.load(open(DATA / "regime_indicators.json"))
    label = ind.get("regime"); label_date = ind.get("session_date") or ind.get("as_of")
    if label_date != iso(r_date):
        warnings.append(f"regime label date {label_date} (regime_indicators.json) != R_full date {iso(r_date)} (regime_v2_daily.csv)")
    if "regime" in row and isinstance(row["regime"], str) and row["regime"] != label:
        warnings.append(f"regime label '{label}' (regime_indicators.json) != '{row['regime']}' (regime_v2_daily.csv {iso(r_date)})")
    if r_date < session_ts:
        warnings.append(f"R_full ends {iso(r_date)}, before session {iso(session_ts)}")
    block = {
        "rule": "24-indicator regime index R_full (data/regime_v2_daily.csv), tier-4 mapping: cash = clamp(floor + R_full x slope, floor, max), exposure = 1 - cash",
        "state": label, "R_full": r4(R), "cash": r4(cash), "exposure": r4(1.0 - cash),
        "computed_from": {"R_full": r4(R), "R_full_date": iso(r_date), "label": label, "label_date": label_date,
                          "tier": DECISION_TIER, "tier4_mapping": {k: r4(v) for k, v in tier4.items()}},
        "as_of": iso(r_date), "evaluation": {"frequency": "daily"}, "session_date": iso(session_ts),
    }
    return block, reg["R_full"].astype(float)


def cross_check(spy: pd.Series, reg_series: pd.Series, rd: date, monthly: dict) -> dict:
    """Evaluate the registered implementation at the current month's rebalance session and
    compare with this script's reading through the prior session. Any disagreement stops the job."""
    try:
        import c3_regime_vs_rules as c3
    except Exception as e:                                   # pragma: no cover
        return {"status": "skipped", "reason": f"c3_regime_vs_rules import failed: {e}"}
    consts = {"sma_months": SMA_MONTHS, "mom_lookback_months": MOM_LOOKBACK_MONTHS, "mom_skip_months": MOM_SKIP_MONTHS,
              "vol_target": VOL_TARGET, "vol_window_days": VOL_WINDOW_DAYS, "vol_cap": VOL_CAP, "decision_tier": DECISION_TIER}
    bad = {k: (v, c3.REG.get(k)) for k, v in consts.items() if c3.REG.get(k) != v}
    if bad:
        raise SystemExit(f"[compute_comparators] constants differ from c3_regime_vs_rules.REG: {bad} — stop, re-register")
    rd_ts = pd.Timestamp(rd)
    if rd_ts not in spy.index:
        return {"status": "skipped", "reason": f"rebalance session {rd} not in index history (through {iso(spy.index[-1])})"}
    sig = c3.signals_at(rd_ts, spy, reg_series, spy.resample("ME").last().dropna())
    theirs = {k: float(sig[k]) for k in RULES}
    ours = {k: float(monthly[k]["exposure"]) if k in monthly else float("nan") for k in RULES}
    agree = all(np.isclose(theirs[k], ours[k], atol=1e-9, equal_nan=True) for k in RULES)
    res = {"status": "ok" if agree else "MISMATCH", "implementation": "scripts/c3_regime_vs_rules.py signals_at()",
           "rebalance_session": iso(rd_ts), "signals_through": iso(monthly["through"]),
           "c3_exposures": {k: r4(v) for k, v in theirs.items()}, "this_script": {k: r4(v) for k, v in ours.items()}}
    if not agree:
        raise SystemExit(f"[compute_comparators] cross-check MISMATCH vs c3_regime_vs_rules.signals_at({iso(rd_ts)}): {res}")
    return res


# ----------------------------------------------------------------------------- output
def build(session_date: str) -> dict:
    session_ts = pd.Timestamp(session_date)
    warnings: list[str] = []
    sect = pd.read_parquet(SOURCE / "sector_etfs.parquet"); sect.index = pd.to_datetime(sect.index)
    spy = sect["spy"].dropna().astype(float).sort_index()
    hist = spy.loc[:session_ts]
    if hist.empty:
        raise SystemExit(f"[compute_comparators] no SPY history at or before {session_date}")
    through = hist.index[-1]
    if through < session_ts:
        warnings.append(f"index history ends {iso(through)}, before session {session_date}; rule states computed through {iso(through)}")

    cfg = json.load(open(REPO / "config.json"))
    tier4 = {k: float(cfg["tier_specs"][DECISION_TIER][k]) for k in ("cash_floor", "cash_slope", "cash_max")}
    if tier4 != REGISTERED_TIER4:
        warnings.append(f"config.json {DECISION_TIER} mapping {tier4} != registered {REGISTERED_TIER4} (§B7); config value used")

    cur = rule_states(hist, spy)                              # through the last completed session
    rd = first_trading_day_of_month(session_ts.year, session_ts.month)   # this month's registered rebalance session
    hist_prev = spy.loc[spy.index < pd.Timestamp(rd)]         # its information set: sessions strictly before it
    monthly = rule_states(hist_prev, spy)
    regime, reg_series = regime_state(session_ts, tier4, warnings)
    check = cross_check(spy, reg_series, rd, monthly)
    for k in RULES:
        if k not in cur:
            raise SystemExit(f"[compute_comparators] insufficient history for {k} through {iso(through)}")

    def monthly_eval(entry: dict) -> dict:
        y, m = entry["month_end_date"].year, entry["month_end_date"].month
        ny, nm = add_month(y, m)
        nxt = last_trading_day_of_month(ny, nm)
        return {"frequency": "monthly", "evaluated_at": iso(entry["month_end_date"]),
                "next_evaluation": nxt.isoformat(), "next_rebalance": next_trading_day(nxt).isoformat(),
                "note": "state set at the last completed month-end close; the registered rebalance applies a new reading "
                        "at the first session of the following month (B4/B5)"}

    def prov_label(prov_key: str) -> str:
        if cur["month_complete"]:
            return f"month complete at {iso(through)}: the provisional reading equals the current state"
        return (f"PROVISIONAL - latest close {iso(through)} treated as the {through.strftime('%B %Y')} month-end; "
                f"not the rule's state until the month completes")

    s, t, v = cur["sma10"], cur["tsmom_12_1"], cur["vol_target_10"]
    ps, pt = cur["provisional"]["sma10"], cur["provisional"]["tsmom_12_1"]
    binary = lambda e: "invested" if e >= 1.0 else "cash"
    rules = {
        "sma10": {
            "rule": RULE_LABELS["sma10"], "state": binary(s["exposure"]), "exposure": r4(s["exposure"]),
            "computed_from": {"P_m": r4(s["P_m"]), "sma10": r4(s["sma10"]), "month_end_date": iso(s["month_end_date"]),
                              "month": s["month"], "n_month_ends": SMA_MONTHS,
                              "month_end_closes_used": [[iso(d), r4(c)] for d, c in s["closes_used"]]},
            "evaluation": monthly_eval(s),
            "provisional_if_evaluated_today": {"label": prov_label("sma10"), "P": r4(ps["P"]), "sma10": r4(ps["sma10"]),
                                               "state": binary(ps["exposure"]), "exposure": r4(ps["exposure"]),
                                               "through": iso(through), "same_as_current": bool(cur["month_complete"])},
            "session_date": session_date,
        },
        "tsmom_12_1": {
            "rule": RULE_LABELS["tsmom_12_1"], "state": binary(t["exposure"]), "exposure": r4(t["exposure"]),
            "computed_from": {"P_m_1": r4(t["P_m_1"]), "P_m_1_date": iso(t["P_m_1_date"]),
                              "P_m_12": r4(t["P_m_12"]), "P_m_12_date": iso(t["P_m_12_date"]),
                              "ret_12_1": r4(t["ret_12_1"]), "month_end_date": iso(t["month_end_date"]), "month": t["month"]},
            "evaluation": monthly_eval(t),
            "provisional_if_evaluated_today": {"label": prov_label("tsmom_12_1"),
                                               "note": "the 12-1 rule skips the latest month, so the next evaluation's reading "
                                                       "is already fixed by known month-end closes",
                                               "P_m_1": r4(pt["P_m_1"]), "P_m_1_date": iso(pt["P_m_1_date"]),
                                               "P_m_12": r4(pt["P_m_12"]), "P_m_12_date": iso(pt["P_m_12_date"]),
                                               "ret_12_1": r4(pt["ret_12_1"]), "state": binary(pt["exposure"]),
                                               "exposure": r4(pt["exposure"]), "same_as_current": bool(cur["month_complete"])},
            "session_date": session_date,
        },
        "vol_target_10": {
            "rule": RULE_LABELS["vol_target_10"], "state": "invested" if v["exposure"] >= VOL_CAP else "scaled",
            "exposure": r4(v["exposure"]),
            "computed_from": {"sigma_ann": r4(v["sigma_ann"]), "target": VOL_TARGET, "cap": VOL_CAP,
                              "window_days": VOL_WINDOW_DAYS, "n_returns": v["n_returns"],
                              "window_start": iso(v["window_start"]), "through": iso(v["through"])},
            "evaluation": {"frequency": "daily",
                           "note": "60-session window through the last completed session; the registered C3 contestant "
                                   "re-sets this exposure at the monthly rebalance - see monthly_as_registered"},
            "monthly_as_registered": ({"set_at": rd.isoformat(), "signals_through": iso(monthly["through"]),
                                       "sigma_ann": r4(monthly["vol_target_10"]["sigma_ann"]),
                                       "exposure": r4(monthly["vol_target_10"]["exposure"])}
                                      if "vol_target_10" in monthly else None),
            "session_date": session_date,
        },
    }
    et = now_et()
    return {
        "cadence": "daily", "session_date": session_date, "as_of": iso(through),
        "computed_at": et.isoformat(timespec="seconds"),
        "index": INDEX_LABEL, "index_through": iso(through), "index_last_close": r4(hist.iloc[-1]),
        "registration": REGISTRATION, "note": NOTE,
        "regime": regime, "rules": rules,
        "cross_check": check, "warnings": warnings,
    }


def print_summary(out: dict) -> None:
    rg, ru = out["regime"], out["rules"]
    print(f"[compute_comparators] session {out['session_date']} · SPY {out['index_last_close']:.2f} through {out['index_through']}")
    print(f"  regime         {rg['state']} R_full {rg['R_full']:.4f} → exposure {rg['exposure']:.4f} (tier-4 mapping, cash {rg['cash']:.4f}) as of {rg['as_of']}")
    s = ru["sma10"]; c = s["computed_from"]; p = s["provisional_if_evaluated_today"]
    print(f"  sma10          {s['state']} ({s['exposure']:.2f}): P_m {c['P_m']:.2f} {'>' if c['P_m'] > c['sma10'] else '<='} SMA10 {c['sma10']:.2f} "
          f"at {c['month_end_date']} month-end; next evaluation {s['evaluation']['next_evaluation']}; "
          f"provisional today {p['state']} ({p['P']:.2f} vs {p['sma10']:.2f})")
    t = ru["tsmom_12_1"]; c = t["computed_from"]; p = t["provisional_if_evaluated_today"]
    print(f"  tsmom_12_1     {t['state']} ({t['exposure']:.2f}): P_m-1 {c['P_m_1']:.2f} ({c['P_m_1_date']}) / P_m-12 {c['P_m_12']:.2f} ({c['P_m_12_date']}) "
          f"- 1 = {c['ret_12_1']:+.4f}; next evaluation {t['evaluation']['next_evaluation']} reads {p['state']} ({p['ret_12_1']:+.4f}, already fixed)")
    v = ru["vol_target_10"]; c = v["computed_from"]; m = v["monthly_as_registered"]
    mtxt = f"; monthly-registered exposure {m['exposure']:.4f} set {m['set_at']} (σ {m['sigma_ann']*100:.2f}%)" if m else ""
    print(f"  vol_target_10  {v['state']} ({v['exposure']:.4f}): σ60 {c['sigma_ann']*100:.2f}% ann. through {c['through']} → min(1, 0.10/σ){mtxt}")
    ck = out["cross_check"]
    print(f"  cross-check vs c3_regime_vs_rules.signals_at: {ck['status']}" + (f" at {ck['rebalance_session']}" if "rebalance_session" in ck else f" ({ck.get('reason')})"))
    for w in out["warnings"]:
        print(f"  WARNING: {w}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Nightly state of the C3 one-line rules beside the regime index (descriptive).")
    ap.add_argument("--print", dest="print_summary", action="store_true", help="print a one-line summary per rule")
    ap.add_argument("--allow-non-trading", action="store_true", help="bypass the trading-day gate (manual runs only)")
    args = ap.parse_args()
    require_trading_day("compute_comparators")
    session_date = last_completed_session()
    out = build(session_date)
    OUT_PATH.write_text(json.dumps(out, indent=2) + "\n")
    print(f"[compute_comparators] wrote {OUT_PATH.relative_to(REPO)} (session {session_date})")
    if args.print_summary:
        print_summary(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
