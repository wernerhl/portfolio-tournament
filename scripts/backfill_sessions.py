#!/usr/bin/env python3
"""backfill_sessions.py — missing sessions in the tournament history, filled under the
as-published convention (Tournament Audit and Execution Order of 30 September 2026, 4.5 / T1).

Twelve sessions were absent from data/tournament.json (24 and 26 June, 27 August, and 16–28
September 2026: nightly runs that were rejected or skipped). A row for a missing session is
what the system would have published that evening: every tier's shares as they stood in the
previous row, valued at the session's closes from the price store; cash compounded at the
previous row's EFFR; the regime reading from the revised series (no published vintage exists
for a session the nightly missed — the row says so); the label from the hysteresis corridor
off the previous row's label; benchmarks anchored at inception. Each row carries
`backfilled: true`, `backfill_date` and `backfill_note`. Nothing already published is altered.

compute_nav.py calls `backfill_missing()` before it appends the session's row, so a future
gap heals on the next successful nightly; the referee reports any remaining gap as CRITICAL.

Usage:  python scripts/backfill_sessions.py [--dry-run] [--print]
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATA = REPO / "data"
sys.path.insert(0, str(HERE))
from trading_calendar import is_trading_day, now_et  # noqa: E402
from regime_label import label_with_corridor  # noqa: E402
import strat_tier  # noqa: E402  (J6: the STRATIFIED paper tier is carried forward, never seeded, by a backfill)

TIERS = ["1_cap_pres", "2_balanced", "3_aggressive", "4_tactical"]


def log(m: str) -> None:
    print(f"[backfill_sessions] {m}", flush=True)


def missing_sessions(history: list, through: str | None = None) -> list[str]:
    """Trading sessions absent between the first row and `through` (default: the last row)."""
    if not history:
        return []
    have = {h["date"] for h in history}
    d = date.fromisoformat(history[0]["date"])
    end = date.fromisoformat(through or history[-1]["date"])
    out = []
    while d <= end:
        s = d.isoformat()
        if is_trading_day(s) and s not in have:
            out.append(s)
        d += timedelta(days=1)
    return out


class Closes:
    """Closes on a session from the served stores (tier names, SPY/QQQ, TLT) plus SSO from the
    provider (no store carries it). A missing close falls back to the last available on or
    before the session and is noted."""

    def __init__(self):
        self.px = pd.read_parquet(DATA / "source" / "prices_daily.parquet"); self.px.index = pd.to_datetime(self.px.index)
        self.etf = pd.read_parquet(DATA / "source" / "sector_etfs.parquet"); self.etf.index = pd.to_datetime(self.etf.index)
        vp = DATA / "source" / "vol_indicators.parquet"
        self.vol = pd.read_parquet(vp) if vp.exists() else None
        if self.vol is not None:
            self.vol.index = pd.to_datetime(self.vol.index)
        self._sso = None
        self._prov: dict[str, pd.Series] = {}
        self.notes: list[str] = []

    def _last_on_or_before(self, s: pd.Series, d: str, label: str):
        s = s.dropna(); s = s[s.index <= pd.Timestamp(d)]
        if s.empty:
            return None
        if str(s.index[-1].date()) != d:
            self.notes.append(f"{label}: no close on {d}; last available {str(s.index[-1].date())} used")
        return float(s.iloc[-1])

    def sso_series(self) -> pd.Series | None:
        if self._sso is None:
            try:
                import yfinance as yf
                h = yf.Ticker("SSO").history(period="1y", auto_adjust=True)
                s = h["Close"]; s.index = pd.to_datetime(s.index).tz_localize(None)
                self._sso = s
            except Exception as e:  # noqa: BLE001
                self.notes.append(f"SSO: provider unavailable ({type(e).__name__})"); self._sso = pd.Series(dtype=float)
        return self._sso

    def provider_series(self, tk: str) -> pd.Series:
        """J6: a name outside every store (a paper-tier member the universe does not carry) from the provider, cached."""
        if tk not in self._prov:
            try:
                import yfinance as yf
                h = yf.Ticker(tk).history(period="6mo", auto_adjust=True)
                s = h["Close"]; s.index = pd.to_datetime(s.index).tz_localize(None)
                self._prov[tk] = s
            except Exception as e:  # noqa: BLE001
                self.notes.append(f"{tk}: provider unavailable ({type(e).__name__})"); self._prov[tk] = pd.Series(dtype=float)
        return self._prov[tk]

    def close(self, tk: str, d: str, provider_ok: bool = False):
        tk = tk.upper()
        if tk in self.px.columns:
            return self._last_on_or_before(self.px[tk], d, tk)
        if tk.lower() in self.etf.columns:
            return self._last_on_or_before(self.etf[tk.lower()], d, tk)
        if tk == "TLT" and self.vol is not None and "tlt" in self.vol.columns:
            return self._last_on_or_before(self.vol["tlt"], d, tk)
        if tk == "SSO":
            s = self.sso_series()
            return self._last_on_or_before(s, d, tk) if s is not None and not s.empty else None
        if provider_ok:
            s = self.provider_series(tk)
            return self._last_on_or_before(s, d, tk + " (provider)") if not s.empty else None
        return None


def regime_R_for(session: str) -> float | None:
    rd = pd.read_csv(DATA / "regime_daily.csv"); rd["date"] = rd["date"].astype(str)
    row = rd[rd["date"] == session]
    if len(row):
        return float(row["R_t"].iloc[0])
    before = rd[rd["date"] < session]
    return float(before["R_t"].iloc[-1]) if len(before) else None


def cash_pct(R: float, spec: dict) -> float:
    cp = min(spec["cash_max"], spec["cash_floor"] + R * spec["cash_slope"])
    return max(cp, spec["cash_floor"])


def build_row(prev: dict, session: str, closes: Closes, cfg: dict, inception: dict, today: str) -> dict:
    from compute_nav import benchmark_navs_from_prices, BENCHMARK_KEYS  # noqa: E402  (pure helpers)
    R = regime_R_for(session)
    if R is None:
        R = float(prev["R_t"])
    label = label_with_corridor(R, prev.get("regime"))
    effr_daily = float(prev.get("effr_daily_pct") or 4.0) / 100.0 / 252.0
    tiers = {}
    for tid in TIERS:
        pt = prev["tiers"].get(tid) or {}
        shares = pt.get("shares") or {p["ticker"]: float(p["shares"]) for p in pt.get("positions", []) if p.get("shares")}
        spec = cfg["tier_specs"][tid]
        positions, equity = [], 0.0
        for tk, sh in shares.items():
            px = closes.close(tk, session)
            if px is None:
                continue
            val = float(sh) * px; equity += val
            positions.append({"ticker": tk, "shares": round(float(sh), 6), "price": round(px, 2), "value": round(val, 2)})
        cash = float(pt.get("cash") or 0.0) * (1.0 + effr_daily)
        total = equity + cash
        for p in positions:
            p["weight"] = round(p["value"] / total * 100, 1) if total > 0 else 0
        cp = cash_pct(R, spec)
        tiers[tid] = {"nav": round(total, 2), "equity": round(equity, 2), "cash": round(cash, 2),
                      "target_cash_pct": round(cp * 100, 1), "actual_cash_pct": round(cash / total * 100, 1) if total > 0 else 0,
                      "n_positions": len(positions), "holdings": [p["ticker"] for p in positions],
                      "shares": {p["ticker"]: p["shares"] for p in positions},
                      "prices_snapshot": {p["ticker"]: round(closes.close(p["ticker"], session) or 0.0, 4) for p in positions},
                      "positions": positions}
    # the operator tier: the previous row's positions (a change enters only through a published row)
    pw = prev["tiers"].get("5_werner") or {}
    wpos, weq = [], 0.0
    for p in pw.get("positions", []):
        sh = float(p.get("shares") or 0)
        if sh <= 0:
            continue
        px = closes.close(p["ticker"], session)
        if px is None:
            wpos.append({"ticker": p["ticker"], "shares": sh, "price": None, "value": None, "cost_basis": p.get("cost_basis"), "gain_pct": None, "_note": "no price"}); continue
        val = sh * px; weq += val
        cost = float(p.get("cost_basis") or 0)
        wpos.append({"ticker": p["ticker"], "shares": sh, "price": round(px, 2), "value": round(val, 2), "cost_basis": p.get("cost_basis"),
                     "gain_pct": round((px / cost - 1) * 100, 1) if cost > 0 else None})
    wcash = float(pw.get("cash") or 0.0) * (1.0 + effr_daily)
    wtot = weq + wcash
    for p in wpos:
        if p.get("value"):
            p["weight"] = round(p["value"] / wtot * 100, 1) if wtot > 0 else 0
    wcp = cash_pct(R, cfg["werner_picks"])
    tiers["5_werner"] = {"nav": round(wtot, 2), "equity": round(weq, 2), "cash": round(wcash, 2), "target_cash_pct": round(wcp * 100, 1),
                         "actual_cash_pct": round(wcash / wtot * 100, 1) if wtot > 0 else 0,
                         "n_positions": len([p for p in wpos if p.get("value")]), "holdings": [p["ticker"] for p in wpos if p.get("value")],
                         "positions": wpos}
    # J6: the STRATIFIED paper tier is carried forward only when the previous row has it (a backfill never seeds it;
    # a rebalance happens only in a published row). Its names come from the stores, else from the provider.
    if prev["tiers"].get(strat_tier.TIER_ID):
        tiers[strat_tier.TIER_ID] = strat_tier.carry_forward_row(prev["tiers"][strat_tier.TIER_ID], session,
                                                                 lambda tk, d: closes.close(tk, d, provider_ok=True), effr_daily)
    prices_lower = {"spy": closes.close("SPY", session), "qqq": closes.close("QQQ", session), "sso": closes.close("SSO", session), "tlt": closes.close("TLT", session)}
    bench = benchmark_navs_from_prices({k: v for k, v in prices_lower.items() if v is not None}, inception)
    return {"date": session, "R_t": round(R, 4), "regime": label, "effr_daily_pct": prev.get("effr_daily_pct"),
            "tiers": tiers, "benchmarks": bench,
            "backfilled": True, "backfill_date": today,
            "backfill_note": ("row computed after the fact under the as-published convention: the previous row's shares at the "
                              "session's closes from the price store, cash at the previous row's EFFR, R from the revised series "
                              "(no published vintage for a session the nightly missed), the label from the hysteresis corridor"),
            "R_t_source": "regime_daily.csv (revised series)"}


def backfill_missing(tournament: dict, through: str | None = None, dry_run: bool = False) -> list[str]:
    """Insert rows for every missing session up to `through` (exclusive of a row not yet
    published). Returns the sessions inserted. Mutates `tournament` in place."""
    history = tournament.get("history", [])
    miss = missing_sessions(history, through)
    if not miss:
        return []
    cfg = json.load(open(REPO / "config.json"))
    inception = json.load(open(DATA / "benchmark_inception.json"))
    closes = Closes()
    today = now_et().strftime("%Y-%m-%d")
    by_date = {h["date"]: h for h in history}
    inserted = []
    for s in miss:
        prev_dates = sorted(d for d in by_date if d < s)
        if not prev_dates:
            continue
        row = build_row(by_date[prev_dates[-1]], s, closes, cfg, inception, today)
        by_date[s] = row; inserted.append(s)
    if not dry_run:
        tournament["history"] = [by_date[d] for d in sorted(by_date)]
    for n in sorted(set(closes.notes))[:20]:
        log(f"note: {n}")
    return inserted


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--print", dest="do_print", action="store_true")
    args = ap.parse_args()
    p = DATA / "tournament.json"
    t = json.load(open(p))
    before = len(t["history"])
    ins = backfill_missing(t, dry_run=args.dry_run)
    log(f"{len(ins)} missing session(s): {ins}")
    if args.do_print or args.dry_run:
        for h in t["history"]:
            if h.get("backfilled") and h["date"] in ins:
                log(f"  {h['date']} R {h['R_t']} {h['regime']} · " + " · ".join(f"{tid[:5]} ${h['tiers'][tid]['nav']:,.0f}" for tid in TIERS + ['5_werner']))
    if args.dry_run or not ins:
        return 0
    from compute_nav import annotate_drawdowns, cost_restatement  # noqa: E402
    cfg = json.load(open(REPO / "config.json")); cm = cfg["system_settings"].get("cost_model", {})
    cost_rt = float(cm.get("one_way_bps", 10)) / 10000.0
    label = f"{cm.get('half_spread_bps', '?')} bps half-spread + {cm.get('impact_bps', '?')} bps impact = {cost_rt*10000:.0f} bps one-way on NAV-weight turnover"
    t["cost_restatement"] = cost_restatement(t["history"], cost_rt, label)
    t["drawdown"] = annotate_drawdowns(t["history"], t["history"][-1]["date"])
    t["backfilled_sessions"] = sorted(set((t.get("backfilled_sessions") or []) + ins))
    p.write_text(json.dumps(t, indent=2, default=str))
    log(f"wrote tournament.json: {before} → {len(t['history'])} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
