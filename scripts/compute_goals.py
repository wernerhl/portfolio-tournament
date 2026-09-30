#!/usr/bin/env python3
"""compute_goals.py — the operator's goals, descriptive (order 30-Sept-2026, items D1 and D2)
→ data/goals.json.

D1  House goal: target R$2,500,000, horizon three years from 18 September 2026. Shows the total
    book and cash in reais at the live rate, the share of target, the dollar cost of the target
    at the live rate, the FX sensitivity row, and the required monthly savings for zero, 5 and
    13 percent annual returns on the reais floor. Descriptive; no recommendation.
D2  Claims register: the pre-registered claim of 18 September 2026 (account value $229,245.80;
    target 29 percent annualized for three years) with the since-start return, its annualized
    equivalent, the number of sessions elapsed, the caption that annualized figures under one
    year are not informative, beside the 29 percent path. The record (claims_register.json) is
    never edited; this file only computes against it.

Inputs: data/goals_config.json, data/claims_register.json, data/book.json (NAV, cash), the
provider's USDBRL quote (BRL=X). --intraday uses the live tape for the rate and the intraday
book; otherwise the last settled close.

Usage:  python scripts/compute_goals.py [--intraday] [--print] [--allow-non-trading]
"""
from __future__ import annotations
import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATA = REPO / "data"
sys.path.insert(0, str(HERE))
from trading_calendar import is_trading_day, last_completed_session, now_et  # noqa: E402

OUT = DATA / "goals.json"


def log(m: str) -> None:
    print(f"[compute_goals] {m}", flush=True)


def r2(x, nd=2):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(f) else round(f, nd)


def fetch_fx(intraday: bool) -> dict:
    """USDBRL (reais per dollar) from the provider: the last daily close for the settled figure,
    the last 1-minute bar for the intraday one. Returns {rate, as_of, source, mode}."""
    import yfinance as yf
    t = yf.Ticker("BRL=X")
    out = {"rate": None, "as_of": None, "source": "BRL=X (provider)", "mode": "intraday" if intraday else "close"}
    try:
        if intraday:
            d = t.history(period="1d", interval="1m", auto_adjust=False)
            c = d["Close"].dropna() if d is not None and not d.empty else None
            if c is not None and not c.empty:
                out.update({"rate": float(c.iloc[-1]), "as_of": str(c.index[-1])})
                return out
        d = t.history(period="10d", auto_adjust=False)
        c = d["Close"].dropna()
        # the settled figure is the last close ON OR BEFORE the last completed session (the
        # provider's daily history carries today's partial bar during the day)
        cutoff = last_completed_session()
        c = c[[str(ix.date()) <= cutoff for ix in c.index]]
        out.update({"rate": float(c.iloc[-1]), "as_of": str(c.index[-1].date()), "mode": "close"})
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}"
    return out


def sessions_between(a: str, b: str) -> int:
    """Trading sessions after a through b."""
    from datetime import date, timedelta
    d0, d1 = date.fromisoformat(a), date.fromisoformat(b)
    n, d = 0, d0 + timedelta(days=1)
    while d <= d1:
        if is_trading_day(d.isoformat()):
            n += 1
        d += timedelta(days=1)
    return n


def monthly_saving(target: float, floor: float, annual: float, months: int) -> float | None:
    """Contribution S per month such that floor·(1+r)^(months/12) + S·annuity = target."""
    if months <= 0:
        return None
    m = (1.0 + annual) ** (1.0 / 12.0) - 1.0
    growth = floor * (1.0 + annual) ** (months / 12.0)
    annuity = months if m == 0 else ((1.0 + m) ** months - 1.0) / m
    return max(0.0, (target - growth) / annuity)


