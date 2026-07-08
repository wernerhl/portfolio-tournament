"""
compute_intraday.py — runs every 30 min during the market session.

Fast/free intraday channels only (yfinance 1-minute bars over a 2-day window):
  SPX, VIX, VIX3M, VVIX, SKEW, HYG, LQD, GLD, TLT, DXY.

Writes data/intraday.json with:
  - latest prices + change vs prior session close
  - shock_active flag if any of (VIX +15%, SPX -1.5%, VIX backwardation, HY -1%)
  - complacency check (SKEW>140 + VIX<17 + low intraday vol)
  - timestamp (UTC) so the dashboard can show staleness age

This does NOT touch macro indicators (FRED) — they update at most daily anyway.
The dashboard reads this and overlays a SHOCK or STALE banner above the regime
gauge whenever the end-of-day snapshot diverges from the live tape.
"""
from __future__ import annotations
import json, sys, datetime as dt
from pathlib import Path

import numpy as np
import yfinance as yf

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"

TICKERS = {
    "spx":   "^GSPC",
    "vix":   "^VIX",
    "vix3m": "^VIX3M",
    "vvix":  "^VVIX",
    "skew":  "^SKEW",
    "hyg":   "HYG",
    "lqd":   "LQD",
    "gld":   "GC=F",
    "tlt":   "TLT",
    "dxy":   "DX-Y.NYB",
    # Equity sector proxies for the idiosyncratic_equity overlay
    "smh":   "SMH",
    "soxx":  "SOXX",
    # ──────────────────────────────────────────────────────────────────
    # Same-day 2Y rate proxies — FRED DGS2 publishes T+1 around macro
    # releases so the cash-2Y move is invisible on the event day itself.
    # Two same-day proxies, captured as prior settle/close → current:
    #   ZT=F  CME 2-Year T-Note futures — trades through the 08:30 ET
    #         release. Standard proxy for event-day Δ2Y.
    #   SHY   iShares 1-3y Treasury ETF — duration ≈ 1.85y; Δyield
    #         derived via −price_return / duration × 10000 bps.
    # vol_regime prefers ZT then SHY then FRED (T+1 reconciliation only).
    # ──────────────────────────────────────────────────────────────────
    "zt":    "ZT=F",
    "shy":   "SHY",
}


def fetch_intraday() -> dict:
    """Snapshot last 1-min bars over 2 sessions. Returns {key: {last, prior_close}}."""
    out = {}
    for key, tk in TICKERS.items():
        try:
            d = yf.Ticker(tk).history(period="2d", interval="1m", auto_adjust=False)
            if d is None or d.empty:
                continue
            close = d["Close"].dropna()
            if close.empty:
                continue
            last = float(close.iloc[-1])
            # Find the prior session: earliest bar from a different calendar date
            try:
                last_date = close.index[-1].date()
                prior_mask = [t.date() != last_date for t in close.index]
                if any(prior_mask):
                    prior_close = float(close[prior_mask].iloc[-1])
                else:
                    prior_close = float(close.iloc[0])
            except Exception:
                prior_close = float(close.iloc[0])
            out[key] = {"last": round(last, 4), "prior_close": round(prior_close, 4)}
        except Exception as e:
            print(f"  warn {key} ({tk}): {e}", file=sys.stderr)
    return out


def _pct(now, prior):
    if now is None or prior in (None, 0):
        return None
    return (now / prior - 1.0) * 100.0


# HYG duration ≈ 3.5y vs TLT ≈ 17y → return beta ≈ 0.25 for duration hedging.
# Documented estimate per JULY AUDIT FIX 6a; revisit if HYG duration drifts.
HYG_TLT_DURATION_BETA = 0.25


def _load_canonical() -> dict:
    """Canonical vol-complex close (written by refresh_data after the close)."""
    for name in ("vol_close_canonical.json", "vol_canonical_close.json"):
        p = Path(__file__).resolve().parent.parent / "data" / name
        if p.exists():
            try:
                return json.load(open(p))
            except Exception:
                pass
    return {}


