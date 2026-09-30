#!/usr/bin/env python3
"""daily_brief.py — the daily brief: a colour by rule, a narrative under a validator, an
append-only log (Execution Order of 30 September 2026, items B1–B3).

B1  Each session after the close, a colour from the pre-registered rules in
    data/brief_rules.json — never set by a model. RED if any red rule fires; YELLOW if no red
    rule fires and any yellow rule fires; GREEN otherwise. Every entry stores the list of
    rules that fired. The colour describes the state of the session; it is not a forecast.
B2  A facts payload is assembled from served data only: index and sector moves, the regime
    reading and label, the complacency and shock flags, VIX and SKEW, the 10-year yield and its
    change, the book's change and top contributor, held-name moves above 3 percent, today's
    releases with their prints where available, and the next three events. A language model
    writes one entry of at most 40 words from the payload. The validator rejects the entry if
    any number in the text is absent from the payload (after rounding), if it contains a
    forecast verb, or if it names a security not in the payload; on rejection the template
    sentence is used and the rejection is logged. No recommendation, no direction.
B3  data/daily_log.jsonl, append-only, one entry per session: date, colour, rules fired, the
    text, the facts payload hash, and whether the text came from the model or the template.
    An entry is never edited; a correction is a new entry referencing the old (--correct).

The model is called only when the environment carries the key named in the rules file
(ANTHROPIC_API_KEY); the key is never printed or stored. Without it the template is used and
the reason is logged.

Usage:
  python scripts/daily_brief.py [--session YYYY-MM-DD] [--dry-run] [--print]
  python scripts/daily_brief.py --validate-text "…"          # exercise the validator; writes nothing
  python scripts/daily_brief.py --correct ENTRY_ID --reason "…" [--session …]
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATA = REPO / "data"
sys.path.insert(0, str(HERE))
from trading_calendar import is_trading_day, last_completed_session, now_et, prev_trading_day  # noqa: E402

RULES_PATH = DATA / "brief_rules.json"
LOG_PATH = DATA / "daily_log.jsonl"
FACTS_PATH = DATA / "brief_facts.json"
SECTORS = {"xlk": "Technology", "xlf": "Financials", "xle": "Energy", "xlv": "Health care", "xli": "Industrials",
           "xly": "Consumer discretionary", "xlp": "Consumer staples", "xlu": "Utilities", "xlb": "Materials",
           "xlre": "Real estate", "xlc": "Communication services"}
INDEX_ETFS = {"spy": "SPY", "qqq": "QQQ", "iwm": "IWM", "smh": "SMH"}
MACRO_TYPES = {"FOMC", "CPI", "NFP", "PCE", "PPI", "GDP", "JOLTS", "ISM_MFG", "ISM_SVC", "RETAIL", "CLAIMS", "ELECTION", "OPEX", "TREASURY"}
PRINT_SERIES = {   # FRED series for the day's releases, with how the print is read
    "CPI": ("CPIAUCSL", "mom_pct"), "PPI": ("PPIFIS", "mom_pct"), "PCE": ("PCEPI", "mom_pct"), "RETAIL": ("RSAFS", "mom_pct"),
    "NFP": ("PAYEMS", "change_k"), "JOLTS": ("JTSJOL", "level_k"), "CLAIMS": ("ICSA", "level_k"),
    "GDP": ("A191RL1Q225SBEA", "level_pct"), "FOMC": ("DFEDTARU", "level_pct"),
}
PROHIBITED = ("edge", "alpha")
DIRECTIVES = ("buy now", "sell now", "buy ", "sell ", "go long", "go short", "add to", "trim ", "hedge now")
SYSTEM_PROMPT = ("You write the daily brief line for a portfolio dashboard. Write ONE plain sentence of at most 40 words "
                 "describing the trading session, using only facts and numbers present in the JSON payload; copy every number "
                 "exactly as it appears there (same rounding). Describe the state only: never forecast, never recommend, never "
                 "use the words will, expect, likely, should, could, may, might, outlook. Name no security that is not in the "
                 "payload. Do not use the words edge or alpha. Output the sentence only.")


def log(m: str) -> None:
    print(f"[daily_brief] {m}", flush=True)


def r2(x, nd=2):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(f) else round(f, nd)


def load_rules(path: Path = RULES_PATH) -> dict:
    return json.load(open(path))


def sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def regime_label(R: float, prev_label: str | None = None) -> str:
    """The corridor label (scripts/regime_label.py; audit 30-Sept T3) off the previous session's
    published label — never re-derived from R alone."""
    from regime_label import label_with_corridor
    return label_with_corridor(R, prev_label)


def previous_published_label(session: str) -> str | None:
    """The tournament row's label for the last published session before `session`."""
    try:
        H = json.load(open(DATA / "tournament.json")).get("history", [])
        before = [h for h in H if str(h.get("date", "")) < session]
        return before[-1].get("regime") if before else None
    except Exception:
        return None


