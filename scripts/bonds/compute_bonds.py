#!/usr/bin/env python3
"""compute_bonds.py — data/bonds/states.json (order phases 2, 3, 4).

The state reads (pre-registered, no forecast), the allocation questions (pre-registered
rules), and the book integration for the fixed-income module. Every rule that drives a
display is defined in config and frozen before it runs (data/bonds/state_config.json).

The module reads the level and slope of the curve, credit spreads versus their history,
and breakevens; it does not predict rates. States are descriptive; the rates-regime state
is gated DIAGNOSTIC and drives no sizing (Phase 6 validates it). No buy or sell instruction.

Reads the FRED store as-published: the point-in-time (ALFRED) parquet when it is current,
else the revised parquet with the vintage recorded (yields and OAS are essentially not
revised, so the two coincide; the point-in-time overlay refreshes on the vintage rebuild).
"""
from __future__ import annotations
import json, sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import bonds_common as bc
import book_analytics as ba

HISTORY_YEARS = 10


def log(m: str) -> None:
    print(m, flush=True)


# ── FRED store (as-published) ──────────────────────────────────────────────
def load_fred() -> tuple[pd.DataFrame, str, pd.Timestamp]:
    """Indicators frame, store label, through-date. Prefer the point-in-time store when it
    is within a week of the revised store; else use revised and say the overlay is pending."""
    rev = pd.read_parquet(bc.SOURCE / "fred_indicators.parquet"); rev.index = pd.to_datetime(rev.index)
    rev_last = rev.index.max()
    try:
        pit = pd.read_parquet(bc.SOURCE / "fred_indicators_pit.parquet"); pit.index = pd.to_datetime(pit.index)
        if (rev_last - pit.index.max()).days <= 7:
            return pit.sort_index(), "point-in-time (as-published, ALFRED)", pit.index.max()
    except Exception:
        pass
    return rev.sort_index(), "revised (as-published latest; point-in-time overlay rebuilds on the vintage workflow)", rev_last


def last_valid(s: pd.Series) -> tuple[float | None, pd.Timestamp | None]:
    s = s.dropna()
    if s.empty:
        return None, None
    return float(s.iloc[-1]), s.index[-1]


def pctile(series: pd.Series, value: float | None, through: pd.Timestamp, years: int = HISTORY_YEARS) -> float | None:
    """Percentile (0-100) of `value` within the trailing `years` of `series` up to `through`."""
    if value is None:
        return None
    w = series.loc[through - pd.DateOffset(years=years):through].dropna()
    if len(w) < 250:
        return None
    return round(float((w < value).mean()) * 100.0, 1)


def band_for(pct: float | None, bands: list[dict]) -> str | None:
    if pct is None:
        return None
    for b in bands:
        if b.get("min_pct", 0.0) <= pct < b.get("max_pct", 100.0 + 1e-9):
            return b["id"]
    return None


# ── 2.1 curve state ────────────────────────────────────────────────────────
def curve_state(cfg: dict, ind: pd.DataFrame, through: pd.Timestamp) -> dict:
    cc = cfg["curve"]
    have = lambda c: c in ind.columns and ind[c].dropna().size > 0
    # slope 2s10s (config series) and 3m10y for context; computed from the maturities
    slope = (ind["us10y"] - ind["us02y"]) if (have("us10y") and have("us02y")) else pd.Series(dtype=float)
    cur_slope, slope_date = last_valid(slope)
    slope_pct = pctile(slope, cur_slope, through)
    state = band_for(slope_pct, cc["bands"])

    slope_3m10y = (ind["us10y"] - ind["us03m"]) if (have("us10y") and have("us03m")) else pd.Series(dtype=float)
    cur_3m10y, _ = last_valid(slope_3m10y)

    maturities = []
    for m in cfg["maturities"]:
        lbl = cfg["maturity_labels"].get(m, m)
        if have(m):
            lvl, d = last_valid(ind[m])
            maturities.append({"maturity": lbl, "series": m, "level_pct": round(lvl, 2) if lvl is not None else None,
                               "pctile_10y": pctile(ind[m], lvl, through), "as_of": str(d.date()) if d is not None else None})
        else:
            maturities.append({"maturity": lbl, "series": m, "level_pct": None, "pctile_10y": None,
                               "as_of": None, "unavailable": "series not yet in the store (pending FRED fetch)"})
    return {
        "series": cc["series"], "label": cc["label"],
        "slope_2s10s_pct": round(cur_slope, 2) if cur_slope is not None else None,
        "slope_2s10s_bps": round(cur_slope * 100, 0) if cur_slope is not None else None,
        "slope_2s10s_pctile_10y": slope_pct,
        "slope_3m10y_pct": round(cur_3m10y, 2) if cur_3m10y is not None else None,
        "state": state,
        "as_of": str(slope_date.date()) if slope_date is not None else None,
        "maturities": maturities,
        "bands": cc["bands"],
        "footnote": ("States: inverted (2s10s below its 10th percentile over ten years), flat (10th–40th), "
                     "normal (40th–80th), steep (above 80th). Descriptive; no rate direction implied."),
    }


