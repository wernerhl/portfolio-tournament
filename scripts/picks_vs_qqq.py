#!/usr/bin/env python3
"""
picks_vs_qqq.py — the operator's individual-stock picks against a QQQ shadow (Execution Order: Revision of the
Entry-State Indicator and Related Fixes, 6 October 2026, revised, section 6b).

The operator's stock selection had never been measured. For every individual-stock position, a shadow puts the
same dollars into QQQ on the same dates and takes them out on the same dates. Two windows: from 1 October 2026,
and since the first logged trade. Figures: the cumulative difference in dollars and in percent, the same adjusted
for risk (a shadow holding beta dollars of QQQ per dollar), the share of closed positions that beat their shadow,
and the number of independent decisions (distinct entry dates) beside every figure. Index funds, sector funds and
gold are left out. The tournament's algorithmic tiers get the same statistics over the same dates, pooled and per
tier, so the operator's selection and the system's are compared on equal terms.

Inputs
  data/actions.jsonl     the transactions log: the operator's trade rows (brokerage transactions, then operator
                         reports) and every tier's entries, exits and sizing changes by session
  data/tournament.json   the record's per-session positions (shares, as-published closes) and QQQ's close
  data/source/prices_daily.parquet, data/source/sector_etfs.parquet   betas (daily returns before each start)
  data/picks_vs_qqq_config.json   windows, exclusions, beta rule, definitions

Dates. A trade row in the log with a date and price is used as such. Where the log has no trade row, the change
between two holdings snapshots in the record stands in for it, dated at the snapshot (the trade was on or before
it) and priced at that close; the position says so. A position the log cannot place in time (a sale reported
before the first snapshot that shows the purchase, or a purchase and sale in the same session) is listed as not
measurable, with the reason, and enters no figure.

Output: data/picks_vs_qqq.json. Descriptive: with fewer than about 30 independent decisions the comparison cannot
distinguish skill from chance, and the panel says so beside the figures.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATA = REPO / "data"
CONFIG = DATA / "picks_vs_qqq_config.json"
OUT = DATA / "picks_vs_qqq.json"
EPS = 1e-6


def log(m: str) -> None:
    print(f"[picks_vs_qqq] {m}", flush=True)


# ── the record ────────────────────────────────────────────────────────────────────────────────
def load_record(tournament: dict) -> tuple[list[str], dict[str, dict[str, dict[str, tuple[float, float]]]], dict[str, float]]:
    """sessions (ascending), positions[tier][session] = {ticker: (shares, close)}, qqq[session] = close."""
    sessions, pos, qqq = [], {}, {}
    for row in tournament.get("history", []):
        d = str(row.get("date"))[:10]
        sessions.append(d)
        q = ((row.get("benchmarks") or {}).get("qqq") or {}).get("price")
        if q:
            qqq[d] = float(q)
        for tid, t in (row.get("tiers") or {}).items():
            cur = {}
            for p in (t.get("positions") or []):
                sh = float(p.get("shares") or 0.0)
                if sh > EPS and p.get("price"):
                    cur[str(p["ticker"]).upper()] = (sh, float(p["price"]))
            pos.setdefault(tid, {})[d] = cur
    order = sorted(range(len(sessions)), key=lambda i: sessions[i])
    sessions = [sessions[i] for i in order]
    return sessions, pos, qqq


def snapshot_trades(book_pos: dict[str, dict[str, tuple[float, float]]], sessions: list[str], basis: str) -> list[dict]:
    """The change in shares between consecutive sessions of the record, as trades at that session's close."""
    out, prev = [], {}
    for d in sessions:
        cur = book_pos.get(d)
        if cur is None:
            continue
        for tk in sorted(set(prev) | set(cur)):
            a, b = prev.get(tk, (0.0, None))[0], cur.get(tk, (0.0, None))[0]
            if abs(b - a) > EPS:
                # a ticker still held carries the session's close in the record; a full exit does not, and is priced
                # at the session's canonical close when measured (never at the prior session's close)
                px = cur[tk][1] if tk in cur else None
                out.append({"date": d, "ticker": tk, "delta": b - a, "price": px, "price_basis": "close",
                            "date_basis": basis, "source": "record"})
        prev = cur
    return out