# ── the facts payload (served data only) ─────────────────────────────────
def _pct(a, b):
    return None if (a is None or b is None or b == 0) else (float(a) / float(b) - 1.0) * 100.0


def _prev_index(idx: pd.DatetimeIndex, s: pd.Timestamp):
    before = idx[idx < s]
    return before[-1] if len(before) else None


def _chandelier(tk: str, session: str, closes: pd.Series, lookback: int, mult: float) -> tuple[float | None, str]:
    """22-session high − 3 × ATR(22) on OHLC from the provider; close-based range when OHLC is
    unavailable (flagged). Through the session (bars after it are dropped)."""
    try:
        import yfinance as yf
        h = yf.Ticker(tk).history(period="6mo", auto_adjust=False)
        h = h[h.index.tz_localize(None) <= pd.Timestamp(session)] if h.index.tz is not None else h[h.index <= pd.Timestamp(session)]
        if len(h) >= lookback + 1 and {"High", "Low", "Close"} <= set(h.columns):
            hi, lo, cl = h["High"], h["Low"], h["Close"]
            tr = pd.concat([hi - lo, (hi - cl.shift()).abs(), (lo - cl.shift()).abs()], axis=1).max(axis=1)
            atr = tr.rolling(lookback).mean()
            lvl = float(hi.rolling(lookback).max().iloc[-1] - mult * atr.iloc[-1])
            if np.isfinite(lvl):
                return lvl, "OHLC (provider)"
    except Exception:
        pass
    c = closes.dropna().loc[:pd.Timestamp(session)]
    if len(c) < lookback + 1:
        return None, "insufficient history"
    tr = (c - c.shift()).abs()
    lvl = float(c.rolling(lookback).max().iloc[-1] - mult * tr.rolling(lookback).mean().iloc[-1])
    return lvl, "closes only (no OHLC available; close-to-close range)"


def _fred_print(series: str, how: str):
    key = os.environ.get("FRED_API_KEY")
    if not key:
        return None, "print not fetched (no FRED key in this environment)"
    try:
        from fredapi import Fred
        s = Fred(api_key=key).get_series(series).dropna()
        if len(s) < 2:
            return None, "series too short"
        last, prev = float(s.iloc[-1]), float(s.iloc[-2])
        d = str(s.index[-1].date())
        if how == "mom_pct":
            return {"value": r2((last / prev - 1) * 100, 2), "unit": "% m/m", "period": d}, "FRED at run time"
        if how == "change_k":
            return {"value": r2((last - prev), 0), "unit": "thousands, change", "period": d}, "FRED at run time"
        if how == "level_k":
            return {"value": r2(last, 0), "unit": "thousands", "period": d}, "FRED at run time"
        return {"value": r2(last, 2), "unit": "%", "period": d}, "FRED at run time"
    except Exception as e:  # noqa: BLE001
        return None, f"print unavailable ({type(e).__name__})"


