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

One writer per day (order 5-Oct-2026, item 2.2). The workflow has no concurrency group (GitHub keeps one
pending run per group and cancels the rest). Instead, with --publish:
  1. `git fetch origin main`; if data/options/vintages/{today}/_meta.json exists there, exit with the
     notice "already written" and write nothing;
  2. pull every chain into a temporary folder (vintages/.incoming-*), then move it into place;
  3. commit and push. If the push is rejected and origin/main now holds today's vintage, another run
     pushed first: discard the local vintage, exit with the notice, and do not retry. A rejection caused
     by an unrelated commit (another bot) is rebased and pushed again (the paths cannot conflict).
The pull stops at 16:00 ET; tickers not reached are recorded as failed ("window closed").
Missed days are never backfilled with after-hours data: the one-off --backfill-last-session mode that
seeded 25 September (flagged `snapshot_kind: backfill`) is removed.

Outcome (stdout notice, and `outcome=` in $GITHUB_OUTPUT): written | already_written | push_conflict |
outside_window | market_closed | provider_error | push_failed.

Usage:  python scripts/options/snapshot_chains.py [--publish] [--tickers MU,NVDA] [--max-days 400]
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import subprocess
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


def set_outcome(outcome: str, note: str) -> None:
    kind = "warning" if outcome in ("provider_error", "push_failed") else "notice"
    print(f"::{kind}::options snapshot: {outcome} — {note}", flush=True)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"outcome={outcome}\n")


def git(*args, check=False) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=oc.REPO, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r


def origin_has(session: str) -> bool:
    """True when origin/main already holds the session's vintage (its _meta.json)."""
    return git("cat-file", "-e", f"origin/main:data/options/vintages/{session}/_meta.json").returncode == 0


def publish(session: str, pulled_hm: str) -> str:
    """Commit the moved vintage and push it; one writer per day (see the module docstring)."""
    rel = f"data/options/vintages/{session}"
    trig = os.environ.get("SNAPSHOT_TRIGGER", "manual")
    git("add", rel, check=True)
    git("-c", "user.name=Tournament Bot", "-c", "user.email=bot@tournament", "commit", "-q", "-m",
        f"🧾 options vintage {session} · pulled {pulled_hm} ET · {trig}", check=True)
    # F6 (7-Oct-2026): six attempts with a longer backoff (the 6- and 7-Oct vintages were pulled and then lost to
    # push_failed after three quick attempts); a rebase that fails on a shallow history is retried after unshallowing
    for attempt in range(1, 7):
        if git("push", "origin", "HEAD:main").returncode == 0:
            return "written"
        git("fetch", "-q", "origin", "main")
        if origin_has(session):
            git("reset", "-q", "--hard", "origin/main")               # discard the local vintage
            return "push_conflict"
        if git("rebase", "-q", "origin/main").returncode != 0:          # an unrelated bot commit: replay ours on top
            git("rebase", "--abort")
            git("fetch", "-q", "--unshallow", "origin", "main")
            if git("rebase", "-q", "origin/main").returncode != 0:
                git("rebase", "--abort")
                log(f"rebase onto origin/main failed (attempt {attempt}); {git('status', '--short').stdout.strip()[:200]}")
                if attempt == 6:
                    return "push_failed"
        time.sleep(5 * attempt)
    return "push_failed"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true", help="the one-writer guard, commit and push (CI)")
    ap.add_argument("--tickers", default="")
    ap.add_argument("--max-days", type=int, default=400)
    args = ap.parse_args()
    now = now_et()
    d = now.strftime("%Y-%m-%d")
    if not is_trading_day(d):
        set_outcome("market_closed", f"market closed ({d}); nothing to do"); return 0
    if not in_window(now):
        set_outcome("outside_window", f"outside the 15:30–16:00 ET snapshot window ({now.strftime('%H:%M')} ET); "
                    "after-hours pulls are prohibited, nothing written"); return 0
    session, kind = d, "scheduled"
    final = oc.vintage_dir(session)
    if args.publish:
        git("fetch", "-q", "origin", "main")
        if origin_has(session):
            set_outcome("already_written", f"the {session} vintage is already written on origin/main; nothing pulled"); return 0
    if (final / "_meta.json").exists():
        set_outcome("already_written", f"the {session} vintage is already written ({final.relative_to(oc.REPO)}); nothing pulled"); return 0
    tmp = oc.VINTAGES / f".incoming-{session}-{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    r, r_date = oc.risk_free()
    uni = oc.analyzed_universe()
    tks = [t.strip().upper() for t in args.tickers.split(",") if t.strip()] or list(uni)
    cl, prov = oc.closes(tks, session)
    meta = {"session": session, "snapshot_kind": kind, "pulled_at": now.isoformat(timespec="seconds"),
            "trigger": os.environ.get("SNAPSHOT_TRIGGER", "manual"),
            "risk_free": r, "risk_free_date": r_date, "iv_method": "Black-Scholes inversion, Brent on [0.01, 5.0]; provider IV field not stored",
            "quote_rule": "bid-ask mid where both positive, else last (flagged)", "closes_provenance": prov, "tickers": {}}
    written, failed = [], []
    for i, tk in enumerate(tks):
        if not in_window(now_et()):
            failed += [f"{t}: window closed" for t in tks[i:]]
            log(f"16:00 ET reached: {len(tks) - i} tickers not pulled")
            break
        spot, spot_src = live_spot(tk)
        if spot is None and tk in cl.columns and cl[tk].dropna().size:
            spot, spot_src = float(cl[tk].dropna().iloc[-1]), "last close (tape unavailable)"
        if spot is None:
            failed.append(f"{tk}: no spot"); continue
        q, q_src = oc.dividend_yield(tk)
        df, info = pull_chain(tk, session, spot, r, q, args.max_days)
        if df.empty:
            failed.append(f"{tk}: {info.get('error', 'empty chain')}"); continue
        out = tmp / f"{tk}.parquet"
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
    for f_ in failed:
        log(f"  FAILED {f_}")
    if not written:
        shutil.rmtree(tmp, ignore_errors=True)
        set_outcome("provider_error", f"no chain pulled for {session} ({len(failed)} failures); nothing written"); return 1
    meta["completed_at"] = now_et().isoformat(timespec="seconds")
    meta["failed"] = failed
    (tmp / "_meta.json").write_text(json.dumps(meta, indent=2))       # written last: its presence marks the vintage complete
    if final.exists():
        shutil.rmtree(tmp, ignore_errors=True)
        set_outcome("already_written", f"{final.relative_to(oc.REPO)} appeared during the pull; the local pull is discarded"); return 0
    os.rename(tmp, final)
    log(f"vintage {session}: wrote {len(written)}, failed {len(failed)} → {final.relative_to(oc.REPO)}")
    if not args.publish:
        set_outcome("written", f"{session} written locally (no --publish: not committed)"); return 0
    outcome = publish(session, now.strftime("%H:%M"))
    notes = {"written": f"{session} vintage written and pushed ({len(written)} tickers)",
             "push_conflict": f"already written: another run pushed the {session} vintage first; the local vintage is discarded and the push is not retried",
             "push_failed": f"the {session} vintage could not be pushed after three attempts"}
    set_outcome(outcome, notes[outcome])
    return 1 if outcome == "push_failed" else 0


if __name__ == "__main__":
    sys.exit(main())