def _row_date(r: dict) -> str | None:
    if r.get("date"):
        return str(r["date"])[:10]
    if r.get("date_range"):
        return str(r["date_range"][0])[:10]
    return str(r.get("session_date"))[:10] if r.get("session_date") else None


def overlay_log_trades(trades: list[dict], rows: list[dict]) -> list[dict]:
    """The log's own trade rows (brokerage transactions first, then operator reports) replace the snapshot change
    they explain: the first snapshot change of the same ticker and direction on or after the row's date, of at
    least the row's quantity. A row that explains no snapshot change is added as a trade of its own."""
    trades = [dict(t) for t in trades]
    rank = {"brokerage transactions": 0}
    rows = sorted([r for r in rows if r.get("ticker") and set(r.get("action") or []) & {"buy", "sell"}],
                  key=lambda r: (rank.get(r.get("source"), 1), _row_date(r) or ""))
    for r in rows:
        tk = str(r["ticker"]).upper()
        side = -1 if "sell" in r["action"] else 1
        qty = float(r.get("quantity") or 0.0)
        d = _row_date(r)
        if not d or qty <= 0:
            continue
        cand = [t for t in trades if t["ticker"] == tk and t["source"] == "record" and t["delta"] * side > 0
                and t["date"] >= d and abs(t["delta"]) + EPS >= qty]
        new = {"date": str(r.get("session_date") or d)[:10] if not r.get("date") else d, "ticker": tk, "delta": side * qty,
               "price": float(r["price"]) if r.get("price") else None,
               "price_basis": r.get("price_basis") or ("as exported" if r.get("source") == "brokerage transactions" else "reported"),
               "date_basis": (r.get("date_note") or r.get("source") or "log row"), "source": r.get("source") or "log row"}
        if cand:
            t = min(cand, key=lambda x: x["date"])
            rest = t["delta"] - new["delta"]
            trades.remove(t)
            if abs(rest) > EPS:                      # the snapshot change was larger than the row: keep the remainder
                trades.append({**t, "delta": rest})
            new["replaces"] = f"the holdings-snapshot change of {t['date']}"
        trades.append(new)
    return sorted(trades, key=lambda t: (t["date"], t["ticker"]))


def first_logged_trade(rows: list[dict], operator: str) -> str | None:
    ds = []
    for r in rows:
        if r.get("tier") != operator:
            continue
        acts = set(r.get("action") or [])
        if acts & {"buy", "sell"} or (acts & {"entry", "exit"} and (r.get("entries") or r.get("exits"))):
            d = _row_date(r)
            if d:
                ds.append(d)
    return min(ds) if ds else None


# ── betas ─────────────────────────────────────────────────────────────────────────────────────
class Betas:
    def __init__(self, cfg: dict):
        self.cfg = cfg["beta"]
        try:
            p = pd.read_parquet(DATA / "source" / "prices_daily.parquet"); p.index = pd.to_datetime(p.index)
            e = pd.read_parquet(DATA / "source" / "sector_etfs.parquet"); e.index = pd.to_datetime(e.index)
            self.px = p.sort_index()
            self.r = self.px.pct_change(fill_method=None)
            self.q = e["qqq"].sort_index().pct_change(fill_method=None)
        except Exception as ex:  # noqa: BLE001
            log(f"betas unavailable ({type(ex).__name__}: {ex}); every beta is the fallback")
            self.px, self.r, self.q = pd.DataFrame(), pd.DataFrame(), pd.Series(dtype=float)
        self.cache = {}

    def close(self, tk: str, d: str) -> float | None:
        """The canonical close of tk on session d (data/source/prices_daily.parquet), or None."""
        try:
            v = self.px.at[pd.Timestamp(d), tk]
            return float(v) if pd.notna(v) else None
        except (KeyError, ValueError):
            return None

    def at(self, tk: str, start: str) -> tuple[float, int, str]:
        key = (tk, start)
        if key in self.cache:
            return self.cache[key]
        n_need, n_min, fb = self.cfg["sessions"], self.cfg["min_sessions"], self.cfg["fallback"]
        res = (fb, 0, f"fewer than {n_min} sessions of history: beta {fb}")
        if tk in getattr(self.r, "columns", []):
            x = pd.concat([self.r[tk], self.q], axis=1, keys=["s", "q"]).loc[:pd.Timestamp(start) - pd.Timedelta(days=1)].dropna().iloc[-n_need:]
            if len(x) >= n_min and x["q"].var() > 0:
                b = float(np.cov(x["s"], x["q"])[0, 1] / x["q"].var())
                res = (b, len(x), f"{len(x)} sessions before {start}")
        self.cache[key] = res
        return res


