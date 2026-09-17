#!/usr/bin/env python3
"""compute_book.py — nightly book analytics (order 16-Sept-2026, items 1.3, 1.5, 1.6).

Reads data/holdings.json (the only holdings source) and the price store; writes
data/book.json. Every figure is descriptive. Nothing here recommends a trade.

1.3  Per position: market value; share of NAV and of equities; annualised
     volatility (126 sessions); beta to SPY and to SMH (126-session OLS); risk
     contribution share (marginal contribution to variance, cash at zero
     volatility, shares summing to 100 percent); return versus cost basis;
     drawdown from the one-year peak; distance from the 200-day average; RSI-14.
     Portfolio: volatility with cash and for the equity sleeve; beta with cash
     and for the equity sleeve; effective number of theses (registry); effective
     number of bets (exponential entropy of the equity correlation eigenvalues).
1.5  Stress: SMH −30%, SPY −20%, SPY −34% ("2020-scale") through each holding's
     126-session beta to the shocked index; AI-infrastructure basket −30%,
     memory −40%, BMNR to zero from registry exposures. Dollars and share of NAV.
1.6  Diversification sleeves: XLP, XLE, XLF, XLU, TLT, GLD, IWM and the screen
     view's quality-passing names grouped by thesis, each with its 126-session
     correlation to the equity book, ascending.

A held name absent from every price source is displayed with "no price
history" and excluded from the analytics, with the exclusion stated (§7).

Usage:  python scripts/compute_book.py [--print] [--allow-non-trading]
"""
from __future__ import annotations
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from book_analytics import (ANN, DATA, MIN_OBS, REPO, WINDOW, ann_vol, book_series, corr,  # noqa: E402
                            daily_returns, effective_bets, fetch_live_prices, load_etfs, load_holdings,
                            load_prices, member_sub, member_weight, n_eff, ols_beta, risk_contributions,
                            rsi14, thesis_exposure, window_returns)
from trading_calendar import last_completed_session, now_et, require_trading_day  # noqa: E402

OUT = DATA / "book.json"
VOL_WINDOW_RULE = 60          # the registered vol-targeting window (c3_registration §B6)

STRESS_INDEX = [
    {"id": "smh_-30", "label": "Semiconductors (SMH) −30%", "index": "SMH", "shock": -0.30},
    {"id": "spy_-20", "label": "Market (SPY) −20%", "index": "SPY", "shock": -0.20},
    {"id": "spy_-34", "label": "Market (SPY) −34%, 2020-scale", "index": "SPY", "shock": -0.34},
]
SLEEVE_ETFS = [("XLP", "Consumer staples"), ("XLE", "Energy"), ("XLF", "Financials"), ("XLU", "Utilities"),
               ("TLT", "Long Treasuries"), ("GLD", "Gold"), ("IWM", "Small caps")]
# Phase 5: sleeves grouped by thesis — each group's ETFs and the registry theses whose
# quality-passing screen names belong in it. Treasuries and gold have no equity thesis.
SLEEVE_GROUPS = [
    ("staples_defensives", "Staples and defensives",  ["XLP", "XLU"], ["defensive_quality"]),
    ("energy_hard_assets", "Energy and hard assets",  ["XLE", "GLD"], ["hard_assets"]),
    ("financial_plumbing", "Financial plumbing",      ["XLF"],        ["fin_plumbing"]),
    ("treasuries_gold",    "Treasuries and gold",     ["TLT", "GLD"], []),
]
SLEEVES_HEADING = "exposures the book lacks, at the level where the system has evidence"
QUALITY_BAR = {"fundamental": 18.0, "visibility": 15.0}   # the screen view's quality bar (build_json drawdown shelf)
SLEEVE_NOTE = ("name selection has no measured skill; this panel describes exposure the book lacks, "
               "at the level where the system has evidence")
BETS_NOTE = ("calm-period correlations understate co-movement in declines; the thesis figure is the one "
             "used for sizing")


def log(msg: str) -> None:
    print(f"[compute_book] {msg}", flush=True)