def facts_payload(session: str, rules: dict) -> dict:
    src = DATA / "source"
    px = pd.read_parquet(src / "prices_daily.parquet"); px.index = pd.to_datetime(px.index)
    etf = pd.read_parquet(src / "sector_etfs.parquet"); etf.index = pd.to_datetime(etf.index)
    vol = pd.read_parquet(src / "vol_indicators.parquet"); vol.index = pd.to_datetime(vol.index)
    fred = pd.read_parquet(src / "fred_indicators.parquet"); fred.index = pd.to_datetime(fred.index)
    s = pd.Timestamp(session)
    if s not in vol.index and s not in etf.index:
        raise SystemExit(f"[daily_brief] the served closes do not carry the session {session} (vol through {vol.index[-1].date()}, ETFs through {etf.index[-1].date()})")
    notes: list[str] = []
    # indices and sectors
    sp = _prev_index(vol.index, s) if s in vol.index else None
    spx = {"close": r2(vol.loc[s, "spx"]) if s in vol.index else None,
           "change_pct": r2(_pct(vol.loc[s, "spx"], vol.loc[sp, "spx"])) if (sp is not None) else None}
    ep = _prev_index(etf.index, s) if s in etf.index else None
    indices = {"S&P 500": spx}
    for col, lab in INDEX_ETFS.items():
        if col in etf.columns and s in etf.index and ep is not None:
            indices[lab] = {"close": r2(etf.loc[s, col]), "change_pct": r2(_pct(etf.loc[s, col], etf.loc[ep, col]))}
    sectors = {}
    for col, lab in SECTORS.items():
        if col in etf.columns and s in etf.index and ep is not None:
            v = _pct(etf.loc[s, col], etf.loc[ep, col])
            if v is not None:
                sectors[lab] = r2(v)
    sec_sorted = sorted(sectors.items(), key=lambda kv: kv[1])
    # regime: the continuous revised series for the streak, the published vintage beside it
    rd = pd.read_csv(DATA / "regime_daily.csv"); rd["date"] = rd["date"].astype(str)
    rd = rd[rd["date"] <= session].reset_index(drop=True)
    R = float(rd["R_t"].iloc[-1]) if len(rd) else None
    streak = 0
    if len(rd) >= 2:
        vals = rd["R_t"].astype(float).tolist()
        i = len(vals) - 1
        while i >= 1 and vals[i] > vals[i - 1]:
            streak += 1; i -= 1
    pub = pd.read_csv(DATA / "regime_daily_published.csv"); pub["date"] = pub["date"].astype(str)
    prow = pub[pub["date"] == session]
    R_pub = float(prow["R_t_published"].iloc[0]) if len(prow) and pd.notna(prow["R_t_published"].iloc[0]) else None
    # the label: the tournament row's published label for the session when it exists (the
    # corridor off its predecessor), else the corridor off the last published label
    prev_lab = previous_published_label(session)
    row_lab = None
    try:
        row_lab = next((h.get("regime") for h in json.load(open(DATA / "tournament.json")).get("history", []) if h.get("date") == session), None)
    except Exception:
        pass
    label = row_lab or (regime_label(R, prev_lab) if R is not None else None)
    regime = {"R": r2(R, 4), "label": label, "label_basis": "tournament row" if row_lab else "corridor off the previous published label",
              "series_date": rd["date"].iloc[-1] if len(rd) else None,
              "prev_R": r2(float(rd["R_t"].iloc[-2]), 4) if len(rd) >= 2 else None, "rising_streak_sessions": streak,
              "published_R": r2(R_pub, 4), "published_label": (regime_label(R_pub, prev_lab) if R_pub is not None else None)}
    # flags: intraday.json when reconciled to the session, else recomputed by the same rules
    flags = {"complacency": None, "shock": None, "source": None, "complacency_reason": None, "shock_reasons": []}
    ip = DATA / "intraday.json"
    ij = json.load(open(ip)) if ip.exists() else {}
    vix = r2(vol.loc[s, "vix"]) if s in vol.index else None
    vix_prev = r2(vol.loc[sp, "vix"]) if sp is not None else None
    vix_chg = r2(_pct(vix, vix_prev), 1)
    vix3m = r2(vol.loc[s, "vix3m"]) if s in vol.index else None
    skew = r2(vol.loc[s, "skew"], 1) if s in vol.index else None
    if ij.get("session_date") == session and ij.get("reconciled_to_canonical") == session and isinstance(ij.get("complacency_active"), bool):
        flags.update({"complacency": bool(ij["complacency_active"]), "shock": bool(ij.get("shock_active")), "source": "intraday.json (reconciled to the canonical close)",
                      "complacency_reason": ij.get("complacency_reason"), "shock_reasons": ij.get("shock_reasons") or []})
    else:
        reasons = []
        if vix_chg is not None and vix_chg > 15: reasons.append(f"VIX +{vix_chg:.0f}%")
        if spx["change_pct"] is not None and spx["change_pct"] < -1.5: reasons.append(f"SPX {spx['change_pct']:.1f}%")
        if vix is not None and vix3m is not None and vix > vix3m: reasons.append("VIX term backwardated")
        if s in vol.index and sp is not None and {"hyg", "tlt"} <= set(vol.columns):
            cc = _pct(vol.loc[s, "hyg"], vol.loc[sp, "hyg"]); tt = _pct(vol.loc[s, "tlt"], vol.loc[sp, "tlt"])
            if cc is not None and tt is not None and (cc - 0.25 * tt) < -1.0: reasons.append(f"HY credit (duration-adj) {cc - 0.25 * tt:.1f}%")
        comp = (skew is not None and vix is not None and skew > 140 and vix < 17)
        flags.update({"complacency": comp, "shock": bool(reasons), "source": "recomputed from the canonical closes (intraday.json not reconciled to the session)",
                      "complacency_reason": (f"SKEW {skew:.0f} > 140 and VIX {vix:.1f} < 17" if comp else None), "shock_reasons": reasons})
    volatility = {"vix": vix, "vix_prev": vix_prev, "vix_change_pct": vix_chg, "vix3m": vix3m, "skew": skew,
                  "vvix": r2(vol.loc[s, "vvix"]) if (s in vol.index and "vvix" in vol.columns) else None}
    # rates: the latest 10-year on or before the session (FRED lag), and its change
    y = fred["us10y"].dropna(); y = y[y.index <= s]
    rates = {"us10y_pct": r2(y.iloc[-1]) if len(y) else None, "us10y_date": str(y.index[-1].date()) if len(y) else None,
             "us10y_change_bp": r2((float(y.iloc[-1]) - float(y.iloc[-2])) * 100, 0) if len(y) >= 2 else None,
             "us10y_lag_note": (None if (len(y) and y.index[-1] == s) else f"latest FRED observation {str(y.index[-1].date()) if len(y) else 'none'} (published with a lag)")}
    if rates["us10y_lag_note"]: notes.append("10-year yield: " + rates["us10y_lag_note"])
    # credit
    bs = DATA / "bonds" / "states.json"
    credit = {"ig_state": None, "hy_state": None, "hy_oas_bps": None, "ig_oas_bps": None, "as_of": None}
    if bs.exists():
        cr = (json.load(open(bs)).get("credit") or {})
        credit = {"ig_state": (cr.get("ig") or {}).get("state"), "hy_state": (cr.get("hy") or {}).get("state"),
                  "hy_oas_bps": r2((cr.get("hy") or {}).get("oas_bps"), 0), "ig_oas_bps": r2((cr.get("ig") or {}).get("oas_bps"), 0),
                  "as_of": (cr.get("hy") or {}).get("as_of")}
    # the book: current holdings on the session's closes; change over the prior session
    hj = json.load(open(DATA / "holdings.json"))
    held = [(str(h["ticker"]).upper(), float(h["shares"])) for h in hj.get("holdings", []) if (h.get("shares") or 0) > 0]
    cash = float(hj.get("cash") or 0.0)
    pp = _prev_index(px.index, s)
    moves, val_now, val_prev, contrib = [], 0.0, 0.0, []
    for tk, sh in held:
        if tk not in px.columns or s not in px.index or pd.isna(px.loc[s, tk]) or pp is None or pd.isna(px.loc[pp, tk]):
            moves.append({"ticker": tk, "close": None, "change_pct": None, "note": "no close for the session"}); continue
        c1, c0 = float(px.loc[s, tk]), float(px.loc[pp, tk])
        val_now += sh * c1; val_prev += sh * c0
        d = sh * (c1 - c0); contrib.append((tk, d))
        moves.append({"ticker": tk, "close": r2(c1), "change_pct": r2(_pct(c1, c0)), "dollars": r2(d, 0)})
    nav_prev = val_prev + cash; nav_now = val_now + cash
    top = max(contrib, key=lambda t: abs(t[1])) if contrib else None
    book = {"nav": r2(nav_now, 0), "nav_prev": r2(nav_prev, 0), "change_pct": r2(_pct(nav_now, nav_prev)), "change_dollars": r2(nav_now - nav_prev, 0),
            "top_contributor": ({"ticker": top[0], "dollars": r2(top[1], 0),
                                 "change_pct": next((m["change_pct"] for m in moves if m["ticker"] == top[0]), None)} if top else None),
            "held_moves": moves, "moves_over_3pct": [m for m in moves if m.get("change_pct") is not None and abs(m["change_pct"]) > 3.0],
            "holdings_as_of": hj.get("as_of"), "cash": r2(cash, 0),
            "note": "current holdings on the session's closes; cash unchanged; a holdings change inside the day is not modelled"}
    # held levels: 200-day average and the Chandelier level
    p6 = rules["rules"]; r6 = next((r for r in p6 if r["id"] == "R6"), {"params": {}})
    lb, mult, ma_n = r6["params"].get("chandelier_lookback", 22), r6["params"].get("atr_multiple", 3.0), r6["params"].get("ma_sessions", 200)
    sig = {}
    sp_ = DATA / "ticker_signals.json"
    if sp_.exists():
        sig = json.load(open(sp_)).get("signals", {})
    levels = []
    for tk, sh in held:
        if tk not in px.columns or s not in px.index:
            continue
        c = px[tk].dropna().loc[:s]
        close = float(c.iloc[-1]) if len(c) else None
        ma = float(c.iloc[-ma_n:].mean()) if len(c) >= ma_n else None
        ch, ch_src = _chandelier(tk, session, px[tk], lb, mult)
        prev_close = float(c.iloc[-2]) if len(c) >= 2 else None
        trail = ((sig.get(tk) or {}).get("stops") or {}).get("trail_stop")
        levels.append({"ticker": tk, "close": r2(close), "ma200": r2(ma), "ma200_dist_pct": r2(_pct(close, ma)),
                       "chandelier": r2(ch), "chandelier_source": ch_src,
                       "below_chandelier": (close is not None and ch is not None and close < ch),
                       "below_ma200": (close is not None and ma is not None and close < ma),
                       "prev_close": r2(prev_close), "rulebook_trailing_level": trail})
    # calendar: today's releases with prints, the next three events, the next two sessions
    cal = json.load(open(DATA / "event_calendar.json")); events = cal.get("events", [])
    held_set = {tk for tk, _ in held}
    today_ev = [e for e in events if e.get("date") == session and e.get("type") in MACRO_TYPES and e.get("type") not in ("TREASURY",)]
    releases = []
    for e in today_ev:
        pr, pr_note = (None, "no print series for this type")
        if e["type"] in PRINT_SERIES:
            pr, pr_note = _fred_print(*PRINT_SERIES[e["type"]])
        releases.append({"type": e["type"], "name": e.get("name"), "impact": e.get("impact"), "time_et": e.get("time_et"), "print": pr, "print_note": pr_note})
    s1 = next_session(session); s2 = next_session(s1)
    upcoming = {"sessions": [s1, s2],
                "high_impact_macro": [{"date": e["date"], "type": e["type"], "name": e.get("name")} for e in events
                                      if e.get("date") in (s1, s2) and e.get("type") in MACRO_TYPES and e.get("impact") == "high"],
                "held_earnings": [{"date": e["date"], "ticker": str(e.get("ticker", "")).upper()} for e in events
                                  if e.get("date") in (s1, s2) and e.get("type") == "EARNINGS" and str(e.get("ticker", "")).upper() in held_set]}
    nxt = [e for e in events if e.get("date") > session and e.get("impact") in ("high", "medium")
           and (e.get("type") != "EARNINGS" or str(e.get("ticker", "")).upper() in held_set)]
    nxt.sort(key=lambda e: (e["date"], e.get("type", "")))
    next_events = [{"date": e["date"], "type": e["type"], "label": e.get("label"), "name": e.get("name"), "impact": e.get("impact"),
                    "ticker": e.get("ticker")} for e in nxt[:3]]
    clusters = [c for c in cal.get("clusters", []) if c.get("date", "") >= session][:3]
    payload = {"session": session, "indices": indices, "sectors": {k: v for k, v in sectors.items()},
               "sectors_weakest": sec_sorted[:2], "sectors_strongest": sec_sorted[-2:][::-1],
               "regime": regime, "flags": flags, "volatility": volatility, "rates": rates, "credit": credit, "book": book,
               "held_levels": levels, "releases_today": releases, "upcoming_two_sessions": upcoming, "next_events": next_events,
               "clusters_ahead": clusters, "tickers": sorted(held_set | set(INDEX_ETFS.values())), "notes": notes,
               "sources": ["data/source/prices_daily.parquet", "data/source/sector_etfs.parquet", "data/source/vol_indicators.parquet",
                           "data/source/fred_indicators.parquet", "data/regime_daily.csv", "data/regime_daily_published.csv",
                           "data/intraday.json", "data/bonds/states.json", "data/holdings.json", "data/ticker_signals.json",
                           "data/event_calendar.json"]}
    return payload