def assess_intraday(px: dict) -> dict:
    """Shock + complacency rules — NULL-GUARDED (JULY AUDIT FIX 2).
    A safety check must NEVER return boolean-false on missing input; missing
    input marks the check IMPAIRED and is surfaced loudly."""
    impaired = []

    spx_chg = _pct(px.get("spx", {}).get("last"), px.get("spx", {}).get("prior_close"))
    if spx_chg is None: impaired.append("spx_move")
    vix_now = px.get("vix", {}).get("last")
    vix_pri = px.get("vix", {}).get("prior_close")
    vix_chg = _pct(vix_now, vix_pri)
    if vix_chg is None: impaired.append("vix_spike")
    vix3m = px.get("vix3m", {}).get("last")
    if vix_now is None or vix3m is None:
        backwardation = None; impaired.append("backwardation")
    else:
        backwardation = bool(vix_now > vix3m)

    # Credit leg — duration-aware (JULY AUDIT FIX 6a): raw HYG/LQD relative
    # change is duration-confounded (LQD ~2x HYG duration → a rates-up day
    # reads as credit "improvement"). Use HYG return minus beta-matched TLT.
    credit_chg = None
    hyg, tlt = px.get("hyg") or {}, px.get("tlt") or {}
    hyg_ret = _pct(hyg.get("last"), hyg.get("prior_close"))
    tlt_ret = _pct(tlt.get("last"), tlt.get("prior_close"))
    if hyg_ret is not None and tlt_ret is not None:
        credit_chg = hyg_ret - HYG_TLT_DURATION_BETA * tlt_ret
    else:
        impaired.append("credit")

    # ── SHOCK triggers (evaluated legs only; impaired legs listed) ───────
    reasons = []
    if vix_chg is not None and vix_chg > 15:      reasons.append(f"VIX +{vix_chg:.0f}%")
    if spx_chg is not None and spx_chg < -1.5:    reasons.append(f"SPX {spx_chg:.1f}%")
    if backwardation:                              reasons.append(f"VIX term backwardated (VIX {vix_now:.1f} > VIX3M {vix3m:.1f})")
    if credit_chg is not None and credit_chg < -1.0:
        reasons.append(f"HY credit (duration-adj) {credit_chg:.1f}%")
    shock_active = len(reasons) > 0

    # ── COMPLACENCY — HIGH SKEW (>140) + LOW VIX (<17) ──────────────────
    # (JULY AUDIT FIX 2: definition restored; June's low-SKEW variant
    # reversed. Same definition as compute_regime_v2 so the two flags can
    # never disagree.) Yahoo's intraday ^SKEW feed is unreliable — fall back
    # to the canonical EOD close before declaring the check impaired.
    skew = px.get("skew", {}).get("last")
    skew_source = "intraday"
    if skew is None:
        canon = _load_canonical()
        if canon.get("skew") is not None:
            skew = float(canon["skew"]); skew_source = f"canonical close ({canon.get('date')})"
    if skew is None or vix_now is None:
        complacency_active = "impaired"
        missing = [n for n, v in (("SKEW", skew), ("VIX", vix_now)) if v is None]
        complacency_reason = f"COMPLACENCY CHECK IMPAIRED — {'/'.join(missing)} feed unavailable"
        impaired.append("complacency")
    else:
        complacency_active = bool(skew > 140 and vix_now < 17)
        complacency_reason = (f"SKEW {skew:.0f} > 140 ({skew_source}) and VIX {vix_now:.1f} < 17 — "
                              f"tail priced, spot fear absent — market complacent"
                              ) if complacency_active else None

    return {
        "timestamp":        dt.datetime.utcnow().isoformat(timespec="seconds"),
        "spx_change_pct":   round(spx_chg, 2) if spx_chg is not None else None,
        "vix_now":          round(vix_now, 2) if vix_now is not None else None,
        "vix_prior":        round(vix_pri, 2) if vix_pri is not None else None,
        "vix_change_pct":   round(vix_chg, 1) if vix_chg is not None else None,
        "vix3m":            round(vix3m, 2) if vix3m is not None else None,
        "backwardation":    backwardation,
        "skew":             round(skew, 1) if skew is not None else None,
        "skew_source":      skew_source if skew is not None else None,
        "credit_change_dur_adj_pct": round(credit_chg, 2) if credit_chg is not None else None,
        "credit_beta_note": f"HYG return − {HYG_TLT_DURATION_BETA}×TLT return (duration-matched)",
        "shock_active":     shock_active,
        "shock_reasons":    reasons,
        "impaired_checks":  impaired,
        "complacency_active": complacency_active,
        "complacency_reason": complacency_reason,
        "prices":           px,
    }


def main():
    print("Fetching intraday snapshot...")
    px = fetch_intraday()
    print(f"  got {len(px)}/{len(TICKERS)} channels")
    state = assess_intraday(px)

    # ── Post-close reconcile to the canonical close (JULY AUDIT FIX 3b) ──
    # After the close, intraday's last 1-minute tick and the canonical daily
    # bar both claim to be "the close" and disagree by a few cents. The
    # canonical file (one fetcher, pinned provider) wins: overwrite the
    # close-like fields so both artifacts agree to the cent.
    et = dt.datetime.utcnow() - dt.timedelta(hours=4)
    after_close = et.hour > 16 or (et.hour == 16 and et.minute >= 20)
    canon = _load_canonical()
    if after_close and canon.get("date") == et.strftime("%Y-%m-%d"):
        for key_state, key_px, key_c in [("vix_now", "vix", "vix"), (None, "vix3m", "vix3m"),
                                          (None, "vvix", "vvix"), (None, "vix1d", "vix1d"),
                                          ("skew", "skew", "skew")]:
            cv = canon.get(key_c)
            if cv is None: continue
            if key_px in state.get("prices", {}):
                state["prices"][key_px]["last"] = cv
            if key_state and state.get(key_state) is not None:
                state[key_state] = cv
        if canon.get("vix3m") is not None:
            state["vix3m"] = canon["vix3m"]
        state["reconciled_to_canonical"] = canon.get("date")
        print(f"  post-close: reconciled vol-complex fields to canonical close {canon.get('date')}")

    out = DATA / "intraday.json"
    DATA.mkdir(exist_ok=True)
    with open(out, "w") as f:
        json.dump(state, f, indent=2, default=str, allow_nan=False)
    _f = lambda v, fmt: (fmt % v) if v is not None else "—"
    print(f"  SPX {_f(state['spx_change_pct'], '%+.2f%%')}  ·  "
          f"VIX {state['vix_now']} ({_f(state['vix_change_pct'], '%+.1f%%')})  ·  "
          f"SKEW {state['skew']} ({state.get('skew_source')})")
    if state["shock_active"]:
        print(f"  *** SHOCK ACTIVE: {', '.join(state['shock_reasons'])}")
    if state["complacency_active"] is True:
        print(f"  *** COMPLACENCY: {state['complacency_reason']}")
    elif state["complacency_active"] == "impaired":
        print(f"  *** {state['complacency_reason']}", file=sys.stderr)
    if state["impaired_checks"]:
        print(f"  impaired checks: {state['impaired_checks']}", file=sys.stderr)
    print(f"  saved → {out}")


if __name__ == "__main__":
    main()