def r4(x, nd=4):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(f) else round(f, nd)


def screen_universe() -> tuple[pd.DataFrame | None, str | None]:
    """The screen view's scored universe: post-merge path, dev sibling, then the
    published file. None if unreachable (the sleeves then carry ETFs only)."""
    cands = [("data/screen/scored_universe.csv", REPO / "data" / "screen" / "scored_universe.csv"),
             ("sibling", Path("/Users/whl/portfolio-screener/data/scored_universe.csv"))]
    for label, p in cands:
        if p.exists():
            try:
                return pd.read_csv(p), f"{label}:{p}"
            except Exception:
                continue
    url = "https://raw.githubusercontent.com/wernerhl/portfolio-screener/main/data/scored_universe.csv"
    try:
        return pd.read_csv(url), url
    except Exception as e:
        log(f"screen universe unavailable ({type(e).__name__}); sleeves carry ETFs only")
        return None, None


def build(session: str, live: dict | None = None, intraday: bool = False) -> dict:
    hold = load_holdings()
    prices = load_prices()
    etfs = load_etfs()
    live = live or {}
    live_used: list[str] = []
    registry = json.load(open(DATA / "thesis_registry.json"))
    through = min(prices.index[-1], etfs.index[-1])
    warnings: list[str] = []
    if str(through.date()) != session:
        warnings.append(f"price store ends {through.date()}, before the last completed session {session}; "
                        f"analytics computed through {through.date()}")

    # ── positions ────────────────────────────────────────────────────────
    cash = float(hold.get("cash") or 0.0)
    positions, unpriced = [], []
    for h in hold["holdings"]:
        tk = str(h["ticker"]).upper(); sh = float(h.get("shares") or 0)
        cost = float(h.get("cost_basis") or 0)
        if sh <= 0:
            continue
        if tk not in prices.columns or prices[tk].dropna().empty:
            unpriced.append(tk)
            positions.append({"ticker": tk, "shares": sh, "cost_basis": cost, "price": None, "value": None,
                              "status": "no price history", "excluded_from_analytics": True})
            continue
        s = prices[tk].dropna()
        s = s.loc[:through]
        px = float(s.iloc[-1])
        priced_at = str(s.index[-1].date())
        price_source = "close"
        # Intraday overlay: the CURRENT price (hence market value, share of NAV, stress
        # dollars, return-vs-cost) is the live tape; every return window below stays on the
        # settled daily closes. The settled store is not modified.
        if intraday and tk in live and live[tk]:
            px = float(live[tk]); price_source = "intraday"; live_used.append(tk)
        positions.append({"ticker": tk, "shares": sh, "cost_basis": cost, "price": px, "value": sh * px,
                          "priced_at": priced_at, "price_source": price_source, "history_sessions": int(len(s)),
                          "status": "ok", "excluded_from_analytics": False})
    priced = [p for p in positions if p["value"] is not None]
    equity = float(sum(p["value"] for p in priced))
    nav = equity + cash
    if nav <= 0:
        raise SystemExit("[compute_book] NAV is zero")
    for p in priced:
        p["share_nav"] = p["value"] / nav
        p["share_equity"] = p["value"] / equity if equity > 0 else None
        p["return_vs_cost"] = (p["price"] / p["cost_basis"] - 1.0) if p["cost_basis"] > 0 else None
        p["unrealized"] = (p["price"] - p["cost_basis"]) * p["shares"] if p["cost_basis"] > 0 else None

    # ── returns, betas, vols, technicals ─────────────────────────────────
    all_px = prices.join(etfs[[c for c in ("SPY", "SMH") if c in etfs.columns and c not in prices.columns]], how="outer")
    rets = daily_returns(all_px)
    names = [p["ticker"] for p in priced]
    win = window_returns(rets, names + ["SPY", "SMH"], through)
    win_start, win_end = str(win.index[0].date()), str(win.index[-1].date())
    for p in priced:
        tk = p["ticker"]; r = win[tk] if tk in win.columns else pd.Series(dtype=float)
        p["vol_ann"] = ann_vol(r)
        p["beta_spy"] = ols_beta(r, win["SPY"])
        p["beta_smh"] = ols_beta(r, win["SMH"])
        s = prices[tk].dropna().loc[:through]
        peak = float(s.iloc[-252:].max())
        p["drawdown_1y"] = float(p["price"] / peak - 1.0) if peak > 0 else None
        p["peak_1y_date"] = str(s.iloc[-252:].idxmax().date())
        ma200 = float(s.iloc[-200:].mean()) if len(s) >= 200 else None
        p["ma200"] = ma200
        p["ma200_dist"] = (p["price"] / ma200 - 1.0) if ma200 else None
        p["rsi14"] = rsi14(s)
        p["insufficient_history"] = bool(len(s) < 120)
        if p["insufficient_history"]:
            p["status"] = "no signal (insufficient history)"

    w_nav = {p["ticker"]: p["share_nav"] for p in priced}
    w_eq = {p["ticker"]: p["share_equity"] for p in priced}
    rc = risk_contributions(win, w_nav)
    for p in priced:
        p["risk_share"] = rc["shares"].get(p["ticker"])
    bets = effective_bets(win, names)

    # equity-sleeve series (constant current weights) and the portfolio figures
    eq_series = book_series(rets, w_eq).loc[:through]
    eq_win = eq_series.iloc[-WINDOW:]
    vol_eq = ann_vol(eq_win)
    vol_eq_60 = ann_vol(eq_series.iloc[-VOL_WINDOW_RULE:], min_obs=int(0.8 * VOL_WINDOW_RULE))
    inv_share = equity / nav
    vol_nav = vol_eq * inv_share if vol_eq is not None else None
    beta_eq_spy_reg = ols_beta(eq_win, win["SPY"]); beta_eq_smh_reg = ols_beta(eq_win, win["SMH"])
    # Portfolio beta = weight-averaged position betas (Σ w β): with cash over NAV
    # (cash at beta zero), for the sleeve over equity. The regression of the
    # constant-weight sleeve series is reported beside it as a cross-check.
    def wavg_beta(key):
        num = sum(w_eq[p["ticker"]] * p[key]["beta"] for p in priced if p[key]["beta"] is not None)
        cov = sum(w_eq[p["ticker"]] for p in priced if p[key]["beta"] is not None)
        return (num / cov) if cov > 0 else None
    beta_eq_spy_w, beta_eq_smh_w = wavg_beta("beta_spy"), wavg_beta("beta_smh")
    beta_nav_spy = beta_eq_spy_w * inv_share if beta_eq_spy_w is not None else None
    beta_nav_smh = beta_eq_smh_w * inv_share if beta_eq_smh_w is not None else None

    # effective theses from the registry
    values = {p["ticker"]: p["value"] for p in priced}
    exposure, nw = thesis_exposure(values, registry)
    eff_theses = n_eff(exposure)

    # ── stress (1.5) ─────────────────────────────────────────────────────
    stress = []
    for sc in STRESS_INDEX:
        key = "beta_smh" if sc["index"] == "SMH" else "beta_spy"
        rows, loss, covered = [], 0.0, 0.0
        for p in priced:
            b = p[key]["beta"]
            if b is None:
                rows.append({"ticker": p["ticker"], "beta": None, "loss": None, "excluded": "no beta"}); continue
            l = p["value"] * b * sc["shock"]
            loss += l; covered += p["value"]
            rows.append({"ticker": p["ticker"], "beta": r4(b), "loss": round(l, 2)})
        stress.append({**sc, "method": f"Σ value_i × β_i({sc['index']}, {WINDOW}-session OLS) × shock; cash unchanged",
                       "loss": round(loss, 2), "share_nav": r4(loss / nav), "share_equity": r4(loss / equity) if equity else None,
                       "covered_equity_share": r4(covered / equity) if equity else None, "positions": rows})
    ai = registry["theses"].get("ai_infra", {}).get("members", {})
    memory_members = [m for m, v in ai.items() if member_sub(v) == "memory"]
    memory_source = "registry sub-thesis 'memory' (ai_infra members with sub: memory)"
    if not memory_members:
        memory_members = ["MU", "SNDK"]
        memory_source = "registry v3 queue: memory_semis proposal (MU, SNDK) — no sub-thesis field yet"
    def basket_loss(label, id_, shock, weight_of, method):
        rows, loss = [], 0.0
        for p in priced:
            w = weight_of(p["ticker"])
            if w <= 0:
                continue
            l = p["value"] * w * shock; loss += l
            rows.append({"ticker": p["ticker"], "exposure_weight": r4(w), "loss": round(l, 2)})
        return {"id": id_, "label": label, "shock": shock, "method": method, "loss": round(loss, 2),
                "share_nav": r4(loss / nav), "share_equity": r4(loss / equity) if equity else None, "positions": rows}
    stress.append(basket_loss("AI infrastructure basket −30%", "ai_infra_-30", -0.30,
                              lambda tk: nw.get(tk, {}).get("ai_infra", 0.0),
                              "Σ value_i × registry membership weight in ai_infra × −30%"))
    stress.append(basket_loss("Memory −40%", "memory_-40", -0.40,
                              lambda tk: 1.0 if tk in memory_members else 0.0,
                              f"Σ value_i × −40% over {memory_members} ({memory_source})"))
    stress.append(basket_loss("BMNR to zero", "bmnr_0", -1.0, lambda tk: 1.0 if tk == "BMNR" else 0.0,
                              "the BMNR position's full market value"))

    # ── sleeves (1.6) ─────────────────────────────────────────────────────
    sleeves = []
    etf_rets = daily_returns(etfs).loc[:through]
    for tk, label in SLEEVE_ETFS:
        if tk not in etf_rets.columns:
            sleeves.append({"ticker": tk, "label": label, "kind": "etf", "corr": None, "n_obs": 0, "note": "not in the price store"}); continue
        c = corr(eq_win, etf_rets[tk].iloc[-WINDOW:])
        sleeves.append({"ticker": tk, "label": label, "kind": "etf", "group": None, "corr": r4(c["corr"]), "n_obs": c["n_obs"]})
    screen, screen_src = screen_universe()
    quality_names = []
    if screen is not None and {"ticker", "fundamental", "visibility"} <= set(screen.columns):
        q = screen[(pd.to_numeric(screen["fundamental"], errors="coerce") >= QUALITY_BAR["fundamental"]) &
                   (pd.to_numeric(screen["visibility"], errors="coerce") >= QUALITY_BAR["visibility"])]
        held = set(names)
        for _, row in q.iterrows():
            tk = str(row["ticker"]).upper()
            if tk in held or tk not in rets.columns:
                continue
            theses = nw.get(tk)
            if not theses:
                continue                                   # no registry thesis → no group to describe
            tid = max(theses.items(), key=lambda kv: kv[1])[0]
            c = corr(eq_win, rets[tk].loc[:through].iloc[-WINDOW:])
            quality_names.append({"ticker": tk, "label": registry["theses"][tid]["label"], "kind": "screen_name",
                                  "group": tid, "corr": r4(c["corr"]), "n_obs": c["n_obs"],
                                  "screen_composite": r4(row.get("composite"), 1),
                                  "fundamental": r4(row.get("fundamental"), 1), "visibility": r4(row.get("visibility"), 1)})
    sleeves = sorted(sleeves + quality_names, key=lambda s: (s["corr"] is None, s["corr"] if s["corr"] is not None else 9))
    # Phase 5: the same sleeves grouped by thesis, each group's ETFs and its quality-passing screen names
    etf_by = {s_["ticker"]: s_ for s_ in sleeves if s_["kind"] == "etf"}
    groups = []
    for gid, glabel, etfs, theses in SLEEVE_GROUPS:
        gnames = sorted([q for q in quality_names if q["group"] in theses],
                        key=lambda q: (q["corr"] is None, q["corr"] if q["corr"] is not None else 9))
        groups.append({"id": gid, "label": glabel, "theses": theses,
                       "etfs": [etf_by[t] for t in etfs if t in etf_by],
                       "names": gnames, "n_quality_names": len(gnames)})

    if intraday:
        warnings.append("intraday snapshot: position values, NAV and stress are at the live tape; "
                        "volatility, beta, risk shares and correlations are the last settled close's "
                        f"126-session windows (through {through.date()})")
    payload = {
        "cadence": "intraday" if intraday else "daily",
        "mode": "intraday" if intraday else "close",
        "intraday": bool(intraday),
        "intraday_as_of": now_et().isoformat(timespec="seconds") if intraday else None,
        "intraday_priced": sorted(live_used) if intraday else [],
        "session_date": session, "as_of": str(through.date()),
        "computed_at": now_et().isoformat(timespec="seconds"),
        "source": {"holdings": "data/holdings.json", "holdings_as_of": hold.get("as_of"), "holdings_source": hold.get("source"),
                   "prices": "data/source/prices_daily.parquet", "indices": "data/source/sector_etfs.parquet (SPY, SMH, sector ETFs); TLT from vol_indicators.parquet",
                   "registry": f"data/thesis_registry.json v{registry.get('version')}", "screen_universe": screen_src},
        "definitions": {"window_sessions": WINDOW, "min_obs": MIN_OBS, "beta": "OLS slope with intercept, daily simple returns",
                        "volatility": "sample std (ddof=1) of daily simple returns × √252",
                        "risk_share": "w_i (Σw)_i / wᵀΣw, w over NAV, cash at zero volatility; sums to 100% over equities",
                        "effective_bets": "exp(−Σ p_i ln p_i) over normalised eigenvalues of the equity correlation matrix",
                        "effective_theses": "1/Σw² over the registry exposure vector of the invested sleeve (unclassified remainder counted)",
                        "book_series": "constant current equity weights applied to daily returns"},
        "window": {"start": win_start, "end": win_end, "n_sessions": int(len(win))},
        "nav": round(nav, 2), "equity": round(equity, 2), "cash": round(cash, 2),
        "invested_share": r4(inv_share), "cash_share": r4(cash / nav),
        "positions": positions, "unpriced": unpriced,
        "portfolio": {
            "vol_ann_with_cash": r4(vol_nav), "vol_ann_equity": r4(vol_eq), "vol_ann_equity_60": r4(vol_eq_60),
            "beta_spy_with_cash": r4(beta_nav_spy), "beta_spy_equity": r4(beta_eq_spy_w),
            "beta_spy_equity_regression": r4(beta_eq_spy_reg["beta"]), "beta_spy_equity_regression_r2": r4(beta_eq_spy_reg["r2"]),
            "beta_smh_with_cash": r4(beta_nav_smh), "beta_smh_equity": r4(beta_eq_smh_w),
            "beta_smh_equity_regression": r4(beta_eq_smh_reg["beta"]),
            "beta_definition": "Σ w β over position betas; with cash: w over NAV (cash at beta 0); equity sleeve: w over equity; the constant-weight sleeve regression is the cross-check",
            "effective_theses": r4(eff_theses, 2), "thesis_exposure": {k: r4(v) for k, v in sorted(exposure.items(), key=lambda kv: -kv[1])},
            "effective_bets": r4(bets["value"], 2), "effective_bets_eigenvalues": [r4(x) for x in (bets["eigenvalues"] or [])],
            "effective_bets_note": BETS_NOTE, "sizing_figure": "effective_theses",
            "risk_decomposition_n_obs": rc["n_obs"], "vol_from_covariance_with_cash": r4(rc["vol_nav_ann"]),
        },
        "stress": stress, "stress_note": "fixed scenarios; descriptive; betas from the same 126-session window",
        "sleeves": sleeves, "sleeves_note": SLEEVE_NOTE,
        "sleeve_groups": groups, "sleeves_heading": SLEEVES_HEADING,
        "quality_bar": QUALITY_BAR,
        "warnings": warnings,
        "note": "descriptive; no rule drives this book; nothing here is a recommendation",
    }
    return payload


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        f = float(o)
        return None if not math.isfinite(f) else round(f, 6)
    return o