# ── 2.2 credit state ───────────────────────────────────────────────────────
def _oas_leg(ind: pd.DataFrame, col: str, bands: list[dict], through: pd.Timestamp) -> dict:
    if col not in ind.columns:
        return {"oas_pct": None, "oas_bps": None, "pctile_10y": None, "state": None,
                "unavailable": "OAS series not in the store"}
    lvl, d = last_valid(ind[col])                    # OAS series are in percent (0.80 = 80 bps)
    pct = pctile(ind[col], lvl, through)
    return {"oas_pct": round(lvl, 3) if lvl is not None else None,
            "oas_bps": round(lvl * 100, 0) if lvl is not None else None,
            "pctile_10y": pct, "state": band_for(pct, bands),
            "as_of": str(d.date()) if d is not None else None}


def credit_state(cfg: dict, ind: pd.DataFrame, through: pd.Timestamp) -> dict:
    cc = cfg["credit"]
    return {
        "method": cc["method"],   # references option-adjusted spreads; the referee enforces this
        "ig": _oas_leg(ind, "ig_oas", cc["bands"], through),
        "hy": _oas_leg(ind, "hy_oas", cc["bands"], through),
        "bands": cc["bands"],
        "duration_caveat": ("Computed from the option-adjusted spread series, which are "
                            "duration-controlled by construction — NOT an ETF price ratio. A raw "
                            "HYG-versus-LQD ratio is prohibited (duration-confounding, per the ledger)."),
        "footnote": ("States against ten-year OAS history: tight (<20th percentile), normal (20–60th), "
                     "wide (60–90th), stressed (>90th). Descriptive; no spread direction implied. "
                     "Tight spreads mean little compensation for default and illiquidity risk."),
    }


# ── 2.3 real-vs-nominal read ───────────────────────────────────────────────
def real_nominal(ind: pd.DataFrame, through: pd.Timestamp) -> dict:
    def leg(col):
        if col not in ind.columns:
            return None, None, None
        lvl, d = last_valid(ind[col])
        return (round(lvl, 3) if lvl is not None else None,
                pctile(ind[col], lvl, through),
                str(d.date()) if d is not None else None)
    be10, be10_pct, be10_d = leg("breakeven_10y")
    fwd, _, _ = leg("fwd_5y5y_infl")
    real10, _, real_d = leg("tips_real_10y")
    out = {
        "breakeven_10y_pct": be10, "breakeven_10y_pctile_10y": be10_pct,
        "priced_inflation": be10, "priced_inflation_note": "the 10-year breakeven is the market's priced average inflation over ten years",
        "fwd_5y5y_infl_pct": fwd,
        "real_10y_yield_pct": real10,
        "as_of": be10_d,
        "footnote": ("This read decides only whether TIPS or nominal Treasuries carry better at a given "
                     "maturity; it is not an inflation forecast."),
    }
    if fwd is None:
        out["fwd_5y5y_unavailable"] = "T5YIFR not yet in the store (pending FRED fetch)"
    if real10 is None:
        out["real_10y_unavailable"] = "DFII10 not yet in the store (pending FRED fetch)"
    return out


# ── 3.1 are you paid to take duration ──────────────────────────────────────
def load_sleeve_metrics() -> dict:
    p = bc.BONDS / "sleeve_metrics.json"
    if not p.exists():
        return {}
    j = json.loads(p.read_text())
    return {r["ticker"]: r for r in j.get("sleeves", [])}