def next_session(d: str) -> str:
    cur = pd.Timestamp(d) + pd.Timedelta(days=1)
    while not is_trading_day(cur.strftime("%Y-%m-%d")):
        cur += pd.Timedelta(days=1)
    return cur.strftime("%Y-%m-%d")


# ── the colour, by rule ─────────────────────────────────────────────────
def evaluate_rules(p: dict, rules: dict) -> tuple[str, list[dict]]:
    fired: list[dict] = []
    def fire(rule, evidence):
        fired.append({"id": rule["id"], "color": rule["color"], "text": rule["text"], "evidence": evidence})
    for rule in rules["rules"]:
        rid, prm = rule["id"], rule.get("params", {})
        if rid == "R1":
            lab = (p.get("regime") or {}).get("label")
            if lab in prm.get("labels", []): fire(rule, f"regime label {lab}")
        elif rid == "R2":
            if (p.get("flags") or {}).get("shock") is True: fire(rule, "; ".join((p["flags"].get("shock_reasons") or [])) or "shock active")
        elif rid == "R3":
            v = ((p.get("indices") or {}).get("S&P 500") or {}).get("change_pct")
            if v is not None and v < prm.get("threshold_pct", -2.0): fire(rule, f"S&P 500 {v:+.2f}%")
        elif rid == "R4":
            v = (p.get("volatility") or {}).get("vix_change_pct")
            if v is not None and v > prm.get("threshold_pct", 20.0): fire(rule, f"VIX {v:+.1f}%")
        elif rid == "R5":
            v = (p.get("book") or {}).get("change_pct")
            if v is not None and v < prm.get("threshold_pct", -3.0): fire(rule, f"book {v:+.2f}%")
        elif rid == "R6":
            hits = [l["ticker"] for l in p.get("held_levels", []) if l.get("below_chandelier") and l.get("below_ma200")]
            if hits: fire(rule, "below both levels: " + ", ".join(hits))
        elif rid == "R7":
            cr = p.get("credit") or {}
            st = [k for k in ("ig_state", "hy_state") if cr.get(k) in prm.get("states", ["stressed"])]
            if st: fire(rule, "credit " + ", ".join(f"{k.split('_')[0].upper()} {cr[k]}" for k in st))
        elif rid == "Y1":
            if (p.get("flags") or {}).get("complacency") is True: fire(rule, (p["flags"].get("complacency_reason") or "complacency on"))
        elif rid == "Y2":
            up = p.get("upcoming_two_sessions") or {}
            items = [f"{e['type']} {e['date']}" for e in up.get("high_impact_macro", [])] + [f"{e['ticker']} earnings {e['date']}" for e in up.get("held_earnings", [])]
            if items: fire(rule, "; ".join(items))
        elif rid == "Y3":
            n = (p.get("regime") or {}).get("rising_streak_sessions") or 0
            if n >= prm.get("sessions", 5): fire(rule, f"regime index up {n} sessions in a row")
        elif rid == "Y4":
            r = p.get("rates") or {}
            lvl, chg = r.get("us10y_pct"), r.get("us10y_change_bp")
            ev = []
            if lvl is not None and lvl > prm.get("level_pct", 5.0): ev.append(f"10-year {lvl:.2f}% ({r.get('us10y_date')})")
            if chg is not None and chg > prm.get("change_bp", 15.0): ev.append(f"10-year {chg:+.0f} bp")
            if ev: fire(rule, "; ".join(ev))
        elif rid == "Y5":
            v = (p.get("book") or {}).get("change_pct")
            if v is not None and prm.get("from_pct", -3.0) <= v <= prm.get("to_pct", -1.5): fire(rule, f"book {v:+.2f}%")
        elif rid == "Y6":
            band = prm.get("band_pct", 3.0)
            hits = [f"{l['ticker']} {l['ma200_dist_pct']:+.1f}%" for l in p.get("held_levels", []) if l.get("ma200_dist_pct") is not None and abs(l["ma200_dist_pct"]) <= band]
            if hits: fire(rule, "; ".join(hits))
    colors = [f["color"] for f in fired]
    color = "RED" if "RED" in colors else ("YELLOW" if "YELLOW" in colors else "GREEN")
    return color, fired


