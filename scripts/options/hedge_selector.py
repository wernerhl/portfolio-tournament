#!/usr/bin/env python3
"""hedge_selector.py — the hedge selector for held names (Phase 4; descriptive, DIAGNOSTIC).

For each held position, price and rank four structures on the live chain — protective put at
10 and 15 percent out of the money, put spread (10/20), collar (15 percent put, 10 percent
call), covered call (10 percent OTM) — each at the first expiry beyond the next earnings
release and at about 90 days. For each: net cost or credit per share and on the position,
floor and cap, breakevens, the change in position delta, and the book's loss in the three
standing stress scenarios with the structure in place. Selection rules are fixed in
data/options/hedge_rules.json and pre-registered. Every row carries
"DIAGNOSTIC: descriptive; no execution path; option overlays not yet validated."

Reads the session's chain vintage, lens.json (state, term, event, skew), holdings.json and
book.json (values, betas, risk shares, the standing scenarios). Writes data/options/hedges.json.
"""
from __future__ import annotations
import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import options_common as oc
from trading_calendar import now_et

warnings.filterwarnings("ignore")
OUT = oc.OPT / "hedges.json"
RULES = json.loads((oc.OPT / "hedge_rules.json").read_text())
LABEL = RULES["label"]


def log(m: str) -> None:
    print(f"[hedge_selector] {m}", flush=True)


def r2(x, nd=2):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(f) else round(f, nd)


def leg_quote(df: pd.DataFrame, expiry: str, cp: str, moneyness: float, spot: float) -> dict | None:
    """The listed strike nearest the target (at or below for puts, at or above for calls)
    that carries a usable price at this expiry."""
    e = df[(df.expiry == expiry) & (df.cp == cp) & df.price_used.notna() & (df.price_used > 0)]
    if e.empty:
        return None
    target = moneyness * spot
    cand = e[e.strike <= target] if cp == "p" else e[e.strike >= target]
    if cand.empty:
        cand = e
    row = cand.iloc[(cand.strike - target).abs().argsort().iloc[0]]
    return {"strike": float(row.strike), "price": float(row.price_used), "quote": str(row.quote),
            "iv": (float(row.iv) if pd.notna(row.iv) else None), "delta": (float(row.delta) if pd.notna(row.delta) else None)}


def payoff(legs: list[dict], S: float) -> float:
    """Per-share payoff of the structure's option legs at expiry price S (excluding premium)."""
    tot = 0.0
    for lg in legs:
        intr = max(0.0, S - lg["strike"]) if lg["cp"] == "c" else max(0.0, lg["strike"] - S)
        tot += intr if lg["side"] == "buy" else -intr
    return tot


