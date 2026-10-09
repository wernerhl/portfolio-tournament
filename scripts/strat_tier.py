"""strat_tier.py — the STRATIFIED paper tier (6_strat): execution order of 8 October 2026, J6.

The candidate-list score failed its registered test on 8 October 2026 (data/analyst/candidate_list_test_result.json).
The owner keeps a live record of it anyway, apart from the four tiers: the top tenth of the month's S&P 500 members
with prices and fundamentals by the registered score, equal weights, fully invested (cash is only the rounding
residue), no regime cash, rebalanced on the last session of March, June, September and December to the holdings
file of that month-end (data/tournament/strat_holdings/<month_end>.json, written once by
scripts/analyst/strat_holdings.py), the C1 cost (10 bps one-way on NAV-weight turnover) on every trade, start
capital 100,000. No verdict rule; the row stays outside the ranking.

This module holds the accounting only (no provider client, so tests and the backfill import it freely):

  compute_row(history, session, prices, spec, cost_rt, cost_label, effr_daily)
      the tier's entry for the session's tournament row, or None when nothing is to be written (before the first
      session, or no holdings file yet). The previous positions are marked at the session's closes first; on a
      session where a newer holdings file is in force (the latest file at or before the session, quarter-end
      month-ends only) the tier is rebalanced to it at those closes — on the quarter-end session itself when the
      file exists by then, else on the first session after the file appears (recorded as late).
  names_for_session(history, session, spec)
      the tickers compute_nav must price: the previous row's names plus the file in force when a rebalance is due.
  carry_forward_row(prev_tier, session, close_fn, effr_daily)
      the backfill convention (previous shares at the session's closes, cash at EFFR) for a missed session.

The tier's parameters live in config.json under "strat_tier" (load_spec); the four tiers' specs are untouched.
"""
from __future__ import annotations

import json
import math
import re
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
from trading_calendar import is_trading_day  # noqa: E402

TIER_ID = "6_strat"
LABEL = "paper tier · DIAGNOSTIC · its registered test failed on 8 October 2026"
WEIGHTS = "equal weights, fully invested, no regime cash"
DEFAULT_SPEC = {
    "id": TIER_ID, "name": "STRATIFIED", "short": "STRATIFIED", "label": LABEL,
    "first_session": "2026-10-09", "seed_month_end": "2026-09-30", "start_capital": 100000.0,
    "holdings_dir": "data/tournament/strat_holdings", "rebalance_months": [3, 6, 9, 12], "weights": WEIGHTS,
}
_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


def load_spec(cfg: dict) -> dict | None:
    """The tier's parameters from config.json ("strat_tier"); None when the block is absent or disabled."""
    block = (cfg or {}).get("strat_tier")
    if not block or block.get("enabled") is False:
        return None
    spec = {**DEFAULT_SPEC, **block}
    spec["start_capital"] = float(spec["start_capital"])
    spec["rebalance_months"] = [int(m) for m in spec["rebalance_months"]]
    return spec


# ── calendar ─────────────────────────────────────────────────────────────────────────────────────
def month_end_of(d: str) -> str:
    """The calendar month-end of the month containing d (YYYY-MM-DD)."""
    x = date.fromisoformat(d[:10])
    nxt = (x.replace(day=28) + timedelta(days=4)).replace(day=1)
    return (nxt - timedelta(days=1)).isoformat()


def next_trading_day(d: str) -> str:
    x = date.fromisoformat(d[:10]) + timedelta(days=1)
    while not is_trading_day(x):
        x += timedelta(days=1)
    return x.isoformat()


def is_last_session_of_month(session: str) -> bool:
    if not is_trading_day(session):
        return False
    return next_trading_day(session)[:7] != session[:7]


def is_quarter_end_session(session: str, months=(3, 6, 9, 12)) -> bool:
    """The last trading session of March, June, September or December."""
    return int(session[5:7]) in tuple(months) and is_last_session_of_month(session)


def quarter_end_session_for(month_end: str) -> str:
    """The last trading session at or before the calendar month-end."""
    x = date.fromisoformat(month_end[:10])
    while not is_trading_day(x):
        x -= timedelta(days=1)
    return x.isoformat()


# ── holdings files ───────────────────────────────────────────────────────────────────────────────
def holdings_dir_of(spec: dict, holdings_dir: Path | str | None = None) -> Path:
    if holdings_dir is not None:
        return Path(holdings_dir)
    p = Path(spec.get("holdings_dir") or DEFAULT_SPEC["holdings_dir"])
    return p if p.is_absolute() else REPO / p


def holdings_files(hdir: Path, months=(3, 6, 9, 12)) -> list[tuple[str, Path]]:
    """(month_end, path) for every quarter-end holdings file in the directory, oldest first."""
    hdir = Path(hdir)
    if not hdir.exists():
        return []
    out = []
    for p in hdir.iterdir():
        m = _FILE_RE.match(p.name)
        if not m:
            continue
        me = m.group(1)
        if int(me[5:7]) in tuple(months) and me == month_end_of(me):
            out.append((me, p))
    return sorted(out)