# ── the narrative: template, model, validator ────────────────────────────
def _fmt_signed(v, nd=2):
    return "n/a" if v is None else f"{v:+.{nd}f}"


def template_text(p: dict) -> str:
    spx = ((p.get("indices") or {}).get("S&P 500") or {}).get("change_pct")
    v = p.get("volatility") or {}; rg = p.get("regime") or {}; bk = p.get("book") or {}; rt = p.get("rates") or {}
    top = bk.get("top_contributor") or {}
    nxt = (p.get("next_events") or [{}])[0]
    parts = [f"{p['session']}: S&P 500 {_fmt_signed(spx)}%, VIX {v.get('vix')} ({_fmt_signed(v.get('vix_change_pct'), 1)}%), SKEW {v.get('skew')};",
             f"regime {rg.get('label')} (R {rg.get('R')});"]
    if rt.get("us10y_pct") is not None:
        parts.append(f"10-year {rt['us10y_pct']}%;")
    if bk.get("change_pct") is not None:
        parts.append(f"book {_fmt_signed(bk['change_pct'])}%" + (f" ({top.get('ticker')} {_fmt_signed(top.get('change_pct'), 2)}%);" if top else ";"))
    if nxt:
        parts.append(f"next: {nxt.get('label') or nxt.get('type')} {nxt.get('date')}.")
    return " ".join(parts)