def price_structure(spec: dict, df: pd.DataFrame, expiry: str, spot: float, shares: float,
                    betas: dict, book_stress: list[dict], nav: float, pos_value: float) -> dict | None:
    legs = []
    for L in spec["legs"]:
        q = leg_quote(df, expiry, L["cp"], L["moneyness"], spot)
        if q is None:
            return None
        legs.append({**L, **q})
    net = sum(lg["price"] if lg["side"] == "buy" else -lg["price"] for lg in legs)   # per share; >0 debit, <0 credit
    d_delta = sum((lg["delta"] or 0.0) * (1 if lg["side"] == "buy" else -1) for lg in legs)
    puts_b = [lg for lg in legs if lg["cp"] == "p" and lg["side"] == "buy"]
    puts_s = [lg for lg in legs if lg["cp"] == "p" and lg["side"] == "sell"]
    calls_s = [lg for lg in legs if lg["cp"] == "c" and lg["side"] == "sell"]
    floor = (puts_b[0]["strike"] - net) if puts_b else None
    floor_note = (f"protection ends below {puts_s[0]['strike']:.2f} (the short put)" if puts_s else None)
    cap = (calls_s[0]["strike"] - net) if calls_s else None
    breakeven = spot + net
    contracts = int(shares // 100)
    stress_rows = []
    for sc in book_stress:
        idx = sc.get("index"); b = betas.get(idx)
        if idx is None or b is None:
            continue
        S1 = spot * (1.0 + b * sc["shock"])
        unhedged = shares * (S1 - spot)
        hedged = unhedged + shares * (payoff(legs, S1) - net)
        book_loss = float(sc["loss"]) - unhedged + hedged
        stress_rows.append({"id": sc["id"], "label": sc["label"], "stressed_price": r2(S1),
                            "position_unhedged": r2(unhedged, 0), "position_with_structure": r2(hedged, 0),
                            "book_loss_unhedged": r2(sc["loss"], 0), "book_loss_with_structure": r2(book_loss, 0),
                            "book_share_nav_unhedged": r2(sc["loss"] / nav, 4), "book_share_nav_with_structure": r2(book_loss / nav, 4)})
    return {
        "id": spec["id"], "label": spec["label"], "expiry": expiry,
        "legs": [{k: (r2(v, 4) if isinstance(v, float) else v) for k, v in lg.items() if k != "moneyness"} | {"target_moneyness": lg["moneyness"]} for lg in legs],
        "net_per_share": r2(net), "net_kind": "debit" if net > 0 else "credit",
        "net_on_position": r2(net * shares, 0), "contracts": contracts,
        "floor": r2(floor), "floor_note": floor_note, "cap": r2(cap), "breakeven": r2(breakeven),
        "delta_change_per_share": r2(d_delta, 4), "position_delta_after": r2(1.0 + d_delta, 4),
        "stress": stress_rows, "quote_flags": sorted({lg["quote"] for lg in legs}),
        "diagnostic": LABEL,
    }


def rank(structs: list[dict], ctx: dict) -> list[dict]:
    """Apply the pre-registered selection rules; lower priority ranks first; ties by cost."""
    pri = {s["id"]: 9 for s in structs}; why = {s["id"]: [] for s in structs}
    excluded = set()
    def first(ids, n, note):
        for i in ids:
            if i in pri and pri[i] > n:
                pri[i] = n; why[i].append(f"rule {n}: {note}")
    if ctx["risk_share"] is not None and ctx["risk_share"] > 0.40:
        first(["collar_15_10"], 1, "position risk share above 40% — collar first regardless of volatility state")
    if ctx["state"] == "cheap":
        first(["put_10", "put_spread_10_20", "put_15"], 2, "volatility cheap relative to realized — protection first")
    if ctx["state"] == "rich" and not ctx["earnings_inside"]:
        first(["covered_call_10"], 3, "volatility rich and no earnings inside the tenor — covered call first")
    if ctx["skew"] is not None and ctx["skew"] < 0:
        first(["collar_15_10"], 4, "calls richer than puts at matched distance — sell the rich leg, buy the cheap one")
    if ctx["earnings_inside"] and ctx["term_inverted"]:
        excluded.add("covered_call_10"); why["covered_call_10"].append("rule 5: earnings inside the tenor with an inverted term structure — no naked premium selling ranked")
    out = []
    order = {spec["id"]: i for i, spec in enumerate(RULES["structures"])}   # the registered order: protection first
    for s in structs:
        s = dict(s); s["rank_priority"] = pri[s["id"]]; s["ranked_by"] = why[s["id"]] or ["no rule fired: the registered structure order (protection first)"]
        s["excluded"] = s["id"] in excluded
        out.append(s)
    # Among structures a rule ranked first, the cheaper one leads; with no rule fired, the
    # registered order stands — a credit never ranks first merely for being a credit.
    def key(s):
        if s["rank_priority"] < 9:
            return (s["rank_priority"], s["net_per_share"] if s["net_per_share"] is not None else 9e9, order.get(s["id"], 99))
        return (9, order.get(s["id"], 99), 0)
    ranked = sorted([s for s in out if not s["excluded"]], key=key)
    ranked += [s for s in out if s["excluded"]]
    for i, s in enumerate(ranked):
        s["rank"] = None if s["excluded"] else i + 1
    return ranked


def build() -> dict:
    sessions = oc.captured_sessions()          # captured days only (order 5-Oct-2026, 2.3)
    if not sessions:
        raise SystemExit("[hedge_selector] no chain vintage on disk")
    session = sessions[-1]
    meta = oc.vintage_meta(session); vint = oc.load_vintage(session)
    lens = json.loads((oc.OPT / "lens.json").read_text()).get("names", {}) if (oc.OPT / "lens.json").exists() else {}
    book = json.loads((oc.DATA / "book.json").read_text())
    nav = float(book["nav"]); stress = [s for s in book.get("stress", []) if s.get("index")]
    positions = {p["ticker"]: p for p in book.get("positions", []) if p.get("value") is not None}
    out, warns = {}, []
    for tk, p in sorted(positions.items()):
        if tk not in vint:
            warns.append(f"{tk}: no chain in vintage {session}"); continue
        df = vint[tk]; spot = float(meta["tickers"][tk]["spot"]); shares = float(p["shares"])
        L = lens.get(tk, {}); vol = L.get("volatility", {}); ev = L.get("event", {}); term = L.get("term_structure", {}); sk = L.get("skew", {})
        betas = {"SPY": (p.get("beta_spy") or {}).get("beta"), "SMH": (p.get("beta_smh") or {}).get("beta")}
        expiries = sorted(df.expiry.unique().tolist())
        e_after = ev.get("expiry_after") or oc.pick_expiry([e for e in expiries if (pd.Timestamp(e) - pd.Timestamp(session)).days >= 30] or expiries, session, 30)
        e_90 = oc.pick_expiry(expiries, session, oc.BACK_DAYS)
        gain = (spot / float(p["cost_basis"]) - 1.0) if p.get("cost_basis") else None
        tenors = []
        for kind, e in (("after_earnings", e_after), ("about_90d", e_90)):
            if not e:
                continue
            earnings_inside = bool(ev.get("next_earnings") and pd.Timestamp(ev["next_earnings"]) <= pd.Timestamp(e))
            ctx = {"risk_share": p.get("risk_share"), "state": vol.get("state"), "earnings_inside": earnings_inside,
                   "term_inverted": bool(term.get("inverted")), "skew": sk.get("skew")}
            structs = []
            for spec in RULES["structures"]:
                s = price_structure(spec, df, e, spot, shares, betas, stress, nav, float(p["value"]))
                if s:
                    structs.append(s)
                else:
                    warns.append(f"{tk} {e} {spec['id']}: no usable strikes")
            tenors.append({"tenor": kind, "expiry": e, "days": int((pd.Timestamp(e) - pd.Timestamp(session)).days),
                           "sessions": oc.sessions_to_expiry(session, e), "earnings_inside": earnings_inside,
                           "context": ctx, "structures": rank(structs, ctx)})
        out[tk] = {
            "spot": r2(spot), "shares": shares, "cost_basis": p.get("cost_basis"), "value": r2(p["value"], 0),
            "embedded_gain": r2(gain, 4), "large_embedded_gain": bool(gain is not None and gain > 0.50),
            "embedded_gain_note": ("gain over 50% on cost: a structure that avoids a sale ranks above a trim when it achieves the same "
                                   "stress reduction; the tax consideration is stated in words, no tax computation") if (gain is not None and gain > 0.50) else None,
            "risk_share": r2(p.get("risk_share"), 4), "betas": {k: r2(v, 3) for k, v in betas.items()},
            "volatility_state": vol.get("state"), "term_inverted": term.get("inverted"), "next_earnings": ev.get("next_earnings"),
            "implied_move": r2(ev.get("implied_move"), 4), "skew": sk.get("skew"), "impaired": L.get("impaired"),
            "tenors": tenors, "diagnostic": LABEL,
        }
    return {"cadence": "daily", "session_date": session, "as_of": now_et().date().isoformat(),
            "computed_at": now_et().isoformat(timespec="seconds"), "label": LABEL,
            "rules": RULES["selection_rules"], "structures": RULES["structures"], "tenors": RULES["tenors"],
            "pricing": RULES["pricing"], "stress_method": RULES["stress"], "nav": r2(nav, 0),
            "positions": out, "warnings": warns,
            "note": "descriptive; a menu of structures with their properties and their effect on the book; no execution path; nothing here is a recommendation"}


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--print", dest="do_print", action="store_true"); args = ap.parse_args()
    payload = build()
    OUT.write_text(json.dumps(payload, indent=2))
    log(f"wrote {OUT.relative_to(oc.REPO)}: {len(payload['positions'])} positions, session {payload['session_date']}; warnings {len(payload['warnings'])}")
    for w in payload["warnings"][:10]:
        log(f"  WARN {w}")
    if args.do_print:
        for tk, p in payload["positions"].items():
            log(f"  {tk:5} spot {p['spot']} risk {p['risk_share']} state {p['volatility_state']} inv={p['term_inverted']} earn {p['next_earnings']} gain {p['embedded_gain']}")
            for t in p["tenors"]:
                top = t["structures"][0] if t["structures"] else None
                log(f"     {t['tenor']:14} {t['expiry']} ({t['days']}d) earnings_inside={t['earnings_inside']} → #1 {top['label'] if top else '—'} net {top['net_per_share'] if top else '—'}/sh "
                    f"floor {top['floor'] if top else '—'} cap {top['cap'] if top else '—'} · {top['ranked_by'][0] if top else ''}")
                for s in t["structures"]:
                    sp = next((x for x in s["stress"] if x["id"] == "spy_-20"), None)
                    log(f"        {('#'+str(s['rank'])) if s['rank'] else 'x ':>3} {s['label']:28} {s['net_kind']:6} {s['net_per_share']:>8} /sh  floor {s['floor']}  cap {s['cap']}  Δ {s['delta_change_per_share']}  SPY−20 book {sp['book_share_nav_unhedged'] if sp else '—'} → {sp['book_share_nav_with_structure'] if sp else '—'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
