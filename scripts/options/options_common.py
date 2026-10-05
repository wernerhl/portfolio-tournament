#!/usr/bin/env python3
"""options_common.py — shared engine for the options lens (order 26-Sept-2026).

Governing premises. Options information enters in two roles that are never confused:
description and hedging (what the market prices; which structure protects most cheaply)
is shipped as descriptive; return signals enter only as pre-registered candidates on the
union universe, never on the seven-name book. No panel emits a directional recommendation.

1.1  The provider's impliedVolatility field is NEVER used. Implied volatility is computed
     here by Black-Scholes inversion (Brent's method on [0.01, 5.0]) from option prices,
     with the risk-free rate from the canonical 3-month bill and the dividend yield from the
     fundamentals store. Price input per strike: the bid-ask mid where both are positive,
     else the last price flagged `quote: last`. A strike at or below intrinsic + $0.01, or
     whose inversion fails, carries `iv: null` with the reason.

Conventions (stated once, used everywhere):
  * sessions to expiry are the trading sessions strictly AFTER the snapshot session (the chain
    is pulled at 15:45 ET; the pull day's close is minutes away and is not a session of
    variance); T = sessions / 252, used identically for the inversion and the event subtraction.
  * the FRONT tenor is the expiry nearest 30 calendar days, the BACK tenor the expiry
    nearest 90; ATM implied volatility at "about 30 / 90 days" is interpolated linearly in
    calendar days between the two bracketing expiries.
  * ATM at an expiry = the strike nearest spot; the ATM IV is the mean of the call and put
    inversions there (either alone if only one inverts).
  * realized volatility = sample std (ddof=1) of daily log returns × √252 over 21 and 63
    sessions, through the snapshot session.
"""
from __future__ import annotations
import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm

REPO = Path(__file__).resolve().parent.parent.parent
DATA = REPO / "data"
SOURCE = DATA / "source"
OPT = DATA / "options"
VINTAGES = OPT / "vintages"

IV_LO, IV_HI = 0.01, 5.0
FRONT_DAYS, BACK_DAYS = 30, 90
INDEX_ETFS = ["SPY", "QQQ", "SMH"]
ATM_IV_BOUNDS = (0.05, 3.0)          # referee: every computed ATM IV must lie in this range
LIVE_QUOTE_BAR = 0.70                # referee: share of front-expiry strikes with live bid-ask


# ── universe ─────────────────────────────────────────────────────────────
def held_names() -> list[str]:
    p = DATA / "holdings.json"
    if not p.exists():
        return []
    return sorted({str(h["ticker"]).upper() for h in json.load(open(p)).get("holdings", []) if (h.get("shares") or 0) > 0})


def board_top40() -> list[str]:
    p = DATA / "screen" / "scores.json"
    if not p.exists():
        return []
    w = json.load(open(p)).get("watchlist", [])
    return [str(r["ticker"]).upper() for r in w if r.get("on_board_as") != "held"][:40]


def analyzed_universe() -> dict[str, list[str]]:
    """Every held name, the screen board's top 40, and SPY/QQQ/SMH, with the role of each."""
    held, board = held_names(), board_top40()
    roles: dict[str, list[str]] = {}
    for t in held:
        roles.setdefault(t, []).append("held")
    for t in board:
        roles.setdefault(t, []).append("board")
    for t in INDEX_ETFS:
        roles.setdefault(t, []).append("index")
    return dict(sorted(roles.items()))


# ── rates and yields ─────────────────────────────────────────────────────
def risk_free() -> tuple[float, str]:
    """Canonical 3-month bill yield (FRED DGS3MO, `us03m`) as a decimal, with its date."""
    fr = pd.read_parquet(SOURCE / "fred_indicators.parquet")
    fr.index = pd.to_datetime(fr.index)
    s = fr["us03m"].dropna()
    return float(s.iloc[-1]) / 100.0, str(s.index[-1].date())


_FUND = None


def dividend_yield(tk: str) -> tuple[float, str]:
    """Continuous dividend yield (decimal) from the fundamentals store (its dividendYield is
    in percent). ETFs and names without a figure carry 0 with the source flagged."""
    global _FUND
    if _FUND is None:
        p = DATA / "canonical" / "fundamentals.json"
        _FUND = json.load(open(p)).get("tickers", {}) if p.exists() else {}
    v = (_FUND.get(tk) or {}).get("dividendYield")
    if v is None:
        return 0.0, "none on record (0 used)"
    v = float(v)
    return (v / 100.0 if v > 0 else 0.0), "fundamentals store dividendYield (percent)"