def payload_numbers(obj, out=None) -> set:
    """Every number in the payload, as the strings a sentence may quote (0, 1 and 2 decimals,
    with and without sign)."""
    if out is None:
        out = set()
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)) and obj is not None and np.isfinite(obj):
        for nd in (0, 1, 2, 3, 4):
            for v in (obj, abs(obj)):
                out.add(f"{round(float(v), nd):.{nd}f}")
                out.add(str(int(round(float(v), nd)))) if nd == 0 else None
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            payload_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            payload_numbers(v, out)
    # strings (notes, rule texts, dates) supply no figures: only numeric fields count
    return out


def _universe() -> set:
    p = DATA / "universe.txt"
    if not p.exists():
        return set()
    return {ln.strip().upper() for ln in open(p) if ln.strip() and not ln.startswith("#")}


def validate_text(text: str, p: dict, cfg: dict, universe: set | None = None) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    t = (text or "").strip()
    if not t:
        return False, ["empty text"]
    words = t.split()
    if len(words) > int(cfg.get("max_words", 40)):
        reasons.append(f"{len(words)} words > {cfg.get('max_words', 40)}")
    low = " " + re.sub(r"[^a-z0-9 %+.-]", " ", t.lower()) + " "
    for w in cfg.get("forecast_words", []):
        if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low):
            reasons.append(f"forecast word: {w}")
    for w in PROHIBITED:
        if re.search(r"(?<![a-z])" + w + r"(?![a-z])", low):
            reasons.append(f"prohibited word: {w}")
    for d in DIRECTIVES:
        if d.strip() in ("buy", "sell") and re.search(r"(?<![a-z])" + d.strip() + r"(?![a-z])", low):
            reasons.append(f"directive: {d.strip()}")
        elif d.strip() not in ("buy", "sell") and d in low:
            reasons.append(f"directive: {d.strip()}")
    allowed = payload_numbers(p)
    stripped = re.sub(r"\d{4}-\d{2}-\d{2}", " ", t)          # ISO dates are not quoted numbers
    stripped = re.sub(r"\b\d{1,2}:\d{2}\b", " ", stripped)   # times
    for name in ("S&P 500", "S&P500", "Nasdaq 100", "Nasdaq-100", "Russell 2000", "Dow 30"):   # index names carry no figure
        stripped = stripped.replace(name, " ")
    stripped = re.sub(r"(?<![\d.])\d+-(?:year|yr|day|session|month|week|minute)s?\b", " ", stripped, flags=re.I)   # "10-year", "200-day": tenors, not figures
    for m in re.findall(r"(?<![A-Za-z])[-+]?\d+(?:,\d{3})*(?:\.\d+)?", stripped):
        raw = m.replace(",", "").lstrip("+")
        try:
            v = float(raw)
        except ValueError:
            continue
        nd = len(raw.split(".")[1]) if "." in raw else 0
        key = f"{abs(v):.{nd}f}"                     # the figure at the decimals the text shows
        if key not in allowed:
            reasons.append(f"number not in the payload: {m}")
    uni = universe if universe is not None else _universe()
    # a security is "in the payload" when its symbol appears as a whole word anywhere in it
    # (held moves, index ETFs, the next events, the regime label's words) — nothing else may be named
    ptext = json.dumps(p, ensure_ascii=False)
    allowed_tk = set(re.findall(r"(?<![A-Za-z])[A-Z]{1,5}(?![A-Za-z])", ptext)) | {str(x).upper() for x in (p.get("tickers") or [])}
    for tok in re.findall(r"(?<![A-Za-z])[A-Z]{1,5}(?![A-Za-z])", t):
        if tok in uni and tok not in allowed_tk:
            reasons.append(f"security not in the payload: {tok}")
    return (not reasons), reasons