def q_duration(sm: dict, ind: pd.DataFrame, through: pd.Timestamp) -> dict:
    """Compare the yield pickup of extending from cash to intermediate and long duration
    against the additional rate risk. Descriptive; not a rate call."""
    def leg(tk):
        r = sm.get(tk, {})
        return {"ticker": tk, "yield_pct": r.get("distribution_yield_pct"),
                "duration": r.get("effective_duration"), "yield_per_duration": r.get("yield_per_duration")}
    cash, inter, long = leg("SHV"), leg("IEF"), leg("TLT")
    def pickup(a, b):
        if a["yield_pct"] is None or b["yield_pct"] is None or a["duration"] is None or b["duration"] is None:
            return None, None
        dd = b["duration"] - a["duration"]
        return round(b["yield_pct"] - a["yield_pct"], 2), (round((b["yield_pct"] - a["yield_pct"]) / dd, 3) if dd else None)
    up_i, per_i = pickup(cash, inter)
    up_l, per_l = pickup(cash, long)
    # term premium proxy: long-minus-cash yield spread (10y − 3m), and its 10y percentile
    tp = (ind["us10y"] - ind["us03m"]) if ("us10y" in ind and "us03m" in ind) else pd.Series(dtype=float)
    tp_cur, _ = last_valid(tp)
    tp_pct = pctile(tp, tp_cur, through)
    # which sleeve has the highest yield per unit of duration among the Treasury ladder
    ladder = ["SHV", "SHY", "IEF", "TLT", "GOVT"]
    ypd = {tk: sm.get(tk, {}).get("yield_per_duration") for tk in ladder if sm.get(tk, {}).get("yield_per_duration") is not None}
    best = max(ypd, key=ypd.get) if ypd else None
    favorable = None
    if best is not None:
        favorable = best not in ("SHV",)   # if cash has the highest carry per duration, extension is not favoured
    return {
        "question": "Are you paid to take duration?",
        "cash": cash, "intermediate": inter, "long": long,
        "pickup_cash_to_intermediate_pct": up_i, "pickup_per_year_duration_intermediate": per_i,
        "pickup_cash_to_long_pct": up_l, "pickup_per_year_duration_long": per_l,
        "term_premium_proxy": {"definition": "long-minus-cash yield spread (10y minus 3m)",
                               "value_pct": round(tp_cur, 2) if tp_cur is not None else None,
                               "value_bps": round(tp_cur * 100, 0) if tp_cur is not None else None, "pctile_10y": tp_pct},
        "highest_yield_per_duration": best,
        "extension_favoured": favorable,
        "read": (f"cash ({cash['ticker']}) yields {cash['yield_pct']}% at duration {cash['duration']}, "
                 f"intermediate ({inter['ticker']}) {inter['yield_pct']}% at duration {inter['duration']}, "
                 f"long ({long['ticker']}) {long['yield_pct']}% at duration {long['duration']}; "
                 f"the yield per unit of duration is highest at {best}."),
        "note": ("Descriptive, not a rate call. The historical evidence that starting yield explains most "
                 "of a bond sleeve's multi-year return is the basis; a low term-premium percentile means "
                 "extension is thinly compensated."),
    }


# ── 3.2 are you paid to take credit ────────────────────────────────────────
def q_credit(credit: dict) -> dict:
    """IG and HY spread percentiles translated to a yield pickup over duration-matched
    Treasuries (the OAS is that pickup by construction). Descriptive; no spread forecast."""
    ig, hy = credit.get("ig", {}), credit.get("hy", {})
    def leg(x, label):
        return {"index": label, "pickup_bps": x.get("oas_bps"), "pctile_10y": x.get("pctile_10y"),
                "state": x.get("state")}
    return {
        "question": "Are you paid to take credit?",
        "ig": leg(ig, "IG (BAMLC0A0CM)"), "hy": leg(hy, "HY (BAMLH0A0HYM2)"),
        "read": (f"IG spreads pick up {ig.get('oas_bps')}bp over duration-matched Treasuries "
                 f"({ig.get('pctile_10y')}th percentile, {ig.get('state')}); HY {hy.get('oas_bps')}bp "
                 f"({hy.get('pctile_10y')}th percentile, {hy.get('state')})."),
        "note": ("The pickup is the option-adjusted spread over duration-matched Treasuries. Credit "
                 "spreads mean-revert slowly; a tight percentile means little compensation for default "
                 "and illiquidity risk. Descriptive; no spread-direction prediction."),
    }


