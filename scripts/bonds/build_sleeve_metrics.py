#!/usr/bin/env python3
"""build_sleeve_metrics.py — data/bonds/sleeve_metrics.json (order 1.3).

Per sleeve: distribution yield, effective duration (static category table, source noted),
yield-per-unit-of-duration (the module's primary carry metric — the fixed-income analogue
of the risk-contribution panel), 126-session annualized volatility, 1-year total return,
and correlation to the equity book. Correlation and volatility use the SAME 126-session
window and the SAME computation the book panel uses (book_analytics), on the equity book
read from holdings.json — the only holdings source.

Descriptive: no buy or sell instruction, no rate forecast.
"""
from __future__ import annotations
import json, sys
from datetime import datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))                       # bonds_common
sys.path.insert(0, str(HERE.parent))                # book_analytics
import bonds_common as bc
import book_analytics as ba
try:
    from trading_calendar import now_et
except Exception:                       # pragma: no cover
    def now_et():
        return datetime.now().astimezone()


def log(m: str) -> None:
    print(m, flush=True)


def equity_book(live: dict | None = None):
    """(equity_$, w_eq {ticker: share_of_equity}, holdings_as_of, n_positions) from holdings.json.
    In intraday mode the equity dollar figure uses the live tape; the weights and the correlation
    window below stay on the settled closes."""
    live = live or {}
    h = ba.load_holdings()
    prices = ba.load_prices()
    last = prices.ffill().iloc[-1]
    vals = {}
    for pos in h.get("holdings", []):
        tk = str(pos.get("ticker", "")).upper()
        sh = pos.get("shares") or 0
        if sh > 0 and tk in prices.columns and pd.notna(last.get(tk)):
            px = float(live[tk]) if tk in live and live[tk] else float(last[tk])
            vals[tk] = float(sh) * px
    equity = sum(vals.values())
    w_eq = {tk: v / equity for tk, v in vals.items()} if equity else {}
    return equity, w_eq, h.get("as_of"), len(vals)


def build(live: dict | None = None, intraday: bool = False) -> dict:
    uni = bc.load_sleeve_universe()["sleeves"]
    yj = bc.load_sleeve_yields()
    ys = yj.get("yields", {})
    sp = bc.load_sleeve_prices()
    srets = ba.daily_returns(sp)

    equity, w_eq, holdings_as_of, n_pos = equity_book(live)
    rets = ba.daily_returns(ba.load_prices())
    eq_series = ba.book_series(rets, w_eq) if w_eq else pd.Series(dtype=float)
    eq_win = eq_series.iloc[-bc.WINDOW:] if len(eq_series) else pd.Series(dtype=float)

    warnings: list[str] = []
    rows = []
    for s in uni:
        tk = s["ticker"]
        y = ys.get(tk)                                   # fraction or None
        dur = bc.EFF_DURATION.get(tk)
        near_zero = dur is not None and dur < bc.NEAR_ZERO_DURATION
        ypd = round(y / dur, 4) if (y is not None and dur and dur > 0) else None

        sr = srets[tk].dropna() if tk in srets.columns else pd.Series(dtype=float)
        vol = ba.ann_vol(sr.iloc[-bc.WINDOW:], min_obs=bc.MIN_OBS) if len(sr) else None
        # 1-year total return (auto-adjusted close → dividends reinvested)
        p = sp[tk].dropna() if tk in sp.columns else pd.Series(dtype=float)
        ret_1y = round(float(p.iloc[-1] / p.iloc[-1 - bc.YEAR_SESSIONS] - 1), 4) if len(p) > bc.YEAR_SESSIONS else None
        cor = ba.corr(eq_win, sr) if len(eq_win) and len(sr) else {"corr": None, "n_obs": 0}

        if y is None:
            warnings.append(f"{tk}: distribution yield unavailable")
        rows.append({
            "ticker": tk, "asset_class": s["asset_class"], "role": s["role"],
            "distribution_yield": y,
            "distribution_yield_pct": round(y * 100, 2) if y is not None else None,
            "yield_available": y is not None,
            "effective_duration": dur,
            "yield_per_duration": ypd,
            "near_zero_duration": near_zero,
            "vol_126_ann": round(vol, 4) if vol is not None else None,
            "return_1y": ret_1y,
            "correlation_to_book": (round(cor["corr"], 4) if cor.get("corr") is not None else None),
            "corr_n_obs": cor.get("n_obs", 0),
            "priced_through": str(p.index.max().date()) if len(p) else None,
        })

    session = str(sp.index.max().date())
    now_iso = (now_et() if intraday else datetime.now().astimezone()).isoformat(timespec="seconds")
    return {
        "cadence": "intraday" if intraday else "daily",
        "mode": "intraday" if intraday else "close",
        "intraday": bool(intraday),
        "intraday_as_of": now_iso if intraday else None,
        "session_date": session,
        "as_of": datetime.now().astimezone().date().isoformat(),
        "computed_at": now_iso,
        "level": "sleeve",
        "window": bc.WINDOW,
        "duration_source": bc.DURATION_SOURCE,
        "yield_source": {"field": yj.get("field"), "provider": yj.get("provider"),
                         "retrieved_at": yj.get("retrieved_at")},
        "book": {"equity": round(equity, 2), "holdings_as_of": holdings_as_of, "n_positions": n_pos,
                 "correlation_window": bc.WINDOW, "correlation_min_obs": bc.MIN_OBS,
                 "note": "correlation to the current equity book (constant current equity weights), same window and computation as the book panel"},
        "sleeves": rows,
        "warnings": warnings,
        "note": "descriptive; yield-per-duration is the primary carry metric; no buy or sell instruction, no rate forecast.",
    }


def main() -> int:
    intraday = "--intraday" in sys.argv
    live = {}
    if intraday:
        h = ba.load_holdings()
        held = [str(x["ticker"]).upper() for x in h.get("holdings", []) if (x.get("shares") or 0) > 0]
        live = ba.fetch_live_prices(held)
        log(f"intraday: fetched {len(live)}/{len(held)} live held prices")
    payload = build(live=live, intraday=intraday)
    out = bc.BONDS / "sleeve_metrics.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    n = len(payload["sleeves"])
    ny = sum(1 for r in payload["sleeves"] if r["yield_available"])
    nc = sum(1 for r in payload["sleeves"] if r["correlation_to_book"] is not None)
    log(f"saved sleeve_metrics.json ({n} sleeves; {ny} yields; {nc} correlations; equity ${payload['book']['equity']:,.0f}; session {payload['session_date']})")
    if "--print" in sys.argv:
        for r in payload["sleeves"]:
            log(f"  {r['ticker']:5} y={r['distribution_yield_pct']}%  dur={r['effective_duration']}  y/dur={r['yield_per_duration']}  "
                f"vol={r['vol_126_ann']}  1y={r['return_1y']}  corr={r['correlation_to_book']} (n={r['corr_n_obs']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