# ── one book over one window ─────────────────────────────────────────────────────────────────
def first_seen(book_pos: dict, sessions: list[str], tk: str, at: str) -> tuple[str, bool]:
    """The first session of the continuous holding of tk that includes session `at`; True when it reaches back to the
    record's first session (held before the record began)."""
    idx = sessions.index(at)
    i = idx
    while i - 1 >= 0 and tk in (book_pos.get(sessions[i - 1]) or {}):
        i -= 1
    return sessions[i], i == 0


def measure(book: str, book_pos: dict, trades: list[dict], sessions: list[str], qqq: dict[str, float], t0: str, T: str,
            betas: Betas, excluded: dict[str, str]) -> tuple[list[dict], list[dict], list[dict]]:
    """Positions (spells) of one book in (t0, T]: held at the close of t0 or bought after it. Returns (measured
    spells, not measurable, excluded)."""
    win = [d for d in sessions if t0 <= d <= T]
    held0 = book_pos.get(t0) or {}
    tickers = sorted(set(held0) | {t["ticker"] for t in trades if t0 < t["date"] <= T})
    spells, bad, excl = [], [], []
    for tk in tickers:
        if tk in excluded:
            excl.append({"book": book, "ticker": tk, "category": excluded[tk]})
            continue
        ev = {}
        for t in trades:
            if t["ticker"] == tk and t0 < t["date"] <= T:
                ev.setdefault(t["date"], []).append(t)
        shares = 0.0
        cur = None
        last_px = None
        problem = None

        def open_spell(d, entry, entry_basis, held_before):
            b, bn, bnote = betas.at(tk, d)
            return {"book": book, "ticker": tk, "start": d, "entry_date": entry, "entry_basis": entry_basis,
                    "held_before_record": held_before, "beta": round(b, 3), "beta_basis": bnote,
                    "dollars_in": 0.0, "shadow": 0.0, "shadow_b": 0.0, "buys": 0.0, "sells": 0.0, "_b": b,
                    "trades": [], "flags": []}

        if tk in held0:
            shares, px = held0[tk]
            last_px = px
            entry, before = first_seen(book_pos, sessions, tk, t0)
            cur = open_spell(t0, entry, ("held before the record began (" + sessions[0] + ")" if before
                                         else "first holdings snapshot showing it: " + entry), before)
            v = shares * px
            cur.update(dollars_in=v, shadow=v, shadow_b=v, buys=v)
            cur["trades"].append({"date": t0, "delta": round(shares, 4), "price": round(px, 2), "basis": "held at the window's opening close"})
        prev = t0
        for d in win[1:]:
            qr = (qqq[d] / qqq[prev] - 1.0) if (d in qqq and prev in qqq) else 0.0
            if cur is not None:
                cur["shadow"] *= (1.0 + qr)
                cur["shadow_b"] *= (1.0 + cur["_b"] * qr)
            px_d = (book_pos.get(d) or {}).get(tk, (None, None))[1] or betas.close(tk, d)
            if px_d:
                last_px = px_d
            for t in ev.get(d, []):
                if t["delta"] < 0 and (cur is None or shares + t["delta"] < -EPS):
                    problem = (f"the log records a sale of {abs(t['delta']):g} shares on {d} ({t['date_basis']}) before the first "
                               f"holdings snapshot that shows the position; the entry date and price are not in the log")
                    break
                px = t["price"] if t["price"] else px_d
                if t["price"] is None:
                    t = {**t, "price_basis": "the session's close" if t["source"] == "record" else "not in the log: the session's close"}
                if px is None:
                    problem = f"no close for {tk} on {d}"
                    break
                if t["delta"] > 0:
                    if cur is None:
                        eb = (t["date_basis"] if t["source"] != "record" else
                              "holdings snapshot of " + d + " (bought on or before it)" if t["date_basis"] == "holdings snapshot" else
                              "tier record: bought at the close of " + d)
                        cur = open_spell(d, d, eb, False)
                    flow = t["delta"] * px
                    cur["dollars_in"] += flow; cur["buys"] += flow; cur["shadow"] += flow; cur["shadow_b"] += flow
                    shares += t["delta"]
                else:
                    if cur["start"] == d:
                        problem = (f"bought and sold in the same session ({d}): the purchase is dated only by the holdings "
                                   f"snapshot, so the holding period is not in the log")
                        break
                    flow = -t["delta"] * px
                    cur["sells"] += flow; cur["shadow"] -= flow; cur["shadow_b"] -= flow
                    shares += t["delta"]
                cur["trades"].append({"date": d, "delta": round(t["delta"], 4), "price": round(px, 2),
                                      "basis": f"{t['source']}: {t['price_basis']}"})
                if t["source"] == "record" and t.get("date_basis") == "holdings snapshot":
                    cur["flags"].append(f"{d}: dated by the holdings snapshot (the trade was on or before it)")
                if shares <= EPS and cur is not None:
                    cur.update(end=d, closed=True, value_end=0.0)
                    spells.append(cur); cur = None; shares = 0.0
            if problem:
                break
            prev = d
        if problem:
            bad.append({"book": book, "ticker": tk, "reason": problem})
            continue
        if cur is not None:
            v = shares * (last_px or 0.0)
            cur.update(end=T, closed=False, value_end=v)
            spells.append(cur)
    for s in spells:
        s["diff_usd"] = s["value_end"] + s["sells"] - s["buys"] - (s["shadow"] + s["sells"] - s["buys"])     # = value_end - shadow
        s["riskadj_usd"] = s["value_end"] - s["shadow_b"]
        s["pnl_usd"] = s["value_end"] + s["sells"] - s["buys"]
        s["shadow_pnl_usd"] = s["shadow"] + s["sells"] - s["buys"]
        s["diff_pct"] = s["diff_usd"] / s["dollars_in"] if s["dollars_in"] else None
        s["beat"] = s["diff_usd"] > 0
        for k in ("dollars_in", "shadow", "shadow_b", "buys", "sells", "value_end", "diff_usd", "riskadj_usd", "pnl_usd", "shadow_pnl_usd"):
            s[k] = round(s[k], 2)
        s["diff_pct"] = round(s["diff_pct"], 5) if s["diff_pct"] is not None else None
        s.pop("_b", None)
    return spells, bad, excl