def file_in_force(session: str, hdir: Path, months=(3, 6, 9, 12)) -> tuple[str, Path] | None:
    """The latest holdings file whose month-end is at or before the session."""
    cands = [(me, p) for me, p in holdings_files(hdir, months) if me <= session[:10]]
    return cands[-1] if cands else None


def load_holdings(path: Path) -> list[str]:
    """The file's tickers in rank order."""
    j = json.loads(Path(path).read_text())
    names = j.get("names") or []
    out = []
    for n in names:
        tk = n.get("ticker") if isinstance(n, dict) else n
        if tk:
            out.append(str(tk).upper())
    return out


def _rel(p: Path) -> str:
    p = Path(p)
    try:
        return str(p.resolve().relative_to(REPO.resolve()))
    except ValueError:
        return str(p)


# ── the record ───────────────────────────────────────────────────────────────────────────────────
def last_row_with_tier(history: list, before: str | None = None) -> dict | None:
    """The tier's entry in the last history row before `before` (exclusive) that carries it."""
    for row in reversed(history or []):
        if before and str(row.get("date"))[:10] >= before[:10]:
            continue
        t = (row.get("tiers") or {}).get(TIER_ID)
        if t and t.get("nav"):
            return t
    return None


def _shares_of(t: dict) -> dict[str, float]:
    sh = t.get("shares")
    if sh:
        return {str(k).upper(): float(v) for k, v in sh.items() if float(v) > 0}
    return {str(p["ticker"]).upper(): float(p.get("shares") or 0) for p in (t.get("positions") or []) if float(p.get("shares") or 0) > 0}


def _floor6(x: float) -> float:
    return math.floor(x * 1e6 + 1e-9) / 1e6


def rebalance_due(prev: dict | None, session: str, spec: dict, hdir: Path) -> tuple[str, Path] | None:
    """The holdings file to rebalance to on this session, if any: the file in force when the tier holds an older
    month-end (or nothing yet)."""
    if prev is None and session[:10] < spec["first_session"]:
        return None
    target = file_in_force(session, hdir, spec["rebalance_months"])
    if target is None:
        return None
    held = (prev or {}).get("holdings_month_end")
    if prev is None or not held or target[0] > held:
        return target
    return None


def names_for_session(history: list, session: str, spec: dict | None, holdings_dir: Path | str | None = None) -> list[str]:
    """The tickers compute_nav must fetch for the tier on this session."""
    if spec is None:
        return []
    hdir = holdings_dir_of(spec, holdings_dir)
    prev = last_row_with_tier(history, before=session)
    names = set(_shares_of(prev)) if prev else set()
    target = rebalance_due(prev, session, spec, hdir)
    if target:
        names |= set(load_holdings(target[1]))
    return sorted(names)