# ── Black-Scholes ────────────────────────────────────────────────────────
def _d1d2(S, K, T, r, q, sig):
    d1 = (math.log(S / K) + (r - q + 0.5 * sig * sig) * T) / (sig * math.sqrt(T))
    return d1, d1 - sig * math.sqrt(T)


def bs_price(S: float, K: float, T: float, r: float, q: float, sig: float, cp: str) -> float:
    if T <= 0 or sig <= 0:
        return max(0.0, (S - K) if cp == "c" else (K - S))
    d1, d2 = _d1d2(S, K, T, r, q, sig)
    if cp == "c":
        return S * math.exp(-q * T) * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * math.exp(-q * T) * norm.cdf(-d1)


def bs_delta(S, K, T, r, q, sig, cp) -> float | None:
    if T <= 0 or sig is None or sig <= 0:
        return None
    d1, _ = _d1d2(S, K, T, r, q, sig)
    return math.exp(-q * T) * (norm.cdf(d1) if cp == "c" else norm.cdf(d1) - 1.0)


def bs_gamma(S, K, T, r, q, sig) -> float | None:
    if T <= 0 or sig is None or sig <= 0:
        return None
    d1, _ = _d1d2(S, K, T, r, q, sig)
    return math.exp(-q * T) * norm.pdf(d1) / (S * sig * math.sqrt(T))


def intrinsic(S: float, K: float, cp: str) -> float:
    return max(0.0, (S - K) if cp == "c" else (K - S))


def implied_vol(price: float | None, S: float, K: float, T: float, r: float, q: float, cp: str) -> tuple[float | None, str | None]:
    """Brent inversion on [IV_LO, IV_HI]. Returns (iv, None) or (None, reason)."""
    if price is None or not np.isfinite(price):
        return None, "no price"
    if T <= 0:
        return None, "expired"
    if price <= intrinsic(S, K, cp) + 0.01:
        return None, "at or below intrinsic + 0.01"
    f = lambda s: bs_price(S, K, T, r, q, s, cp) - price
    try:
        lo, hi = f(IV_LO), f(IV_HI)
        if lo > 0:
            return None, "price below the model floor at iv 0.01"
        if hi < 0:
            return None, "price above the model ceiling at iv 5.0"
        return float(brentq(f, IV_LO, IV_HI, xtol=1e-7, maxiter=200)), None
    except Exception as e:                      # pragma: no cover
        return None, f"inversion failed: {type(e).__name__}"


def quote_price(bid, ask, last) -> tuple[float | None, str]:
    """Bid-ask mid where both are positive, else the last price flagged `last`."""
    b = float(bid) if bid is not None and np.isfinite(bid) else 0.0
    a = float(ask) if ask is not None and np.isfinite(ask) else 0.0
    if b > 0 and a > 0:
        return (b + a) / 2.0, "mid"
    l = float(last) if last is not None and np.isfinite(last) else 0.0
    return (l if l > 0 else None), "last"


# ── calendar ─────────────────────────────────────────────────────────────
def _cal():
    import sys
    sys.path.insert(0, str(REPO / "scripts"))
    import trading_calendar as tc
    return tc


def sessions_to_expiry(session: str | pd.Timestamp, expiry: str | pd.Timestamp) -> int:
    """Trading sessions strictly AFTER the snapshot session, through the expiry inclusive.
    The chain is pulled at 15:45 ET: the pull day's own close is minutes away and is not a
    session of variance, so it is not counted (a 25-Sept close snapshot has 5 sessions to the
    2-Oct expiry). T = sessions / 252. Applied identically to the inversion and to the
    event-variance subtraction, so the two never mix conventions."""
    tc = _cal()
    d = pd.Timestamp(session).normalize() + pd.Timedelta(days=1); e = pd.Timestamp(expiry).normalize()
    n = 0
    while d <= e:
        if tc.is_trading_day(d.strftime("%Y-%m-%d")):
            n += 1
        d += pd.Timedelta(days=1)
    return n


def sessions_between(a: str | pd.Timestamp, b: str | pd.Timestamp) -> int:
    """Trading sessions in (a, b] — the same count as sessions_to_expiry."""
    return sessions_to_expiry(a, b)


def year_frac(session, expiry) -> float:
    return sessions_to_expiry(session, expiry) / 252.0


def pick_expiry(expiries: list[str], session, target_days: int) -> str | None:
    if not expiries:
        return None
    s = pd.Timestamp(session)
    return min(expiries, key=lambda e: abs((pd.Timestamp(e) - s).days - target_days))