def summarize(spells: list[dict], pooled_dates: bool = True) -> dict:
    n_dec = len({(s["entry_date"] if not s["held_before_record"] else "before the record") if pooled_dates
                 else (s["book"], s["entry_date"]) for s in spells})
    dollars = sum(s["dollars_in"] for s in spells)
    diff = sum(s["diff_usd"] for s in spells)
    radj = sum(s["riskadj_usd"] for s in spells)
    closed = [s for s in spells if s["closed"]]
    beat = sum(1 for s in closed if s["beat"])
    return {"positions": len(spells), "decisions": n_dec, "dollars_in": round(dollars, 2),
            "diff_usd": round(diff, 2), "diff_pct": round(diff / dollars, 5) if dollars else None,
            "riskadj_usd": round(radj, 2), "riskadj_pct": round(radj / dollars, 5) if dollars else None,
            "closed": len(closed), "closed_beat": beat, "closed_beat_share": round(beat / len(closed), 4) if closed else None,
            "closed_decisions": len({s["entry_date"] if not s["held_before_record"] else "before the record" for s in closed})}


def build(cfg: dict, tournament: dict, rows: list[dict], betas: Betas) -> dict:
    sessions, pos, qqq = load_record(tournament)
    T = sessions[-1]
    op, algos = cfg["operator_tier"], cfg["algorithmic_tiers"]
    excluded = {}
    for cat, lst in cfg["exclude"].items():
        if isinstance(lst, list):
            for t in lst:
                excluded[t.upper()] = cat.replace("_", " ").rstrip("s") if cat != "gold" else "gold"
    op_rows = [r for r in rows if r.get("tier") == op]
    first = first_logged_trade(rows, op)
    trades = {op: overlay_log_trades(snapshot_trades(pos.get(op, {}), sessions, "holdings snapshot"), op_rows)}
    for tid in algos:
        trades[tid] = snapshot_trades(pos.get(tid, {}), sessions, "tier record")
    windows = []
    for w in cfg["windows"]:
        start = first if w["start"] == "first_logged_trade" else w["start"]
        if not start:
            windows.append({**w, "status": "no trade row in the log"}); continue
        before = [d for d in sessions if d < start]
        if not before:
            windows.append({**w, "status": f"the record begins after {start}"}); continue
        t0 = before[-1]
        res = {"id": w["id"], "label": w["label"], "opens": start, "opening_close": t0, "as_of": T,
               "sessions": len([d for d in sessions if t0 < d <= T])}
        sp_op, bad_op, ex_op = measure(op, pos.get(op, {}), trades[op], sessions, qqq, t0, T, betas, excluded)
        res["operator"] = {"summary": summarize(sp_op), "positions": sp_op, "not_measurable": bad_op, "excluded": ex_op}
        tiers, all_sp, all_bad, all_ex = {}, [], [], []
        for tid in algos:
            sp, bad, ex = measure(tid, pos.get(tid, {}), trades[tid], sessions, qqq, t0, T, betas, excluded)
            tiers[tid] = {"summary": summarize(sp), "positions": sp, "not_measurable": bad, "excluded": ex}
            all_sp += sp; all_bad += bad; all_ex += ex
        res["algorithmic"] = {"summary": summarize(all_sp), "tiers": tiers,
                              "pooling": "the four tiers' positions summed; decisions = distinct entry dates across the tiers"}
        q0, q1 = qqq.get(t0), qqq.get(T)
        res["qqq_return"] = round(q1 / q0 - 1, 5) if q0 and q1 else None
        windows.append(res)
    return {"windows": windows, "first_logged_trade": first, "as_of": T, "record_begins": sessions[0]}


