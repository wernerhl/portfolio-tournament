#!/usr/bin/env python3
"""snapshot_chains.py — the daily option-chain vintage (order 26-Sept-2026, item 1.2).

Chains are pulled ONCE daily at 15:45 ET on trading days, for every held name, every name
on the screen board's top 40, and SPY, QQQ, SMH. After-hours pulls are prohibited (bid and
ask go to zero), so a scheduled run outside 15:30–16:00 ET exits without writing. Each
snapshot is written IMMUTABLY to data/options/vintages/YYYY-MM-DD/{ticker}.parquet with the
full chain, the implied volatilities computed by the system (item 1.1 — the provider's IV
field is not stored, so nothing served can originate from it), and the quote flags. An
existing vintage file is never rewritten. The archive is the system's own implied-volatility
history and the as-published record for every options claim.

--backfill-last-session: a one-off pull for the LAST completed session from a closed market
(the provider retains the session's closing bid/ask over the weekend); the vintage is
flagged `snapshot_kind: backfill` and carries the pull time. Used once, 26-Sept-2026, to
seed the archive with the 25-Sept close for the acceptance numerics.

Usage:  python scripts/options/snapshot_chains.py [--backfill-last-session] [--tickers MU,NVDA] [--max-days 400]
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import options_common as oc
from trading_calendar import is_trading_day, last_completed_session, now_et

warnings.filterwarnings("ignore")
WINDOW_ET = ((15, 30), (16, 0))     # the snapshot window


def log(m: str) -> None:
    print(f"[snapshot_chains] {m}", flush=True)


def in_window(now) -> bool:
    hm = (now.hour, now.minute)
    return WINDOW_ET[0] <= hm < WINDOW_ET[1]


def _f(v) -> float:
    """Provider numerics arrive as NaN for untraded strikes; store 0.0, never NaN."""
    try:
        x = float(v)
        return x if np.isfinite(x) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _i(v) -> int:
    try:
        x = float(v)
        return int(x) if np.isfinite(x) else 0
    except (TypeError, ValueError):
        return 0


def live_spot(tk: str) -> tuple[float | None, str]:
    import yfinance as yf
    try:
        h = yf.Ticker(tk).history(period="1d", interval="1m", auto_adjust=False)
        c = h["Close"].dropna() if h is not None and not h.empty else None
        if c is not None and len(c):
            return float(c.iloc[-1]), "provider 1-minute tape"
    except Exception:
        pass
    return None, "unavailable"


def pull_chain(tk: str, session: str, spot: float, r: float, q: float, max_days: int) -> tuple[pd.DataFrame, dict]:
    import yfinance as yf
    t = yf.Ticker(tk)
    try:
        expiries = list(t.options)
    except Exception as e:
        return pd.DataFrame(), {"error": f"expiries: {type(e).__name__}"}
    sess = pd.Timestamp(session)
    expiries = [e for e in expiries if 0 < (pd.Timestamp(e) - sess).days <= max_days]
    rows = []
    n_fail = 0
    for e in expiries:
        oc_ = None
        for attempt in range(2):
            try:
                oc_ = t.option_chain(e); break
            except Exception:
                time.sleep(0.8)
        if oc_ is None:
            n_fail += 1; continue
        n = oc.sessions_to_expiry(session, e); T = n / 252.0
        for cp, df in (("c", oc_.calls), ("p", oc_.puts)):
            if df is None or df.empty:
                continue
            for rec in df.itertuples(index=False):
                K = float(rec.strike)
                bid, ask, last = _f(getattr(rec, "bid", None)), _f(getattr(rec, "ask", None)), _f(getattr(rec, "lastPrice", None))
                px, kind = oc.quote_price(bid, ask, last)
                iv, why = oc.implied_vol(px, spot, K, T, r, q, cp)
                rows.append({
                    "ticker": tk, "expiry": e, "cp": cp, "strike": K,
                    "bid": bid, "ask": ask, "last": last,
                    "quote": kind, "price_used": px,
                    "open_interest": _i(getattr(rec, "openInterest", None)), "volume": _i(getattr(rec, "volume", None)),
                    "iv": iv, "iv_reason": why,
                    "delta": oc.bs_delta(spot, K, T, r, q, iv, cp) if iv else None,
                    "gamma": oc.bs_gamma(spot, K, T, r, q, iv) if iv else None,
                    "sessions_to_expiry": n, "T": T, "spot": spot, "r": r, "q": q,
                    "last_trade": str(getattr(rec, "lastTradeDate", ""))[:19],
                })
        time.sleep(0.15)
    df = pd.DataFrame(rows)
    return df, {"n_expiries": len(expiries) - n_fail, "n_expiry_failures": n_fail}


def front_live_share(df: pd.DataFrame, session: str) -> float | None:
    """Share of strikes at the FRONT tenor (nearest 30 days) with a live bid-ask quote."""
    if df.empty:
        return None
    front = oc.pick_expiry(sorted(df.expiry.unique()), session, oc.FRONT_DAYS)
    f = df[df.expiry == front]
    return float((f.quote == "mid").mean()) if len(f) else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill-last-session", action="store_true")
    ap.add_argument("--tickers", default="")
    ap.add_argument("--max-days", type=int, default=400)
    args = ap.parse_args()
    now = now_et()
    if args.backfill_last_session:
        session = last_completed_session()
        kind = "backfill"
    else:
        d = now.strftime("%Y-%m-%d")
        if not is_trading_day(d):
            log(f"market closed ({d}); nothing to do"); return 0
        if not in_window(now):
            log(f"outside the 15:30–16:00 ET snapshot window ({now.strftime('%H:%M')} ET); after-hours pulls are prohibited — nothing written")
            return 0
        session = d; kind = "scheduled"
    vdir = oc.vintage_dir(session)
    vdir.mkdir(parents=True, exist_ok=True)
    r, r_date = oc.risk_free()
    uni = oc.analyzed_universe()
    tks = [t.strip().upper() for t in args.tickers.split(",") if t.strip()] or list(uni)
    cl, prov = oc.closes(tks, session)
    meta_p = vdir / "_meta.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {
        "session": session, "snapshot_kind": kind, "pulled_at": now.isoformat(timespec="seconds"),
        "risk_free": r, "risk_free_date": r_date, "iv_method": "Black-Scholes inversion, Brent on [0.01, 5.0]; provider IV field not stored",
        "quote_rule": "bid-ask mid where both positive, else last (flagged)", "closes_provenance": prov, "tickers": {}}
    written, skipped, failed = [], [], []
    for tk in tks:
        out = oc.vintage_path(session, tk)
        if out.exists():
            skipped.append(tk); continue                       # immutable: never rewritten
        if kind == "scheduled":
            spot, spot_src = live_spot(tk)
            if spot is None and tk in cl.columns and cl[tk].dropna().size:
                spot, spot_src = float(cl[tk].dropna().iloc[-1]), "last close (tape unavailable)"
        else:
            spot, spot_src = (float(cl[tk].dropna().iloc[-1]), f"{session} close") if tk in cl.columns and cl[tk].dropna().size else (None, "unavailable")
        if spot is None:
            failed.append(f"{tk}: no spot"); continue
        q, q_src = oc.dividend_yield(tk)
        df, info = pull_chain(tk, session, spot, r, q, args.max_days)
        if df.empty:
            failed.append(f"{tk}: {info.get('error', 'empty chain')}"); continue
        df.to_parquet(out, index=False)
        sha = hashlib.sha256(out.read_bytes()).hexdigest()      # the immutability record the referee re-checks
        live_share = front_live_share(df, session)
        n_iv = int(df.iv.notna().sum())
        meta["tickers"][tk] = {"roles": uni.get(tk, []), "spot": spot, "spot_source": spot_src, "q": q, "q_source": q_src,
                               "n_expiries": info["n_expiries"], "n_strikes": int(len(df)), "n_iv": n_iv,
                               "front_live_quote_share": live_share, "expiries": sorted(df.expiry.unique().tolist()),
                               "sha256": sha, "written_at": now_et().isoformat(timespec="seconds")}
        written.append(tk)
        log(f"  {tk:5} spot {spot:9.2f} ({spot_src}) · {info['n_expiries']} expiries · {len(df)} strikes · iv {n_iv} · front live-quote {live_share if live_share is None else round(live_share, 2)}")
    meta_p.write_text(json.dumps(meta, indent=2))
    log(f"vintage {session} ({kind}): wrote {len(written)}, immutable-skipped {len(skipped)}, failed {len(failed)} → {vdir.relative_to(oc.REPO)}")
    for f_ in failed:
        log(f"  FAILED {f_}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