def model_text(p: dict, cfg: dict) -> tuple[str | None, dict]:
    env = cfg.get("api_env", "ANTHROPIC_API_KEY")
    key = os.environ.get(env)
    if not key:
        return None, {"reason": f"model unavailable: {env} not set in this environment"}
    compact = {k: v for k, v in p.items() if k not in ("sources",)}
    body = {"model": cfg.get("model", "claude-sonnet-5-5"), "max_tokens": 160, "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": "Payload:\n" + json.dumps(compact, ensure_ascii=False)}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode("utf-8"),
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read().decode("utf-8"))
        text = " ".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text").strip()
        return (text or None), {"model": cfg.get("model"), "reason": None if text else "empty response"}
    except Exception as e:  # noqa: BLE001
        return None, {"model": cfg.get("model"), "reason": f"model call failed ({type(e).__name__})"}


def narrative(p: dict, rules: dict) -> dict:
    cfg = rules.get("narrative", {})
    rejections: list[dict] = []
    text, meta = model_text(p, cfg)
    source, model = "template", None
    if text is not None:
        ok, why = validate_text(text, p, cfg)
        if ok:
            source, model = "model", meta.get("model")
        else:
            rejections.append({"source": "model", "text": text, "reasons": why})
            text2, meta2 = model_text(p, cfg) if False else (None, {})   # one attempt; the template is the fallback
            text = None
    else:
        rejections.append({"source": "model", "text": None, "reasons": [meta.get("reason") or "model unavailable"]})
    if text is None:
        text = template_text(p)
        ok, why = validate_text(text, p, cfg)
        if not ok:
            rejections.append({"source": "template", "text": text, "reasons": why})
            text = f"{p['session']}: brief withheld; the template failed validation ({'; '.join(why)})."
    return {"text": text, "text_source": source, "model": model, "rejections": rejections, "words": len(text.split())}