# ── 3.3 real vs nominal ────────────────────────────────────────────────────
def q_real_nominal(realnom: dict) -> dict:
    """At the 10-year maturity, which of TIPS and nominal Treasuries has the higher real
    carry given the breakeven. Descriptive — a break-even identity, not an inflation call."""
    be = realnom.get("breakeven_10y_pct")
    pct = realnom.get("breakeven_10y_pctile_10y")
    real10 = realnom.get("real_10y_yield_pct")
    read = (f"At the 10-year maturity, TIPS and nominal Treasuries carry the same real yield when "
            f"inflation runs at the {be}% breakeven; TIPS out-carry nominal if realized inflation "
            f"exceeds {be}%, nominal out-carry if it runs below. The breakeven sits at its {pct}th "
            f"percentile over ten years — the inflation compensation priced into nominals is "
            f"{'historically high' if (pct is not None and pct >= 70) else 'in its historical range'}.")
    out = {
        "question": "TIPS or nominal Treasuries?",
        "maturity": "10y", "breakeven_pct": be, "breakeven_pctile_10y": pct, "real_10y_yield_pct": real10,
        "read": read,
        "note": "Descriptive; decides only which carries better at the breakeven, not an inflation forecast.",
    }
    if real10 is None:
        out["real_10y_unavailable"] = "DFII10 not yet in the store (pending FRED fetch); the read uses the breakeven identity only"
    return out


# ── 3.4 the rates regime, as a state not a forecast (DIAGNOSTIC) ────────────
def rates_regime(cfg: dict, curve: dict, credit: dict) -> dict:
    """A combined curve-plus-credit state (the fixed-income analogue of the equity regime
    index), pre-registered and frozen in config. A diagnostic lens: gated DIAGNOSTIC, it
    drives no sizing until the Phase 6 retirement test passes."""
    rc = cfg["rates_regime"]
    cs = curve.get("state")
    ig, hy = credit.get("ig", {}).get("state"), credit.get("hy", {}).get("state")
    stressed = (ig == "stressed") or (hy == "stressed")
    if stressed:
        state, basis = "defense", "credit is stressed"
    elif cs == "inverted":
        state, basis = "duration", "curve is inverted (an association with past rate declines, not a prediction)"
    elif cs in ("normal", "steep"):
        state, basis = "carry", f"curve is {cs} and credit is not stressed"
    else:
        state, basis = "mixed", f"curve is {cs}, credit IG {ig}/HY {hy}"
    return {
        "label": rc["label"],                    # "DIAGNOSTIC" — the referee enforces this
        "state": state,
        "basis": basis,
        "favors": {"carry": "normal/steep curve, non-stressed credit",
                   "duration": "inverted curve (association, not prediction)",
                   "defense": "stressed credit"}[state] if state in ("carry", "duration", "defense") else "no single lean",
        "inputs": {"curve_state": cs, "credit_ig_state": ig, "credit_hy_state": hy},
        "logic": rc["logic"],
        "registration": rc["registration"],
        "gate": rc["gate"],
        "frozen_at": rc.get("frozen_at"),
        "note": ("Diagnostic lens, not a forecast. Gated DIAGNOSTIC: it drives no sizing until the "
                 "pre-registered retirement test passes (Phase 6). Do not execute on this value."),
    }


# ── 4.1 correlation to the equity book (sorted menu) ───────────────────────
ADD_FRACTION = 0.10   # a "given dollar amount" for the marginal read: 10% of NAV, funded from cash


def equity_book():
    """Return series, dollar figures and weights of the current equity book (holdings.json)."""
    h = ba.load_holdings()
    prices = ba.load_prices(); rets = ba.daily_returns(prices)
    last = prices.ffill().iloc[-1]
    vals = {}
    for pos in h.get("holdings", []):
        tk = str(pos.get("ticker", "")).upper(); sh = pos.get("shares") or 0
        if sh > 0 and tk in prices.columns and pd.notna(last.get(tk)):
            vals[tk] = float(sh) * float(last[tk])
    equity = sum(vals.values()); cash = float(h.get("cash") or 0); nav = equity + cash
    w_eq = {tk: v / equity for tk, v in vals.items()} if equity else {}
    eq_series = ba.book_series(rets, w_eq) if w_eq else pd.Series(dtype=float)
    return {"eq_series": eq_series, "equity": equity, "cash": cash, "nav": nav,
            "w_eq": w_eq, "vals": vals, "rets": rets, "prices": prices,
            "holdings_as_of": h.get("as_of")}