def compute_row(history: list, session: str, prices: dict, spec: dict | None, cost_rt: float, cost_label: str,
                effr_daily: float, holdings_dir: Path | str | None = None, log=print) -> dict | None:
    """The tier's entry for the session, or None (nothing written: before the first session, or no holdings file)."""
    if spec is None:
        return None
    hdir = holdings_dir_of(spec, holdings_dir)
    prev = last_row_with_tier(history, before=session)
    if prev is None and session[:10] < spec["first_session"]:
        return None
    target = rebalance_due(prev, session, spec, hdir)
    if prev is None and target is None:
        log(f"  {TIER_ID}: no holdings file at or before {session} in {_rel(hdir)} — nothing written")
        return None
    prices = {str(k).upper(): float(v) for k, v in (prices or {}).items() if v is not None}
    # 1. the previous positions, marked at the session's closes (the seed starts all cash)
    positions, equity, unpriced, shares = [], 0.0, [], {}
    if prev is None:
        cash = spec["start_capital"]
        held_file, held_me = None, None
    else:
        shares = _shares_of(prev)
        for tk, sh in shares.items():
            px = prices.get(tk)
            if px is None:
                positions.append({"ticker": tk, "shares": round(sh, 6), "price": None, "value": None, "_note": "no price"})
                unpriced.append(tk); continue
            val = sh * px; equity += val
            positions.append({"ticker": tk, "shares": round(sh, 6), "price": round(px, 2), "value": round(val, 2)})
        cash = float(prev.get("cash") or 0.0) * (1.0 + effr_daily)
        held_file, held_me = prev.get("holdings_file"), prev.get("holdings_month_end")
    nav_marked = equity + cash
    out: dict = {}
    # 2. the rebalance, when a newer holdings file is in force and every held name has a price today
    if target is not None and unpriced:
        log(f"  {TIER_ID}: rebalance to {target[0]} deferred — no price today for {unpriced[:6]}")
        out["rebalance_deferred"] = {"month_end": target[0], "names_without_price": unpriced}
        target = None
    if target is not None:
        me, path = target
        names = load_holdings(path)
        priced = [t for t in names if t in prices]
        skipped = [t for t in names if t not in prices]
        if not priced:
            log(f"  {TIER_ID}: rebalance to {me} deferred — none of its names has a price today")
            out["rebalance_deferred"] = {"month_end": me, "names_without_price": skipped}
        else:
            k = len(priced)
            w_pre = {p["ticker"]: float(p["value"]) / nav_marked for p in positions if p.get("value") and nav_marked > 0}
            w_pre["_cash"] = max(0.0, 1.0 - sum(v for kk, v in w_pre.items() if kk != "_cash"))
            w_new = {t: 1.0 / k for t in priced}; w_new["_cash"] = 0.0
            turnover = 0.5 * sum(abs(w_new.get(kk, 0.0) - w_pre.get(kk, 0.0)) for kk in set(w_pre) | set(w_new))
            cost = cost_rt * turnover
            nav_after = nav_marked * (1.0 - cost)
            per = nav_after / k
            shares = {t: _floor6(per / prices[t]) for t in priced}
            positions = [{"ticker": t, "shares": shares[t], "price": round(prices[t], 2), "value": round(shares[t] * prices[t], 2)} for t in priced]
            equity = sum(shares[t] * prices[t] for t in priced)
            cash = nav_after - equity                                            # the rounding residue, never negative
            on_time = is_quarter_end_session(session, spec["rebalance_months"]) and month_end_of(session) == me
            out["rebalance"] = {"kind": "seed" if prev is None else "quarter-end rebalance",
                                "holdings_file": _rel(path), "month_end": me, "n_names": k,
                                "turnover_one_way": round(turnover, 4), "cost_pct": round(cost * 100, 4), "cost_model": cost_label,
                                "nav_before_cost": round(nav_marked, 2), "names_without_price": skipped,
                                "on_time": bool(on_time) if prev is not None else None,
                                "due_session": quarter_end_session_for(me) if prev is not None else spec["first_session"],
                                "note": "the previous positions are marked at the session's closes, then sold and the new names bought at those closes; the C1 cost on one-way NAV-weight turnover"}
            held_file, held_me = _rel(path), me
    total = equity + cash
    for p in positions:
        p["weight"] = round(p["value"] / total * 100, 1) if (p.get("value") and total > 0) else (0 if p.get("value") is not None else None)
    priced_pos = [p for p in positions if p.get("value") is not None]
    out.update({
        "nav": round(total, 2), "equity": round(equity, 2), "cash": round(cash, 2),
        "target_cash_pct": 0.0,
        "actual_cash_pct": round(cash / total * 100, 1) if total > 0 else 0,
        "n_positions": len(priced_pos),
        "holdings": [p["ticker"] for p in priced_pos],
        "shares": {t: round(s, 6) for t, s in shares.items()},
        "prices_snapshot": {p["ticker"]: round(prices[p["ticker"]], 4) for p in priced_pos},
        "positions": positions,
        "holdings_file": held_file, "holdings_month_end": held_me,
        "paper_tier": True, "label": spec.get("label") or LABEL, "weights": spec.get("weights") or WEIGHTS,
    })
    if prev is None:
        out["first_session"] = session[:10]
    return out


def carry_forward_row(prev_tier: dict, session: str, close_fn, effr_daily: float) -> dict:
    """A missed session under the backfill convention: the previous row's shares at the session's closes (close_fn
    returns a close or None), cash accrued at EFFR; a name without a close keeps its shares and is noted."""
    shares = _shares_of(prev_tier)
    positions, equity, unpriced = [], 0.0, []
    for tk, sh in shares.items():
        px = close_fn(tk, session)
        if px is None:
            unpriced.append(tk); continue
        val = sh * float(px); equity += val
        positions.append({"ticker": tk, "shares": round(sh, 6), "price": round(float(px), 2), "value": round(val, 2)})
    cash = float(prev_tier.get("cash") or 0.0) * (1.0 + effr_daily)
    total = equity + cash
    for p in positions:
        p["weight"] = round(p["value"] / total * 100, 1) if total > 0 else 0
    out = {"nav": round(total, 2), "equity": round(equity, 2), "cash": round(cash, 2), "target_cash_pct": 0.0,
           "actual_cash_pct": round(cash / total * 100, 1) if total > 0 else 0,
           "n_positions": len(positions), "holdings": [p["ticker"] for p in positions],
           "shares": {t: round(s, 6) for t, s in shares.items()},
           "prices_snapshot": {p["ticker"]: round(float(p["price"]), 4) for p in positions},
           "positions": positions,
           "holdings_file": prev_tier.get("holdings_file"), "holdings_month_end": prev_tier.get("holdings_month_end"),
           "paper_tier": True, "label": prev_tier.get("label") or LABEL, "weights": prev_tier.get("weights") or WEIGHTS}
    if unpriced:
        out["names_without_close"] = unpriced
    return out