def build(intraday: bool) -> dict:
    cfg = json.load(open(DATA / "goals_config.json"))
    reg = json.load(open(DATA / cfg.get("claims_register_file", "claims_register.json").replace("data/", "")))
    book = json.load(open(DATA / "book.json"))
    session = book.get("session_date") or last_completed_session()
    nav, cash = float(book.get("nav") or 0.0), float(book.get("cash") or 0.0)
    book_mode = "intraday" if book.get("intraday") else "close"
    fx = fetch_fx(intraday)
    hg = cfg["house_goal"]
    rate = fx.get("rate")
    et = now_et()
    today = et.strftime("%Y-%m-%d")
    from datetime import date
    months_left = max(0, (date.fromisoformat(hg["horizon_end"]).year - et.year) * 12 + (date.fromisoformat(hg["horizon_end"]).month - et.month))
    house = {"target_brl": hg["target_brl"], "horizon_start": hg["horizon_start"], "horizon_end": hg["horizon_end"], "months_remaining": months_left,
             "fx": fx, "book_usd": r2(nav), "cash_usd": r2(cash), "book_brl": None, "cash_brl": None, "share_of_target_book": None,
             "share_of_target_cash": None, "target_usd_at_rate": None, "fx_sensitivity": [], "monthly_savings": [],
             "savings_basis": hg["savings_basis"], "fx_sensitivity_note": hg["fx_sensitivity_note"], "note": hg["note"]}
    if rate:
        book_brl, cash_brl = nav * rate, cash * rate
        house.update({"book_brl": r2(book_brl, 0), "cash_brl": r2(cash_brl, 0),
                      "share_of_target_book": r2(book_brl / hg["target_brl"], 4), "share_of_target_cash": r2(cash_brl / hg["target_brl"], 4),
                      "target_usd_at_rate": r2(hg["target_brl"] / rate, 0)})
        house["fx_sensitivity"] = [{"rate": r, "target_usd": r2(hg["target_brl"] / r, 0), "book_brl": r2(nav * r, 0),
                                    "share_of_target_book": r2(nav * r / hg["target_brl"], 4)} for r in hg["fx_sensitivity_rates"]]
        for a in hg["savings_return_scenarios_annual"]:
            s = monthly_saving(hg["target_brl"], book_brl, a, months_left)
            house["monthly_savings"].append({"annual_return": a, "monthly_brl": r2(s, 0), "monthly_usd_at_rate": r2(s / rate, 0) if s is not None else None})
    claims = []
    for c in reg.get("claims", []):
        start_v = float(c["start_value_usd"]); target = float(c["target_annualized_return"])
        n_sess = sessions_between(c["start_date"], session)
        since = nav / start_v - 1.0 if start_v > 0 else None
        ann = ((1.0 + since) ** (252.0 / n_sess) - 1.0) if (since is not None and n_sess > 0 and (1.0 + since) > 0) else None
        days = (date.fromisoformat(session) - date.fromisoformat(c["start_date"])).days
        path_now = start_v * (1.0 + target) ** (days / 365.25)
        path = [{"years": y, "date": f"{int(c['start_date'][:4]) + y}{c['start_date'][4:]}", "value_usd": r2(start_v * (1.0 + target) ** y, 0)} for y in range(0, int(c["horizon_years"]) + 1)]
        claims.append({"claim_id": c["claim_id"], "recorded": c["recorded"], "text": c["text"], "start_date": c["start_date"], "start_value_usd": start_v,
                       "target_annualized_return": target, "horizon_years": c["horizon_years"], "end_date": c.get("end_date"),
                       "session": session, "nav_usd": r2(nav), "sessions_elapsed": n_sess, "calendar_days_elapsed": days,
                       "since_start_return": r2(since, 4), "annualized_equivalent": r2(ann, 4),
                       "annualized_caption": c.get("display_caption", "annualized figures under one year are not informative"),
                       "under_one_year": days < 365, "target_path_value_now_usd": r2(path_now, 0), "gap_to_path_usd": r2(nav - path_now, 0),
                       "target_path": path, "record": "data/claims_register.json (never edited)"})
    return {"cadence": "intraday" if intraday else "daily", "mode": "intraday" if intraday else "close", "intraday": bool(intraday),
            "intraday_as_of": et.isoformat(timespec="seconds") if intraday else None, "session_date": session, "as_of": session,
            "computed_at": et.isoformat(timespec="seconds"), "book_source": {"file": "data/book.json", "mode": book_mode, "holdings_as_of": (book.get("source") or {}).get("holdings_as_of")},
            "house_goal": house, "claims": claims, "register_sha256": __import__("hashlib").sha256(json.dumps(reg, sort_keys=True).encode()).hexdigest(),
            "note": "descriptive; no recommendation; the claims record is immutable and this file only computes against it"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--intraday", action="store_true")
    ap.add_argument("--print", dest="do_print", action="store_true")
    ap.add_argument("--allow-non-trading", action="store_true")
    args = ap.parse_args()
    payload = build(args.intraday)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    h = payload["house_goal"]; fx = h["fx"]
    log(f"wrote data/goals.json ({payload['mode']}) · USDBRL {fx.get('rate')} ({fx.get('as_of')}) · book R${h.get('book_brl')} = {h.get('share_of_target_book')} of target · cash R${h.get('cash_brl')} = {h.get('share_of_target_cash')} · target ${h.get('target_usd_at_rate')} at the rate")
    if args.do_print:
        for s in h["monthly_savings"]:
            log(f"  savings at {s['annual_return']*100:.0f}%/yr: R${s['monthly_brl']:,} per month (${s['monthly_usd_at_rate']:,})")
        for c in payload["claims"]:
            log(f"  claim {c['claim_id']}: since start {c['since_start_return']*100:+.2f}% over {c['sessions_elapsed']} sessions · annualized {c['annualized_equivalent']*100:+.1f}% ({c['annualized_caption']}) · 29% path now ${c['target_path_value_now_usd']:,} · gap ${c['gap_to_path_usd']:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