def diversifier_menu(sm: dict) -> dict:
    """The sleeve menu sorted by correlation to the book ascending: a sleeve's value to THIS
    book is its correlation with what is already held, not its standalone yield (order 4.1)."""
    rows = [{"ticker": r["ticker"], "asset_class": r.get("asset_class"), "role": r.get("role"),
             "correlation_to_book": r.get("correlation_to_book"),
             "distribution_yield_pct": r.get("distribution_yield_pct"),
             "effective_duration": r.get("effective_duration"),
             "yield_per_duration": r.get("yield_per_duration"),
             "vol_126_ann": r.get("vol_126_ann")}
            for r in sm.values()]
    rows.sort(key=lambda r: (r["correlation_to_book"] is None, r["correlation_to_book"]))
    return {"sorted_by": "correlation_to_book ascending",
            "note": "A sleeve's value to this book is its correlation with what is already held, not its standalone yield.",
            "sleeves": rows}


# ── 4.2 the conditional message ────────────────────────────────────────────
def _book_json() -> dict:
    p = bc.DATA / "book.json"
    return json.loads(p.read_text()) if p.exists() else {}


def conditional_message(bk: dict, srets: pd.DataFrame, spy_ret: pd.Series, bj: dict) -> dict:
    """The marginal effect on the book's volatility and stress loss of adding a given dollar
    amount (10% of NAV, funded from cash) of each sleeve, at the book's current concentration.
    The honest first message: while one name dominates the book's variance, fixed-income
    diversification has limited effect until the equity concentration is reduced."""
    nav, equity = bk["nav"], bk["equity"]
    eqcash = bk["eq_series"] * (equity / nav) if len(bk["eq_series"]) else pd.Series(dtype=float)
    vol_base = ba.ann_vol(eqcash.iloc[-bc.WINDOW:], min_obs=bc.MIN_OBS)

    # top-name concentration from book.json risk shares
    positions = bj.get("positions", [])
    rs = [(p["ticker"], p.get("risk_share"), p.get("share_nav"), (p.get("beta_spy") or {}).get("beta"), p.get("value"))
          for p in positions if p.get("risk_share") is not None]
    rs.sort(key=lambda x: -(x[1] or 0))
    top = rs[0] if rs else (None, None, None, None, None)
    top_share = top[1]
    fires = top_share is not None and top_share > 0.40

    # reference stress: SPY −20% (from book.json)
    spy20 = next((s for s in bj.get("stress", []) if s.get("id") == "spy_-20"), {})
    base_loss = spy20.get("loss"); base_share = spy20.get("share_nav")

    add = ADD_FRACTION * nav
    # per-sleeve marginal effect
    marg = []
    for tk in bc.sleeve_tickers():
        sr = srets[tk].dropna() if tk in srets.columns else pd.Series(dtype=float)
        if not len(sr) or vol_base is None:
            marg.append({"ticker": tk, "d_vol": None, "beta_spy": None, "d_stress_spy20_share": None}); continue
        combined = (eqcash + ADD_FRACTION * sr).dropna()
        vol_new = ba.ann_vol(combined.iloc[-bc.WINDOW:], min_obs=bc.MIN_OBS)
        b = ba.ols_beta(sr, spy_ret).get("beta")
        d_stress = (add * b * -0.20) / nav if b is not None else None     # change in SPY−20 loss as share of NAV
        marg.append({"ticker": tk,
                     "d_vol": round(vol_new - vol_base, 4) if vol_new is not None else None,
                     "beta_spy": round(b, 3) if b is not None else None,
                     "d_stress_spy20_share": round(d_stress, 4) if d_stress is not None else None})

    # the best-diversifying intermediate Treasury for the headline (lowest corr among the Treasury ladder ex-cash)
    ladder = [m for m in marg if m["ticker"] in ("SHY", "IEF", "TLT", "GOVT")]
    rep = next((m for m in marg if m["ticker"] == "IEF"), (ladder[0] if ladder else None))
    rep_tk = rep["ticker"] if rep else None
    vol_with_rep = round(vol_base + rep["d_vol"], 4) if (rep and rep["d_vol"] is not None) else None

    # trim comparison: halve the top name to cash, recompute the SPY−20 loss
    trim = {}
    if top[0] and top[3] is not None and top[4] is not None and base_loss is not None:
        removed = 0.5 * top[4] * top[3] * -0.20        # loss removed by selling half the top name (its SPY−20 contribution)
        trim_loss = base_loss - removed
        trim = {"action": f"halve {top[0]} to cash",
                "spy20_loss": round(trim_loss, 2),
                "spy20_share_nav": round(trim_loss / nav, 4),
                "improvement_vs_current_share": round((trim_loss - base_loss) / nav, 4)}

    msg = None
    if fires and rep_tk is not None:
        msg = (f"The top name ({top[0]}) is {top_share*100:.0f}% of the book's variance, above 40%. "
               f"Adding {ADD_FRACTION*100:.0f}% of NAV (${add:,.0f}) in an intermediate Treasury "
               f"({rep_tk}, ~0 equity beta, funded from cash) leaves the SPY −20% stress loss at "
               f"{base_share*100:.1f}% of NAV essentially unchanged and moves book volatility from "
               f"{vol_base*100:.1f}% to {vol_with_rep*100:.1f}%. Halving {top[0]} to cash instead takes "
               f"the SPY −20% loss to {trim.get('spy20_share_nav',0)*100:.1f}% of NAV. Fixed-income "
               f"diversification has limited effect until the equity concentration is reduced.")
    return {
        "fires": fires,
        "top_name": {"ticker": top[0], "risk_share": top_share, "share_nav": top[2]},
        "threshold": 0.40,
        "book_vol_with_cash": round(vol_base, 4) if vol_base is not None else None,
        "reference_stress": {"id": "spy_-20", "loss": base_loss, "share_nav": base_share},
        "add_fraction_of_nav": ADD_FRACTION, "add_dollars": round(add, 2),
        "representative_diversifier": rep_tk,
        "book_vol_with_representative": vol_with_rep,
        "trim_comparison": trim,
        "marginal": marg,
        "message": msg,
        "note": ("The marginal effect of adding a bond sleeve, at the book's current concentration. "
                 "This is the honest first message and is shown, not buried. Descriptive."),
    }