def print_summary(b: dict) -> None:
    p = b["portfolio"]
    log(f"session {b['session_date']} · through {b['as_of']} · NAV ${b['nav']:,.0f} = equity ${b['equity']:,.0f} + cash ${b['cash']:,.0f} (invested {b['invested_share']*100:.1f}%)")
    log(f"{'name':6s} {'value':>10s} {'nav%':>6s} {'eq%':>6s} {'vol':>6s} {'βSPY':>6s} {'βSMH':>6s} {'risk%':>6s} {'vsCost':>7s} {'dd1y':>6s} {'ma200':>6s} {'rsi':>5s}")
    for q in b["positions"]:
        if q["value"] is None:
            log(f"{q['ticker']:6s} {'—':>10s}  {q['status']}"); continue
        f = lambda x, m=100: "   n/a" if x is None else f"{x*m:6.1f}"
        log(f"{q['ticker']:6s} {q['value']:10,.0f} {f(q['share_nav'])} {f(q['share_equity'])} {f(q['vol_ann'])} "
            f"{f(q['beta_spy']['beta'],1)} {f(q['beta_smh']['beta'],1)} {f(q['risk_share'])} {f(q['return_vs_cost']):>7s} {f(q['drawdown_1y'])} {f(q['ma200_dist'])} {q['rsi14']:5.1f}")
    pc = lambda x: "n/a" if x is None else f"{x*100:.1f}%"
    n2 = lambda x: "n/a" if x is None else f"{x:.2f}"
    log(f"portfolio: vol with cash {pc(p['vol_ann_with_cash'])} · equity sleeve {pc(p['vol_ann_equity'])} (60-session {pc(p['vol_ann_equity_60'])}) · "
        f"beta with cash {n2(p['beta_spy_with_cash'])} (Σ w_nav β) · equity sleeve {n2(p['beta_spy_equity'])} (Σ w_eq β; sleeve regression {n2(p['beta_spy_equity_regression'])}) · "
        f"effective theses {p['effective_theses']} · effective bets {p['effective_bets']}")
    for s in b["stress"]:
        log(f"stress {s['label']:34s} {s['loss']:12,.0f}  {s['share_nav']*100:6.1f}% of NAV")
    for s in b["sleeves"]:
        if s["kind"] == "etf":
            cs = "n/a" if s["corr"] is None else f"{s['corr']:+.3f}"   # 3.11-safe: no nested f-string
            log(f"sleeve {s['ticker']:5s} {s['label']:18s} corr {cs} (n {s['n_obs']})")
    qn = [s for s in b["sleeves"] if s["kind"] == "screen_name"]
    log(f"quality-passing screen names with a registry thesis: {len(qn)} (lowest: {[(s['ticker'], s['corr']) for s in qn[:5]]})")
    for w in b["warnings"]:
        log(f"WARNING: {w}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", dest="do_print", action="store_true")
    ap.add_argument("--allow-non-trading", action="store_true")
    ap.add_argument("--intraday", action="store_true",
                    help="recompute on the live tape (values, NAV, stress); the settled store and windows are untouched")
    args = ap.parse_args()
    require_trading_day("compute_book")
    session = last_completed_session()
    live: dict = {}
    if args.intraday:
        hold = load_holdings()
        held = [str(h["ticker"]).upper() for h in hold.get("holdings", []) if (h.get("shares") or 0) > 0]
        live = fetch_live_prices(held)
        log(f"intraday: fetched {len(live)}/{len(held)} live prices")
    payload = build(session, live=live, intraday=args.intraday)
    OUT.write_text(json.dumps(_clean(payload), indent=2) + "\n")
    log(f"wrote {OUT.relative_to(REPO)}{' (intraday)' if args.intraday else ''}")
    if args.do_print:
        print_summary(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