# ── the log (append-only) ────────────────────────────────────────────────
def read_log(path: Path = LOG_PATH) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if ln:
            out.append(json.loads(ln))
    return out


def entry_hash(entry: dict) -> str:
    return sha({k: v for k, v in entry.items() if k != "entry_sha256"})


def build_entry(session: str, color: str, fired: list[dict], nar: dict, payload: dict, rules: dict, seq: int,
                supersedes: str | None = None, reason: str | None = None) -> dict:
    entry = {"entry_id": f"brief-{session}-{seq}", "session": session, "logged_at": now_et().isoformat(timespec="seconds"),
             "color": color, "rules_fired": [{"id": f["id"], "text": f["text"], "evidence": f["evidence"]} for f in fired],
             "rules_evaluated": len(rules["rules"]), "rules_sha256": sha(rules),
             "text": nar["text"], "words": nar["words"], "text_source": nar["text_source"], "model": nar.get("model"),
             "rejections": nar.get("rejections", []), "payload_sha256": sha(payload),
             "supersedes": supersedes, "correction_reason": reason,
             "note": "the colour describes the state of the session by pre-registered rules; it is not a forecast; entries are never edited"}
    entry["entry_sha256"] = entry_hash(entry)
    return entry


def append_entry(path: Path, entry: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--print", dest="do_print", action="store_true")
    ap.add_argument("--validate-text", default=None, help="run the validator on this text against the session's payload; write nothing")
    ap.add_argument("--correct", default=None, metavar="ENTRY_ID", help="append a correction entry referencing ENTRY_ID")
    ap.add_argument("--reason", default=None)
    ap.add_argument("--log", default=str(LOG_PATH))
    ap.add_argument("--facts", default=str(FACTS_PATH))
    ap.add_argument("--allow-non-trading", action="store_true")
    args = ap.parse_args()
    rules = load_rules()
    session = args.session or last_completed_session()
    payload = facts_payload(session, rules)
    color, fired = evaluate_rules(payload, rules)
    if args.validate_text is not None:
        ok, why = validate_text(args.validate_text, payload, rules.get("narrative", {}))
        log(f"validator: {'ACCEPTED' if ok else 'REJECTED'} — {'; '.join(why) if why else 'every number in the payload, no forecast verb, no foreign security'}")
        if not ok:
            log(f"template replacement: {template_text(payload)}")
        return 0 if ok else 2
    log_path, facts_path = Path(args.log), Path(args.facts)
    existing = read_log(log_path)
    same = [e for e in existing if e.get("session") == session]
    if same and not args.correct:
        log(f"entry for {session} already logged ({same[-1]['entry_id']}, {same[-1]['color']}); the log is append-only — nothing written")
        if args.do_print:
            log(f"payload colour now: {color} · rules {[f['id'] for f in fired]}")
        return 0
    if args.correct:
        if not any(e.get("entry_id") == args.correct for e in existing):
            raise SystemExit(f"[daily_brief] --correct: entry {args.correct} not in the log")
        if not args.reason:
            raise SystemExit("[daily_brief] --correct needs --reason")
    nar = narrative(payload, rules)
    seq = len(same) + 1
    entry = build_entry(session, color, fired, nar, payload, rules, seq, supersedes=args.correct, reason=args.reason)
    facts = {"cadence": "daily", "session_date": session, "as_of": session, "computed_at": now_et().isoformat(timespec="seconds"),
             "color": color, "rules_fired": entry["rules_fired"], "entry_id": entry["entry_id"], "payload_sha256": entry["payload_sha256"],
             "text": entry["text"], "text_source": entry["text_source"], "payload": payload, "rules_file": "data/brief_rules.json",
             "note": "the facts behind the brief's sentence; served so the validator's claim (every number is in the payload) can be checked by hand"}
    log(f"{session}: {color} · rules {[f['id'] for f in fired] or 'none'} · text from the {nar['text_source']} ({nar['words']} words)")
    log(f"  {entry['text']}")
    for rj in nar.get("rejections", []):
        log(f"  rejection ({rj.get('source')}): {'; '.join(rj.get('reasons', []))}")
    if args.dry_run:
        log("dry run: nothing written")
        return 0
    append_entry(log_path, entry)
    facts_path.write_text(json.dumps(facts, indent=2, ensure_ascii=False) + "\n")
    log(f"appended {entry['entry_id']} to {log_path.name}; wrote {facts_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