def interp_days(points: list[tuple[int, float]], target: int) -> float | None:
    """Linear interpolation in calendar days over (days, value) points; None outside the range."""
    pts = sorted((d, v) for d, v in points if v is not None)
    if not pts:
        return None
    lo = max([p for p in pts if p[0] <= target], default=None)
    hi = min([p for p in pts if p[0] >= target], default=None)
    if lo is None or hi is None:
        return None
    if lo[0] == hi[0]:
        return float(lo[1])
    w = (target - lo[0]) / (hi[0] - lo[0])
    return float(lo[1] + w * (hi[1] - lo[1]))


# ── prices ───────────────────────────────────────────────────────────────
def closes(tickers: list[str], session: str, years: int = 7) -> tuple[pd.DataFrame, dict]:
    """Adjusted daily closes for `tickers` through `session`: the canonical price store
    (prices_daily + sector_etfs) first; when the store ends before the session, the gap is
    filled from the provider in memory (the store itself is never modified) and the fact is
    recorded. Returns (closes, provenance)."""
    prov: dict = {"store": "data/source/prices_daily.parquet + sector_etfs.parquet", "store_through": None, "overlay": None}
    px = pd.read_parquet(SOURCE / "prices_daily.parquet")
    if "SPY_volume" in px.columns:
        px = px.drop(columns=["SPY_volume"])
    px.index = pd.to_datetime(px.index)
    se = pd.read_parquet(SOURCE / "sector_etfs.parquet"); se.index = pd.to_datetime(se.index)
    se.columns = [c.upper() for c in se.columns]
    frame = px.join(se[[c for c in se.columns if c not in px.columns]], how="outer").sort_index()
    have = [t for t in tickers if t in frame.columns]
    out = frame[have].copy()
    prov["store_through"] = str(out.index.max().date()) if len(out) else None
    sess = pd.Timestamp(session)
    missing = [t for t in tickers if t not in out.columns]
    stale = len(out) == 0 or out.index.max() < sess
    if stale or missing:
        try:
            import yfinance as yf
            want = sorted(set(tickers))
            raw = yf.download(want, start=(sess - pd.DateOffset(years=years)).strftime("%Y-%m-%d"),
                              end=(sess + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), auto_adjust=True, progress=False, threads=True)
            cl = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]].rename(columns={"Close": want[0]})
            cl.index = pd.to_datetime(cl.index).tz_localize(None) if getattr(cl.index, "tz", None) is not None else pd.to_datetime(cl.index)
            cl = cl.loc[:sess]
            merged = out.reindex(out.index.union(cl.index))
            for t in cl.columns:
                if t in merged.columns:
                    merged[t] = cl[t].reindex(merged.index).combine_first(merged[t])
                else:
                    merged[t] = cl[t].reindex(merged.index)
            out = merged.sort_index()
            prov["overlay"] = (f"provider daily closes merged in memory through {out.index.max().date()} "
                               f"(store ended {prov['store_through']}; missing in store: {missing or 'none'})")
        except Exception as e:                  # pragma: no cover
            prov["overlay"] = f"overlay failed ({type(e).__name__}); store used as is"
    return out.loc[:sess], prov


def realized_vol(series: pd.Series, n: int) -> float | None:
    r = np.log(series.dropna()).diff().dropna().iloc[-n:]
    if len(r) < max(10, int(0.8 * n)):
        return None
    return float(r.std(ddof=1) * math.sqrt(252))


# ── vintages ─────────────────────────────────────────────────────────────
def vintage_dir(session: str) -> Path:
    return VINTAGES / str(session)[:10]


def vintage_path(session: str, tk: str) -> Path:
    return vintage_dir(session) / f"{tk}.parquet"


def vintage_sessions() -> list[str]:
    if not VINTAGES.exists():
        return []
    return sorted(p.name for p in VINTAGES.iterdir() if p.is_dir() and len(p.name) == 10)


def captured_sessions() -> list[str]:
    """Vintages that count as captured (order 5-Oct-2026, 2.3): complete (their _meta.json exists) and not
    recorded missing in vintages/_index.json. The IV-rank and percentile archive uses only these."""
    idx_p = VINTAGES / "_index.json"
    missing = set()
    if idx_p.exists():
        try:
            missing = {e["date"] for e in json.loads(idx_p.read_text()).get("days", []) if e.get("status") == "missing"}
        except (ValueError, KeyError):
            missing = set()
    return [s for s in vintage_sessions() if s not in missing and (vintage_dir(s) / "_meta.json").exists()]


def load_vintage(session: str) -> dict[str, pd.DataFrame]:
    d = vintage_dir(session)
    out = {}
    if d.exists():
        for p in sorted(d.glob("*.parquet")):
            out[p.stem] = pd.read_parquet(p)
    return out


def vintage_meta(session: str) -> dict:
    p = vintage_dir(session) / "_meta.json"
    return json.loads(p.read_text()) if p.exists() else {}