# ── payload ────────────────────────────────────────────────────────────────
def build() -> dict:
    cfg = bc.load_state_config()
    ind, store, through = load_fred()

    curve = curve_state(cfg, ind, through)
    credit = credit_state(cfg, ind, through)
    realnom = real_nominal(ind, through)
    sm = load_sleeve_metrics()
    alloc = {"duration": q_duration(sm, ind, through), "credit": q_credit(credit),
             "real_vs_nominal": q_real_nominal(realnom)}
    rregime = rates_regime(cfg, curve, credit)
    bk = equity_book()
    srets = ba.daily_returns(bc.load_sleeve_prices())
    etfs = ba.load_etfs(); spy_ret = ba.daily_returns(etfs)["SPY"] if "SPY" in etfs.columns else pd.Series(dtype=float)
    bj = _book_json()
    book_int = {"menu": diversifier_menu(sm),
                "conditional_message": conditional_message(bk, srets, spy_ret, bj)}

    session = str(through.date())
    return {
        "cadence": "daily",
        "session_date": session,
        "as_of": datetime.now().astimezone().date().isoformat(),
        "computed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "vintage": {"store": store, "fred_through": str(through.date()), "history_years": HISTORY_YEARS},
        "config_frozen_at": cfg.get("frozen_at"),
        "curve": curve,
        "credit": credit,
        "real_nominal": realnom,
        "allocation_questions": alloc,
        "rates_regime": rregime,
        "book_integration": book_int,
        "note": "descriptive; states and associations only, no rate forecast; no buy or sell instruction.",
    }


def main() -> int:
    payload = build()
    out = bc.BONDS / "states.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    c = payload["curve"]
    log(f"saved states.json  vintage={payload['vintage']['store']} through {payload['session_date']}")
    log(f"  curve: 2s10s {c['slope_2s10s_bps']}bp (pctile {c['slope_2s10s_pctile_10y']}) → state {c['state']!r}")
    cr = payload["credit"]
    log(f"  credit IG: {cr['ig']['oas_bps']}bp (pctile {cr['ig']['pctile_10y']}) → {cr['ig']['state']!r} · "
        f"HY: {cr['hy']['oas_bps']}bp (pctile {cr['hy']['pctile_10y']}) → {cr['hy']['state']!r}")
    rr = payload["rates_regime"]
    log(f"  rates-regime [{rr['label']}]: {rr['state']!r} ({rr['basis']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