def main() -> int:
    cfg = json.loads(CONFIG.read_text())
    tournament = json.loads((DATA / "tournament.json").read_text())
    rows = []
    p = DATA / "actions.jsonl"
    if p.exists():
        for line in p.read_text().splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    out = build(cfg, tournament, rows, Betas(cfg))
    n_export = sum(1 for r in rows if r.get("tier") == cfg["operator_tier"] and r.get("source") == "brokerage transactions")
    payload = {
        "cadence": "daily", "session_date": out["as_of"], "as_of": out["as_of"],
        "computed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "label": "DESCRIPTIVE",
        "title": "the operator's individual-stock picks against a QQQ shadow, and the algorithmic tiers on the same terms",
        "skill_note": cfg["skill_note"], "min_decisions": cfg["min_decisions"],
        "definitions": cfg["definitions"], "exclusion_rule": cfg["exclude"]["rule"], "beta_rule": cfg["beta"]["rule"],
        "data_basis": ("the brokerage transactions export is in the log for " + str(n_export) + " trade rows" if n_export else
                       "no brokerage transactions export is in the log yet: the operator's dates come from holdings snapshots "
                       "(a trade on or before the snapshot) and the two trades the operator reported; the figures become exact "
                       "once the export is ingested (scripts/ingest_brokerage.py, scripts/seed_actions_from_transactions.py)"),
        "record_begins": out["record_begins"], "first_logged_trade": out["first_logged_trade"],
        "windows": out["windows"],
        "source": "data/actions.jsonl (the transactions log), data/tournament.json (per-session positions and closes), data/picks_vs_qqq_config.json",
    }
    OUT.write_text(json.dumps(payload, indent=1, allow_nan=False, default=str))
    for w in out["windows"]:
        if "operator" not in w:
            log(f"{w['label']}: {w.get('status')}"); continue
        o, a = w["operator"]["summary"], w["algorithmic"]["summary"]
        log(f"{w['label']} (from the close of {w['opening_close']} to {w['as_of']}): operator {o['diff_usd']:+.0f} USD "
            f"({(o['diff_pct'] or 0) * 100:+.2f}%), risk-adjusted {o['riskadj_usd']:+.0f}, closed beat {o['closed_beat']}/{o['closed']}, "
            f"{o['decisions']} decisions; tiers {a['diff_usd']:+.0f} ({(a['diff_pct'] or 0) * 100:+.2f}%), {a['decisions']} decisions; "
            f"not measurable: {[b['ticker'] for b in w['operator']['not_measurable']]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
