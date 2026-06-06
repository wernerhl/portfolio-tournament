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


def assess_intraday(px: dict) -> dict:
    """Run the shock + complacency rules and assemble the dashboard payload."""
    spx_chg = _pct(px.get("spx", {}).get("last"),  px.get("spx", {}).get("prior_close")) or 0.0
    vix_now = px.get("vix", {}).get("last")
    vix_pri = px.get("vix", {}).get("prior_close")
    vix_chg = _pct(vix_now, vix_pri) or 0.0
    vix3m   = px.get("vix3m", {}).get("last")
    skew    = px.get("skew", {}).get("last")
    backwardation = bool(vix_now and vix3m and vix_now > vix3m)

    hyg_lqd_chg = 0.0
    if px.get("hyg") and px.get("lqd"):
        r_now = px["hyg"]["last"] / px["lqd"]["last"] if px["lqd"]["last"] else None
        r_pri = px["hyg"]["prior_close"] / px["lqd"]["prior_close"] if px["lqd"]["prior_close"] else None
        if r_now and r_pri:
            hyg_lqd_chg = (r_now / r_pri - 1) * 100.0

    # ── SHOCK triggers ───────────────────────────────────────────────────
    reasons = []
    if vix_chg > 15:           reasons.append(f"VIX +{vix_chg:.0f}%")
    if spx_chg < -1.5:         reasons.append(f"SPX {spx_chg:.1f}%")
    if backwardation:          reasons.append(f"VIX term backwardated (VIX {vix_now:.1f} > VIX3M {vix3m:.1f})")
    if hyg_lqd_chg < -1.0:     reasons.append(f"HY credit {hyg_lqd_chg:.1f}%")
    shock_active = len(reasons) > 0

    # ── COMPLACENCY (tail priced + protection cheap) ─────────────────────
    complacency_active = bool(skew and vix_now and skew > 140 and vix_now < 17)
    complacency_reason = (f"SKEW {skew:.0f} > 140 and VIX {vix_now:.1f} < 17 — "
                          f"tail priced, protection cheap, market unhedged"
                          ) if complacency_active else None

    return {
        "timestamp":        dt.datetime.utcnow().isoformat(timespec="seconds"),
        "spx_change_pct":   round(spx_chg, 2),
        "vix_now":          round(vix_now, 2) if vix_now is not None else None,
        "vix_prior":        round(vix_pri, 2) if vix_pri is not None else None,
        "vix_change_pct":   round(vix_chg, 1),
        "vix3m":            round(vix3m, 2) if vix3m is not None else None,
        "backwardation":    backwardation,
        "skew":             round(skew, 1) if skew is not None else None,
        "hyg_lqd_change_pct": round(hyg_lqd_chg, 2),
        "shock_active":     shock_active,
        "shock_reasons":    reasons,
        "complacency_active": complacency_active,
        "complacency_reason": complacency_reason,
        "prices":           px,
    }


def main():
    print("Fetching intraday snapshot...")
    px = fetch_intraday()
    print(f"  got {len(px)}/{len(TICKERS)} channels")
    state = assess_intraday(px)
    out = DATA / "intraday.json"
    DATA.mkdir(exist_ok=True)
    with open(out, "w") as f:
        json.dump(state, f, indent=2, default=str, allow_nan=False)
    print(f"  SPX {state['spx_change_pct']:+.2f}%  ·  "
          f"VIX {state['vix_now']} ({state['vix_change_pct']:+.1f}%)  ·  "
          f"SKEW {state['skew']}")
    if state["shock_active"]:
        print(f"  *** SHOCK ACTIVE: {', '.join(state['shock_reasons'])}")
    if state["complacency_active"]:
        print(f"  *** COMPLACENCY: {state['complacency_reason']}")
    print(f"  saved → {out}")


if __name__ == "__main__":
    main()
