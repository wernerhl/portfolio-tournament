#!/usr/bin/env python3
"""
compute_twins.py — order of 30 September 2026, "Continuous Selection, Trade Logs" (4.1–4.3).

Four twins, 1c–4c, of the algorithmic tiers 1–4: same universe, same scores (the tier ranking of
scripts/select_tiers.py), same cash target (compute_nav.cash_pct_from_formula on R_full), same
cost model (C1: 10 bps one-way on |Δweight| in NAV space), differing ONLY in the execution rule:

  daily evaluation, banded execution —
    (b) RANK_EXIT   a held name exits when its tier rank falls below 2K (or it leaves the scored file)
    (c) RANK_ENTRY  an open slot (fewer than K holdings) is filled with the best-ranked name in the
                    top K not held; then a top-K name not held displaces the weakest holding when it
                    exceeds it by ≥ δ tier_composite points (one displacement per name, in rank order;
                    the displaced name is logged RANK_EXIT, the entrant RANK_ENTRY)
    (d) REGIME_CASH the equity sleeve is traded pro rata when |target − actual cash| > 5 points; the
                    target is the tier's cash formula on R_full, the corrected hysteresis label
                    (regime_v2 corridor) is recorded with every trade
    (e) DRIFT       a position is resized to target = (1 − target_cash)/n_held when its weight is off
                    by more than 25 percent of target
  SEED: on a twin's first session the top K are bought at equal weight from all cash with the
  regime cash target (SEED is added to the order's reason codes).

Runs nightly AFTER score_universe.py, compute_regime_v2.py and compute_nav.py (the session's scores,
closes, R and corridor label must exist). Executes at the session's closes from the price store and
charges the C1 cost exactly as compute_nav does — once per session, 10 bps × one-way turnover, where
one-way turnover = 0.5 × Σ|w_after − w_before| over every name and the cash sleeve on the session's
pre-trade NAV (a swap of A for B of value x costs 10 bps × x; so does a cash-funded buy of x) — levied
from cash and allocated pro rata by traded value to the session's trade rows. Cash accrues EFFR daily
(the tournament row's effr_daily_pct, else 4 %/252). Never trades on a non-session; idempotent (a
session already in the state is a no-op).

State   data/tournament/twins_state.json   (positions, cash, nav history, open spells — per twin)
Output  data/tournament/twins.json         (served; cadence daily)
Logs    data/tournament/trades.jsonl       one line per trade (append-only)
        data/tournament/spells.jsonl       one line per spell EVENT: opened / closed / followup_20 / followup_60

Rules   data/tournament/continuous_rules.json (static; sha256 recorded in the output). When config.json
        carries a `continuous_rules` block, its `rules_file` names the file and any parameter present in
        both must agree.

Everything here is a descriptive record of a rule-driven paper tournament; nothing is a recommendation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
from select_tiers import apply_filter          # noqa: E402  (the tier's universe filter, verbatim)
from trading_calendar import is_trading_day, last_completed_session, prev_trading_day  # noqa: E402

REASONS = ("SEED", "RANK_ENTRY", "RANK_EXIT", "REGIME_CASH", "DRIFT", "RECONSTITUTION")
ET = ZoneInfo("America/New_York")
EPS_SHARES = 1e-9


def now_et_iso() -> str:
    return datetime.now(ET).isoformat(timespec="seconds")


def sha256_file(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def cash_pct_from_formula(R: float, spec: dict) -> float:
    """Identical to compute_nav.cash_pct_from_formula (re-stated here so the engine does not import
    the provider client compute_nav pulls in at module level; tests/test_twins.py asserts equality)."""
    cp = min(spec["cash_max"], spec["cash_floor"] + R * spec["cash_slope"])
    return max(cp, spec["cash_floor"])


def naive_regime_label(R: float) -> str:
    """compute_nav's threshold label — used only as the last fallback and marked as such."""
    return "LOW RISK" if R < 0.30 else "ELEVATED" if R < 0.50 else "HIGH RISK" if R < 0.70 else "CRISIS"


# ──────────────────────────────────────────────────────────────────────────────
# Rules
# ──────────────────────────────────────────────────────────────────────────────
RULE_KEYS = ("k_buffer_multiple", "score_margin_delta", "cash_gap_points", "drift_pct_of_target",
             "start_capital", "cost_bps_one_way", "twins")


def load_rules(rules_path: Path, cfg: dict | None) -> tuple[dict, Path]:
    """The rules file is the source; a `continuous_rules` block in config.json may name the file and
    must agree with it on every shared parameter (a disagreement refuses the run)."""
    blk = (cfg or {}).get("continuous_rules") or {}
    if isinstance(blk, dict) and blk.get("rules_file") and rules_path is None:
        rules_path = REPO / blk["rules_file"]
    if rules_path is None:
        rules_path = REPO / "data" / "tournament" / "continuous_rules.json"
    if not rules_path.exists():
        raise SystemExit(f"continuous_rules_missing: {rules_path}")
    rules = json.load(open(rules_path))
    missing = [k for k in RULE_KEYS if k not in rules]
    if missing:
        raise SystemExit(f"continuous_rules_incomplete: missing {missing} in {rules_path}")
    if isinstance(blk, dict):
        for k in RULE_KEYS:
            if k in blk and blk[k] != rules[k]:
                raise SystemExit(f"continuous_rules_disagree: config.json continuous_rules.{k}={blk[k]!r} "
                                 f"!= {rules_path.name} {k}={rules[k]!r}")
    return rules, rules_path


# ──────────────────────────────────────────────────────────────────────────────
# Scores at decision
# ──────────────────────────────────────────────────────────────────────────────
def rank_universe(scored: pd.DataFrame, spec: dict) -> pd.DataFrame:
    """The tier's ranking, exactly as select_tiers.select_for_tier builds it: the universe filter, then
    tier_tech from the ma200/rsi/rs6m ranks weighted by factor_weights × 25, plus fund_score (median-
    filled), ordered by nlargest on tier_composite. Row i (0-based) has tier_rank i+1; the first
    n_holdings rows ARE select_for_tier's picks (tests/test_twins.py asserts this on the live file)."""
    cand = apply_filter(scored, spec.get("universe_filter"))
    cols = ["ticker", "tier_tech", "tier_composite", "tier_rank", "composite", "composite_rank"]
    if cand.empty:
        return pd.DataFrame(columns=cols)
    w = spec["factor_weights"]
    total_w = w["ma200"] + w["rsi"] + w["rs6m"]
    cand = cand.assign(
        tier_tech=(
            cand["ma200_rank"].fillna(0.5) * w["ma200"] +
            cand["rsi_rank"].fillna(0.5) * w["rsi"] +
            cand["rs6m_rank"].fillna(0.5) * w["rs6m"]
        ) / total_w * 25,
    )
    cand["tier_composite"] = cand["tier_tech"] + cand["fund_score"].fillna(cand["fund_score"].median())
    ranked = cand.nlargest(len(cand), "tier_composite").reset_index(drop=True)
    ranked["tier_rank"] = range(1, len(ranked) + 1)
    for c in ("composite", "composite_rank"):
        if c not in ranked.columns:
            ranked[c] = None
    return ranked[cols]


def load_bq(scores_json: Path | None, screen_csv: Path | None) -> dict:
    """Business Quality at decision: the screen's `composite` with `rank` — the watchlist rows of
    data/screen/scores.json first, then the screen's full scored universe (same session, same numbers
    for the names on both) for names off the watchlist. {ticker: (score, rank, source)}."""
    out = {}
    if screen_csv and Path(screen_csv).exists():
        try:
            df = pd.read_csv(screen_csv)
            if {"ticker", "composite", "rank"} <= set(df.columns):
                for r in df.itertuples(index=False):
                    if pd.notna(r.composite):
                        out[str(r.ticker)] = (float(r.composite), int(r.rank), "screen_universe")
        except Exception as e:                       # a broken file is a null with a note, never a crash
            print(f"  warn bq universe unreadable: {e}", file=sys.stderr)
    if scores_json and Path(scores_json).exists():
        try:
            sj = json.load(open(scores_json))
            for r in sj.get("watchlist", []) or []:
                if r.get("composite") is not None and r.get("ticker"):
                    out[str(r["ticker"])] = (float(r["composite"]), int(r.get("rank") or 0) or None, "screen_watchlist")
        except Exception as e:
            print(f"  warn bq watchlist unreadable: {e}", file=sys.stderr)
    return out


def load_tn(signals_json: Path | None) -> dict:
    """Trade-Now at decision: signals[tk].trade_now_strength with a competition rank among the names
    that carry a value (1 + the count strictly stronger). {ticker: (strength, rank, signal_strength)}."""
    if not signals_json or not Path(signals_json).exists():
        return {}
    try:
        sig = json.load(open(signals_json)).get("signals", {}) or {}
    except Exception as e:
        print(f"  warn signals unreadable: {e}", file=sys.stderr)
        return {}
    vals = {tk: float(v["trade_now_strength"]) for tk, v in sig.items()
            if isinstance(v, dict) and v.get("trade_now_strength") is not None}
    out = {}
    for tk, v in sig.items():
        if not isinstance(v, dict):
            continue
        s = vals.get(tk)
        rank = (1 + sum(1 for x in vals.values() if x > s)) if s is not None else None
        out[tk] = (s, rank, v.get("signal_strength"))
    return out


class ScoreBook:
    """All scores at decision for one session: the tier rankings per spec, the tournament composite,
    Business Quality and Trade-Now. `scores_for` returns the trade-row fields plus a scores_note."""

    def __init__(self, scored: pd.DataFrame | None, tier_specs: dict, bq: dict, tn: dict,
                 note: str | None = None, bq_note: str | None = None, tn_note: str | None = None):
        self.scored = scored
        self.rankings = {tid: rank_universe(scored, spec) for tid, spec in tier_specs.items()} if scored is not None else {}
        self.bq, self.tn = bq, tn
        self.note, self.bq_note, self.tn_note = note, bq_note, tn_note
        self._comp = {}
        if scored is not None and "composite" in scored.columns:
            for r in scored.itertuples(index=False):
                cr = getattr(r, "composite_rank", None)
                self._comp[str(r.ticker)] = (None if pd.isna(r.composite) else float(r.composite),
                                             None if cr is None or pd.isna(cr) else int(cr))

    def ranking(self, tid: str) -> pd.DataFrame:
        return self.rankings.get(tid, pd.DataFrame(columns=["ticker", "tier_composite", "tier_rank"]))

    def scores_for(self, ticker: str, tid: str) -> dict:
        notes = []
        if self.note:
            notes.append(self.note)
        rk = self.ranking(tid)
        row = rk[rk["ticker"] == ticker] if len(rk) else rk
        if len(row):
            tc, tr = float(row["tier_composite"].iloc[0]), int(row["tier_rank"].iloc[0])
        else:
            tc, tr = None, None
            if self.scored is not None:
                notes.append("not in the tier's candidate universe at decision" if ticker in self._comp
                             else "not in scored_universe.csv at decision")
        comp, comp_rank = self._comp.get(ticker, (None, None))
        b = self.bq.get(ticker)
        if b is None:
            notes.append(self.bq_note or "Business Quality: name not scored by the screen at decision")
        t = self.tn.get(ticker)
        if t is None or t[0] is None:
            notes.append(self.tn_note or ("Trade-Now: no signal record at decision" if t is None
                                          else "Trade-Now: strength null at decision (position mode / insufficient history)"))
        return {"tier_composite": None if tc is None else round(tc, 4), "tier_rank": tr,
                "composite": None if comp is None else round(comp, 4), "composite_rank": comp_rank,
                "bq_score": None if b is None else b[0], "bq_rank": None if b is None else b[1],
                "tn_score": None if (t is None or t[0] is None) else t[0], "tn_rank": None if (t is None or t[0] is None) else t[1],
                "scores_note": "; ".join(notes) if notes else None}


# ──────────────────────────────────────────────────────────────────────────────
# Prices, benchmarks, thesis baskets
# ──────────────────────────────────────────────────────────────────────────────
class PriceStore:
    """Daily closes by ticker (data/source/prices_daily.parquet) and the ETF store (sector_etfs.parquet,
    `spy`). Sessions are the store's own bars; `session_after(d, n)` is the n-th bar after d."""

    def __init__(self, prices_path: Path, etfs_path: Path | None):
        df = pd.read_parquet(prices_path)
        df.index = pd.to_datetime(df.index)
        try:
            df.index = df.index.tz_localize(None)
        except (TypeError, AttributeError):
            pass
        self.px = df.sort_index()
        self.etf = None
        if etfs_path and Path(etfs_path).exists():
            e = pd.read_parquet(etfs_path)
            e.index = pd.to_datetime(e.index)
            try:
                e.index = e.index.tz_localize(None)
            except (TypeError, AttributeError):
                pass
            self.etf = e.sort_index()
        self.sessions = [d.strftime("%Y-%m-%d") for d in self.px.index]
        self._pos = {d: i for i, d in enumerate(self.sessions)}

    def has_session(self, session: str) -> bool:
        return session in self._pos

    def last_session(self) -> str:
        return self.sessions[-1] if self.sessions else ""

    def close(self, ticker: str, session: str) -> tuple[float | None, str | None]:
        """(close, bar_date): the session's bar when present, else the last bar on or before the session
        (bar_date then differs from the session — a stale price)."""
        if ticker not in self.px.columns:
            return None, None
        ts = pd.Timestamp(session)
        if ts in self.px.index:
            v = self.px.at[ts, ticker]
            if pd.notna(v):
                return float(v), session
        ser = self.px[ticker].loc[:ts].dropna()
        if ser.empty:
            return None, None
        return float(ser.iloc[-1]), ser.index[-1].strftime("%Y-%m-%d")

    def spy(self, session: str) -> float | None:
        if self.etf is None or "spy" not in self.etf.columns:
            return None
        ser = self.etf["spy"].loc[:pd.Timestamp(session)].dropna()
        if ser.empty or ser.index[-1].strftime("%Y-%m-%d") != session:
            return None
        return float(ser.iloc[-1])

    def session_after(self, session: str, n: int) -> str | None:
        i = self._pos.get(session)
        if i is None:
            later = [d for d in self.sessions if d > session]
            if not later:
                return None
            i = self._pos[later[0]] - 1
        j = i + n
        return self.sessions[j] if 0 <= j < len(self.sessions) else None

    def basket_return(self, members: list[str], d0: str, d1: str) -> tuple[float | None, list[str]]:
        """Equal-weight basket of the members' daily returns compounded over (d0, d1]; members without
        prices are dropped and named. None when no member has prices."""
        cols = [m for m in members if m in self.px.columns]
        if not cols or d1 <= d0:
            return None, [m for m in members if m not in self.px.columns]
        win = self.px[cols].loc[pd.Timestamp(d0):pd.Timestamp(d1)]
        if len(win) < 2:
            return None, [m for m in members if m not in self.px.columns]
        rets = win.pct_change().iloc[1:]
        daily = rets.mean(axis=1, skipna=True).fillna(0.0)
        return float((1.0 + daily).prod() - 1.0), [m for m in members if m not in self.px.columns]


def member_weight(v) -> float:
    return float(v.get("weight", 0.0)) if isinstance(v, dict) else float(v)


def thesis_basket_of(ticker: str, registry: dict | None) -> tuple[str | None, list[str]]:
    """The thesis in which the name carries its largest weight (registry order breaks ties) and the
    other members of that thesis (equal-weight basket, the name itself excluded)."""
    if not registry:
        return None, []
    best, best_w = None, 0.0
    for tid, th in (registry.get("theses") or {}).items():
        mem = th.get("members") or {}
        if ticker in mem and member_weight(mem[ticker]) > best_w:
            best, best_w = tid, member_weight(mem[ticker])
    if best is None:
        return None, []
    return best, [m for m in (registry["theses"][best].get("members") or {}) if m != ticker]


# ──────────────────────────────────────────────────────────────────────────────
# Logs (append-only, keyed)
# ──────────────────────────────────────────────────────────────────────────────
def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    with open(p) as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                out.append(json.loads(ln))
    return out


def append_jsonl(p: Path, rows: list[dict]) -> None:
    if not rows:
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")


COST_BASIS = "session one-way turnover, allocated pro rata"


def one_way_turnover(w_before: dict, w_after: dict) -> float:
    """C1 as compute_nav charges it: 0.5 × Σ|w_after − w_before| over every name AND the cash sleeve
    (key "_cash"), both vectors on the pre-trade NAV of the session. A swap of A for B of value x
    turns over x; a cash-funded buy of x turns over x."""
    return 0.5 * sum(abs(w_after.get(k, 0.0) - w_before.get(k, 0.0)) for k in set(w_before) | set(w_after))


def allocate_session_cost(rows: list[dict], cost: float, source: str | None = None) -> None:
    """The session's one C1 charge, spread over the session's trade rows pro rata to traded value so
    every row still carries `cost` (the row costs sum to the session cost up to 4-dp rounding)."""
    total = sum(float(r["value"]) for r in rows)
    for r in rows:
        r["cost"] = round(cost * float(r["value"]) / total, 4) if total > 0 else 0.0
        r["cost_basis"] = COST_BASIS
        if source:
            r["cost_source"] = source


def trade_row(tier: str, session: str, ticker: str, action: str, shares: float, price: float, reason: str,
              scores: dict, regime_R: float | None, regime_label: str | None, source: str,
              nav_at_decision: float | None, detail: str | None = None, existing_ids: set | None = None) -> dict:
    assert reason in REASONS, reason
    value = abs(shares) * price
    base = f"{tier}-{session}-{ticker}-{action}"
    tid = base
    if existing_ids is not None:                 # a second same-direction trade of a name in one session
        n = 2
        while tid in existing_ids:
            tid = f"{base}-{n}"
            n += 1
        existing_ids.add(tid)
    return {
        "trade_id": tid, "session": session, "tier": tier, "ticker": ticker, "action": action,
        "shares": round(abs(shares), 6), "price": round(price, 4), "value": round(value, 2),
        "cost": None, "cost_basis": None, "reason": reason,           # set by allocate_session_cost
        "tier_composite": scores.get("tier_composite"), "tier_rank": scores.get("tier_rank"),
        "composite": scores.get("composite"), "composite_rank": scores.get("composite_rank"),
        "bq_score": scores.get("bq_score"), "bq_rank": scores.get("bq_rank"),
        "tn_score": scores.get("tn_score"), "tn_rank": scores.get("tn_rank"),
        "regime_R": regime_R, "regime_label": regime_label, "source": source,
        "scores_note": scores.get("scores_note"),
        "nav_at_decision": None if nav_at_decision is None else round(nav_at_decision, 2),
        "weight_delta": None if not nav_at_decision else round(value / nav_at_decision, 6),
        "detail": detail,
        "logged_at": now_et_iso(),
    }


def spell_event(spell_id: str, event: str, tier: str, ticker: str, entry_session: str, entry_trade_id: str,
                entry_price: float, scores_at_entry: dict, exit_session=None, exit_trade_id=None, exit_price=None,
                exit_reason=None, sessions_held=None, horizon=None, ret=None, spy_ret=None, basket_ret=None,
                basket_thesis=None, basket_note=None, post_exit=None, horizon_session=None, detail=None) -> dict:
    ex_spy = None if (ret is None or spy_ret is None) else round(ret - spy_ret, 6)
    ex_bk = None if (ret is None or basket_ret is None) else round(ret - basket_ret, 6)
    rec = {
        "spell_id": spell_id, "event": event, "tier": tier, "ticker": ticker,
        "entry_session": entry_session, "entry_trade_id": entry_trade_id, "entry_price": round(entry_price, 4),
        "exit_session": exit_session, "exit_trade_id": exit_trade_id,
        "exit_price": None if exit_price is None else round(exit_price, 4), "exit_reason": exit_reason,
        "sessions_held": sessions_held,
        "return": None if ret is None else round(ret, 6), "spy_return": None if spy_ret is None else round(spy_ret, 6),
        "excess_vs_spy": ex_spy, "basket_return": None if basket_ret is None else round(basket_ret, 6),
        "excess_vs_basket": ex_bk, "basket_thesis": basket_thesis, "basket_note": basket_note,
        "horizon": horizon, "horizon_session": horizon_session,
        "scores_at_entry": {k: scores_at_entry.get(k) for k in ("tier_composite", "tier_rank", "composite_rank", "bq_score", "tn_score")},
        "detail": detail,
        "logged_at": now_et_iso(),
    }
    if post_exit:
        rec.update(post_exit)
    return rec


def closed_spell_event(sp: dict, exit_session: str, exit_trade_id: str, exit_price: float, exit_reason: str,
                       store: PriceStore, registry: dict | None, detail: str | None = None) -> dict:
    """The `closed` event: price return from the entry trade to the exit trade, SPY over the same
    sessions (ETF store), the thesis basket (equal-weight members of the name's largest-weight thesis,
    the name excluded), and the excess returns."""
    ret = exit_price / sp["entry_price"] - 1.0
    s0, s1 = store.spy(sp["entry_session"]), store.spy(exit_session)
    spy_ret = None if (s0 is None or s1 is None) else s1 / s0 - 1.0
    thesis, members = thesis_basket_of(sp["ticker"], registry)
    if thesis is None:
        bret, bnote = None, "no thesis membership in thesis_registry.json"
    else:
        bret, missing = store.basket_return(members, sp["entry_session"], exit_session)
        bnote = None if bret is not None else "basket members without prices"
        if bret is not None and missing:
            bnote = f"members without prices dropped: {missing}"
    held = None
    if store.has_session(sp["entry_session"]) and store.has_session(exit_session):
        held = store._pos[exit_session] - store._pos[sp["entry_session"]]
    return spell_event(sp["spell_id"], "closed", sp["tier"], sp["ticker"], sp["entry_session"], sp["entry_trade_id"],
                       sp["entry_price"], sp.get("scores_at_entry") or {}, exit_session=exit_session,
                       exit_trade_id=exit_trade_id, exit_price=exit_price, exit_reason=exit_reason, sessions_held=held,
                       ret=ret, spy_ret=spy_ret, basket_ret=bret, basket_thesis=thesis, basket_note=bnote,
                       detail=detail)


def followup_events(spells: list[dict], session: str, store: PriceStore, registry: dict | None,
                    tiers: set | None = None, horizons=(20, 60)) -> list[dict]:
    """For every closed spell without a followup_h event whose horizon session (the h-th bar after the
    exit) has elapsed (≤ session, in the store): the spell's return re-measured from the entry price to
    the horizon close, plus the post-exit leg (exit price → horizon close) — each against SPY and the
    thesis basket over the matching sessions."""
    have = {(e["spell_id"], e["event"]) for e in spells}
    closed = {e["spell_id"]: e for e in spells if e.get("event") == "closed"}
    out = []
    for sid, c in sorted(closed.items()):
        if tiers is not None and c["tier"] not in tiers:
            continue
        for h in horizons:
            ev = f"followup_{h}"
            if (sid, ev) in have:
                continue
            hs = store.session_after(c["exit_session"], h)
            if hs is None or hs > session:
                continue
            px, bar = store.close(c["ticker"], hs)
            if px is None or bar != hs:
                continue
            ret = px / c["entry_price"] - 1.0
            post = px / c["exit_price"] - 1.0
            s_e, s_x, s_h = store.spy(c["entry_session"]), store.spy(c["exit_session"]), store.spy(hs)
            spy_ret = None if (s_e is None or s_h is None) else s_h / s_e - 1.0
            spy_post = None if (s_x is None or s_h is None) else s_h / s_x - 1.0
            thesis, members = thesis_basket_of(c["ticker"], registry)
            if thesis is None:
                bret, bpost, bnote = None, None, "no thesis membership in thesis_registry.json"
            else:
                bret, _ = store.basket_return(members, c["entry_session"], hs)
                bpost, _ = store.basket_return(members, c["exit_session"], hs)
                bnote = None if bret is not None else "basket members without prices"
            post_exit = {
                "post_exit_return": round(post, 6),
                "post_exit_spy_return": None if spy_post is None else round(spy_post, 6),
                "post_exit_excess_vs_spy": None if spy_post is None else round(post - spy_post, 6),
                "post_exit_basket_return": None if bpost is None else round(bpost, 6),
                "post_exit_excess_vs_basket": None if bpost is None else round(post - bpost, 6),
            }
            out.append(spell_event(sid, ev, c["tier"], c["ticker"], c["entry_session"], c["entry_trade_id"],
                                   c["entry_price"], c.get("scores_at_entry") or {}, exit_session=c["exit_session"],
                                   exit_trade_id=c["exit_trade_id"], exit_price=c["exit_price"], exit_reason=c["exit_reason"],
                                   sessions_held=c.get("sessions_held"), horizon=h, ret=ret, spy_ret=spy_ret,
                                   basket_ret=bret, basket_thesis=thesis, basket_note=bnote, post_exit=post_exit,
                                   horizon_session=hs))
            have.add((sid, ev))
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Session inputs
# ──────────────────────────────────────────────────────────────────────────────
def regime_for(session: str, data_dir: Path) -> tuple[float, str, str]:
    """(R_full, corrected corridor label, label source). R from regime_daily.csv on the session (a
    missing row refuses the run); the label from regime_indicators.json when it is stamped for the
    session, else the regime_v2_daily.csv row, else compute_nav's threshold label (marked)."""
    rd = pd.read_csv(data_dir / "regime_daily.csv")
    row = rd[rd["date"].astype(str).str[:10] == session]
    if row.empty or pd.isna(row["R_t"].iloc[0]):
        raise SystemExit(f"regime_missing: regime_daily.csv has no R_t for session {session} (run compute_regime_v2 first)")
    R = float(row["R_t"].iloc[0])
    ri = data_dir / "regime_indicators.json"
    if ri.exists():
        try:
            j = json.load(open(ri))
            if str(j.get("session_date") or j.get("as_of") or "")[:10] == session and j.get("regime"):
                return R, str(j["regime"]), "regime_indicators.json"
        except Exception:
            pass
    rv = data_dir / "regime_v2_daily.csv"
    if rv.exists():
        try:
            v = pd.read_csv(rv, usecols=["date", "regime"])
            r2 = v[v["date"].astype(str).str[:10] == session]
            if not r2.empty and isinstance(r2["regime"].iloc[0], str):
                return R, str(r2["regime"].iloc[0]), "regime_v2_daily.csv"
        except Exception:
            pass
    return R, naive_regime_label(R), "threshold_fallback"


def effr_daily_by_date(tournament_path: Path | None) -> dict:
    """{date: daily rate} from the tournament rows' effr_daily_pct (annual %, as compute_nav stores it)."""
    if not tournament_path or not Path(tournament_path).exists():
        return {}
    try:
        t = json.load(open(tournament_path))
    except Exception:
        return {}
    out = {}
    for h in t.get("history", []) or []:
        e = h.get("effr_daily_pct")
        if e is not None and h.get("date"):
            out[str(h["date"])[:10]] = float(e) / 100.0 / 252.0
    return out


def parent_navs(tournament_path: Path | None, session: str) -> dict:
    if not tournament_path or not Path(tournament_path).exists():
        return {}
    try:
        t = json.load(open(tournament_path))
        for h in reversed(t.get("history", []) or []):
            if str(h.get("date"))[:10] == session:
                return {tid: td.get("nav") for tid, td in (h.get("tiers") or {}).items()}
    except Exception:
        pass
    return {}


def load_score_book(data_dir: Path, tier_specs: dict) -> ScoreBook:
    sp = data_dir / "scored_universe.csv"
    if not sp.exists():
        raise SystemExit(f"scores_missing: {sp} (run score_universe first)")
    scored = pd.read_csv(sp)
    bq = load_bq(data_dir / "screen" / "scores.json", data_dir / "screen" / "scored_universe.csv")
    tn = load_tn(data_dir / "ticker_signals.json")
    return ScoreBook(scored, tier_specs, bq, tn,
                     bq_note=None if bq else "Business Quality: data/screen/scores.json absent at decision",
                     tn_note=None if tn else "Trade-Now: data/ticker_signals.json absent at decision")


# ──────────────────────────────────────────────────────────────────────────────
# The twin engine
# ──────────────────────────────────────────────────────────────────────────────
class Twin:
    def __init__(self, twin_id: str, parent: str, spec: dict, st: dict | None, rules: dict):
        self.id, self.parent, self.spec, self.rules = twin_id, parent, spec, rules
        st = st or {}
        self.positions: dict[str, float] = dict(st.get("positions") or {})
        self.cash: float = float(st.get("cash", rules["start_capital"]))
        self.last_session: str | None = st.get("last_session")
        self.start_date: str | None = st.get("start_date")
        self.open_spells: dict[str, dict] = dict(st.get("open_spells") or {})
        self.history: list[dict] = list(st.get("history") or [])
        self.trade_counts: dict[str, int] = dict(st.get("trade_counts") or {})
        self.cost_paid: float = float(st.get("cost_paid_total") or 0.0)
        self.K = int(spec["n_holdings"])
        self.K2 = int(round(rules["k_buffer_multiple"] * self.K))
        self.delta = float(rules["score_margin_delta"])
        self.gap_pts = float(rules["cash_gap_points"])
        self.drift = float(rules["drift_pct_of_target"]) / 100.0
        self.rate = float(rules["cost_bps_one_way"]) / 10000.0
        # per-session scratch
        self.trades: list[dict] = []
        self.spell_events: list[dict] = []
        self._ids: set = set()
        self._traded: float = 0.0          # traded value this session (bounds the session cost: cost ≤ rate × traded)

    # ── valuation ────────────────────────────────────────────────────────
    def value(self, prices: dict) -> tuple[float, float]:
        eq = sum(sh * prices[tk][0] for tk, sh in self.positions.items() if prices.get(tk, (None,))[0] is not None)
        return eq, eq + self.cash

    def weights(self, prices: dict, nav: float) -> dict:
        """NAV-weight vector over the names and the cash sleeve ("_cash"), on the given NAV."""
        if nav <= 0:
            return {"_cash": 1.0}
        w = {tk: sh * prices[tk][0] / nav for tk, sh in self.positions.items() if prices.get(tk, (None,))[0] is not None}
        w["_cash"] = self.cash / nav
        return w

    def _fresh(self, tk: str, prices: dict, session: str) -> bool:
        p = prices.get(tk)
        return bool(p and p[0] is not None and p[1] == session)

    # ── execution primitive (no cost here: the session's C1 charge is levied once, afterwards) ──
    def _exec(self, session: str, tk: str, action: str, value: float, price: float, reason: str, ctx: dict,
              detail: str | None = None, all_shares: bool = False) -> dict | None:
        _, nav = self.value(ctx["prices"])
        if action == "buy":
            # cash never negative, even after the session's cost (≤ rate × traded value) is charged
            value = min(value, max(0.0, self.cash - self.rate * self._traded) / (1.0 + self.rate))
            if value < 1.0:
                return None
            shares = value / price
            self.cash -= value
            self.positions[tk] = self.positions.get(tk, 0.0) + shares
        else:
            held = self.positions.get(tk, 0.0)
            shares = held if all_shares else min(held, value / price)
            if shares <= EPS_SHARES:
                return None
            value = shares * price
            self.cash += value
            left = held - shares
            if left <= EPS_SHARES or all_shares:
                self.positions.pop(tk, None)
            else:
                self.positions[tk] = left
        self._traded += value
        scores = ctx["book"].scores_for(tk, self.parent)
        row = trade_row(self.id, session, tk, action, shares, price, reason, scores, ctx["R"], ctx["label"],
                        "twin_engine", nav, detail=detail, existing_ids=self._ids)
        self.trades.append(row)
        self.trade_counts[reason] = self.trade_counts.get(reason, 0) + 1
        return row

    def _open_spell(self, session: str, row: dict) -> None:
        sid = f"{self.id}-{row['ticker']}-{session}"
        sp = {"spell_id": sid, "tier": self.id, "ticker": row["ticker"], "entry_session": session,
              "entry_trade_id": row["trade_id"], "entry_price": row["price"],
              "scores_at_entry": {k: row.get(k) for k in ("tier_composite", "tier_rank", "composite_rank", "bq_score", "tn_score")}}
        self.open_spells[row["ticker"]] = sp
        self.spell_events.append(spell_event(sid, "opened", self.id, row["ticker"], session, row["trade_id"],
                                             row["price"], sp["scores_at_entry"]))

    def _close_spell(self, session: str, row: dict, ctx: dict, detail: str | None = None) -> None:
        sp = self.open_spells.pop(row["ticker"], None)
        if sp is None:
            return
        self.spell_events.append(closed_spell_event(sp, session, row["trade_id"], row["price"], row["reason"],
                                                    ctx["store"], ctx["registry"], detail=detail))

    # ── the session ─────────────────────────────────────────────────────
    def run_session(self, session: str, ctx: dict) -> dict:
        prices, book, R = ctx["prices"], ctx["book"], ctx["R"]
        cp = cash_pct_from_formula(R, self.spec)
        ranked = book.ranking(self.parent)
        rank_of = {t: int(r) for t, r in zip(ranked["ticker"], ranked["tier_rank"])}
        comp_of = {t: float(c) for t, c in zip(ranked["ticker"], ranked["tier_composite"])}
        top_k = list(ranked["ticker"].head(self.K))
        notes = []

        if self.last_session is None:                                    # ── SEED
            self.start_date = session
            self.cash = float(self.rules["start_capital"])
            self.positions = {}
            _, nav = self.value(prices)
            nav_pre, w_before = nav, {"_cash": 1.0}
            w = (1.0 - cp) / self.K
            for tk in top_k:
                if not self._fresh(tk, prices, session):
                    notes.append(f"{tk}: no close on {session}; not seeded")
                    continue
                row = self._exec(session, tk, "buy", w * nav, prices[tk][0], "SEED", ctx)
                if row:
                    self._open_spell(session, row)
        else:
            # cash accrues EFFR for every trading day since the last processed session
            d = self.last_session
            while True:
                d = self._next_trading_day(d)
                if d > session:
                    break
                self.cash *= 1.0 + ctx["effr"].get(d, 0.04 / 252)
            # pre-trade weight vector on the session's closes (from here only trades move it)
            _, nav_pre = self.value(prices)
            w_before = self.weights(prices, nav_pre)
            # (b) RANK_EXIT
            for tk in list(self.positions):
                r = rank_of.get(tk)
                if r is not None and r <= self.K2:
                    continue
                px, bar = prices.get(tk, (None, None))
                if px is None:
                    notes.append(f"{tk}: rank {r} > 2K but no price at all; held")
                    continue
                detail = (f"rank {r} > 2K={self.K2}" if r is not None else "left the scored file")
                if bar != session:
                    detail += f"; no bar on {session}, last close {bar}"
                row = self._exec(session, tk, "sell", 0.0, px, "RANK_EXIT", ctx, detail=detail, all_shares=True)
                if row:
                    self._close_spell(session, row, ctx, detail=detail)
            # (c) RANK_ENTRY — open slots first, then displacement by δ
            cands = [t for t in top_k if t not in self.positions]
            filled = []
            while len(self.positions) < self.K and cands:
                tk = cands.pop(0)
                if not self._fresh(tk, prices, session):
                    notes.append(f"{tk}: top-K but no close on {session}; slot stays open")
                    continue
                _, nav = self.value(prices)
                row = self._exec(session, tk, "buy", (1.0 - cp) / self.K * nav, prices[tk][0], "RANK_ENTRY", ctx,
                                 detail=f"open slot; rank {rank_of.get(tk)}")
                if row:
                    self._open_spell(session, row)
                    filled.append(tk)
            for tk in cands:
                if not self._fresh(tk, prices, session) or not self.positions:
                    continue
                weakest = min(self.positions, key=lambda t: comp_of.get(t, float("-inf")))
                margin = comp_of.get(tk, float("-inf")) - comp_of.get(weakest, float("-inf"))
                if margin < self.delta - 1e-12 or not self._fresh(weakest, prices, session):
                    continue
                d1 = f"displaced by {tk}: margin {margin:.3f} ≥ δ {self.delta}"
                srow = self._exec(session, weakest, "sell", 0.0, prices[weakest][0], "RANK_EXIT", ctx, detail=d1, all_shares=True)
                if srow:
                    self._close_spell(session, srow, ctx, detail=d1)
                _, nav = self.value(prices)
                d2 = f"displaces {weakest}: margin {margin:.3f} ≥ δ {self.delta}; rank {rank_of.get(tk)}"
                brow = self._exec(session, tk, "buy", (1.0 - cp) / self.K * nav, prices[tk][0], "RANK_ENTRY", ctx, detail=d2)
                if brow:
                    self._open_spell(session, brow)
            # (d) REGIME_CASH
            eq, nav = self.value(prices)
            if nav > 0:
                actual = self.cash / nav
                gap_pts = (cp - actual) * 100.0
                if abs(gap_pts) > self.gap_pts and eq > 0:
                    delta_cash = (cp - actual) * nav
                    tradable = [t for t in self.positions if self._fresh(t, prices, session)]
                    eq_tr = sum(self.positions[t] * prices[t][0] for t in tradable)
                    d3 = f"cash {actual*100:.1f}% vs target {cp*100:.1f}% (gap {gap_pts:+.1f} pts > {self.gap_pts}); label {ctx['label']}"
                    for t in tradable:
                        v = self.positions[t] * prices[t][0] * abs(delta_cash) / eq_tr if eq_tr > 0 else 0.0
                        if delta_cash > 0:
                            self._exec(session, t, "sell", v, prices[t][0], "REGIME_CASH", ctx, detail=d3)
                        else:
                            self._exec(session, t, "buy", v, prices[t][0], "REGIME_CASH", ctx, detail=d3)
            # (e) DRIFT
            eq, nav = self.value(prices)
            n = len(self.positions)
            if n and nav > 0:
                tw = (1.0 - cp) / n
                for t in sorted(self.positions, key=lambda x: rank_of.get(x, 10 ** 6)):
                    if not self._fresh(t, prices, session):
                        continue
                    _, nav = self.value(prices)
                    v = self.positions[t] * prices[t][0]
                    w = v / nav
                    if abs(w - tw) > self.drift * tw:
                        d4 = f"weight {w*100:.2f}% vs target {tw*100:.2f}% ({(w/tw-1)*100:+.1f}% of target > {self.drift*100:.0f}%)"
                        target_v = tw * nav
                        if target_v > v:
                            self._exec(session, t, "buy", target_v - v, prices[t][0], "DRIFT", ctx, detail=d4)
                        else:
                            self._exec(session, t, "sell", v - target_v, prices[t][0], "DRIFT", ctx, detail=d4)

        # ── the session's C1 charge, as compute_nav levies it: 10 bps × one-way turnover (names + cash,
        #    on the pre-trade NAV), once from cash, allocated pro rata to the session's trade rows
        w_after = self.weights(prices, nav_pre)
        turnover = one_way_turnover(w_before, w_after) if self.trades else 0.0
        cost = self.rate * turnover * nav_pre
        self.cash -= cost
        self.cost_paid += cost
        allocate_session_cost(self.trades, cost)
        eq, nav = self.value(prices)
        self.last_session = session
        hrow = {"date": session, "nav": round(nav, 2), "equity": round(eq, 2), "cash": round(self.cash, 2),
                "target_cash_pct": round(cp * 100, 1), "actual_cash_pct": round(self.cash / nav * 100, 1) if nav else None,
                "n_positions": len(self.positions), "R_t": round(R, 4), "regime": ctx["label"],
                "n_trades": len(self.trades), "nav_pre": round(nav_pre, 2),
                "turnover_one_way": round(turnover, 6), "cost": round(cost, 4)}
        self.history.append(hrow)
        return {"row": hrow, "notes": notes, "cp": cp, "rank_of": rank_of, "comp_of": comp_of}

    @staticmethod
    def _next_trading_day(d: str) -> str:
        from datetime import date, timedelta
        cur = date.fromisoformat(d) + timedelta(days=1)
        while not is_trading_day(cur):
            cur += timedelta(days=1)
        return cur.isoformat()

    def state(self) -> dict:
        return {"parent_tier": self.parent, "start_date": self.start_date, "last_session": self.last_session,
                "cash": round(self.cash, 6), "positions": {t: round(s, 6) for t, s in sorted(self.positions.items())},
                "open_spells": self.open_spells, "trade_counts": self.trade_counts,
                "cost_paid_total": round(self.cost_paid, 4), "history": self.history}

    def served(self, prices: dict, cp: float, rank_of: dict, comp_of: dict, parent_nav) -> dict:
        eq, nav = self.value(prices)
        n = len(self.positions)
        tw = (1.0 - cp) / n if n else None
        pos = []
        for t, s in sorted(self.positions.items(), key=lambda kv: rank_of.get(kv[0], 10 ** 6)):
            px = prices.get(t, (None, None))
            v = s * px[0] if px[0] is not None else None
            pos.append({"ticker": t, "shares": round(s, 6), "price": None if px[0] is None else round(px[0], 2),
                        "price_date": px[1], "value": None if v is None else round(v, 2),
                        "weight": None if (v is None or not nav) else round(v / nav * 100, 2),
                        "target_weight": None if tw is None else round(tw * 100, 2),
                        "tier_rank": rank_of.get(t), "tier_composite": None if t not in comp_of else round(comp_of[t], 3),
                        "entry_session": (self.open_spells.get(t) or {}).get("entry_session")})
        return {"parent_tier": self.parent, "short": self.spec.get("short"), "color": self.spec.get("color"),
                "K": self.K, "exit_rank_buffer": self.K2, "start_date": self.start_date, "last_session": self.last_session,
                "nav": round(nav, 2), "equity": round(eq, 2), "cash": round(self.cash, 2),
                "target_cash_pct": round(cp * 100, 1), "actual_cash_pct": round(self.cash / nav * 100, 1) if nav else None,
                "n_positions": n, "positions": pos, "trade_counts": self.trade_counts,
                "n_trades": sum(self.trade_counts.values()), "cost_paid_total": round(self.cost_paid, 2),
                "open_spells": len(self.open_spells), "parent_nav_same_session": parent_nav,
                "return_since_start_pct": round((nav / float(self.rules["start_capital"]) - 1) * 100, 3),
                "history": self.history}


# ──────────────────────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--session", default=None, help="YYYY-MM-DD (default: PUBLISH_SESSION env, else the last completed session)")
    ap.add_argument("--data-dir", default=None, help="root for the inputs (default: <repo>/data)")
    ap.add_argument("--config", default=None)
    ap.add_argument("--rules", default=None)
    ap.add_argument("--state", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--trades", default=None)
    ap.add_argument("--spells", default=None)
    ap.add_argument("--prices", default=None, help="price store parquet (default: <data-dir>/source/prices_daily.parquet)")
    ap.add_argument("--etfs", default=None, help="ETF store parquet with `spy` (default: <data-dir>/source/sector_etfs.parquet)")
    ap.add_argument("--tournament", default=None, help="tournament.json for EFFR and the parents' NAVs ('none' to skip)")
    ap.add_argument("--dry-run", action="store_true", help="compute and print; write nothing")
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else REPO / "data"
    tdir = data_dir / "tournament"
    cfg_path = Path(args.config) if args.config else REPO / "config.json"
    cfg = json.load(open(cfg_path))
    tier_specs = cfg["tier_specs"]
    rules, rules_path = load_rules(Path(args.rules) if args.rules else (tdir / "continuous_rules.json" if args.data_dir else None), cfg)
    rules_sha = sha256_file(rules_path)
    state_p = Path(args.state) if args.state else tdir / "twins_state.json"
    out_p = Path(args.out) if args.out else tdir / "twins.json"
    trades_p = Path(args.trades) if args.trades else tdir / "trades.jsonl"
    spells_p = Path(args.spells) if args.spells else tdir / "spells.jsonl"
    prices_p = Path(args.prices) if args.prices else data_dir / "source" / "prices_daily.parquet"
    etfs_p = Path(args.etfs) if args.etfs else data_dir / "source" / "sector_etfs.parquet"
    tourn_p = None if args.tournament == "none" else (Path(args.tournament) if args.tournament else data_dir / "tournament.json")

    session = args.session or os.environ.get("PUBLISH_SESSION") or last_completed_session()
    if not is_trading_day(session):
        raise SystemExit(f"non_session: {session} is not a trading day — twins never trade on a non-session")
    lcs = last_completed_session()
    if session > lcs:
        raise SystemExit(f"session_not_complete: {session} is after the last completed session {lcs}")

    state = json.load(open(state_p)) if state_p.exists() else {"twins": {}}
    twins_state = state.get("twins", {})
    done = [tw for tw, st in twins_state.items() if (st or {}).get("last_session") and st["last_session"] >= session]
    if done and len(done) == len(rules["twins"]):
        print(f"[compute_twins] session {session} already processed (state last_session "
              f"{max(st['last_session'] for st in twins_state.values())}) — no-op")
        return 0

    # inputs of the session
    store = PriceStore(prices_p, etfs_p)
    if not store.has_session(session):
        raise SystemExit(f"price_store_session_missing: {prices_p.name} has no bar for {session} (ends {store.last_session()})")
    if tourn_p and tourn_p.exists():
        try:
            last_row = (json.load(open(tourn_p)).get("history") or [{}])[-1].get("date")
            if last_row and str(last_row)[:10] < session:
                raise SystemExit(f"tournament_not_published: tournament.json last row {last_row} < session {session} (run compute_nav first)")
        except SystemExit:
            raise
        except Exception:
            pass
    R, label, label_src = regime_for(session, data_dir)
    book = load_score_book(data_dir, tier_specs)
    registry = None
    if (data_dir / "thesis_registry.json").exists():
        registry = json.load(open(data_dir / "thesis_registry.json"))
    effr = effr_daily_by_date(tourn_p)
    pnavs = parent_navs(tourn_p, session)
    existing_trades = read_jsonl(trades_p)
    existing_spells = read_jsonl(spells_p)
    existing_ids = {t["trade_id"] for t in existing_trades}

    print(f"[compute_twins] session {session}  R_full {R:.4f}  label {label} ({label_src})  rules {rules_path.name} "
          f"sha {rules_sha[:12]}  effr {'row' if session in effr else 'default 4%'}")

    new_trades, new_spells, served, new_state = [], [], {}, {}
    for tw_id, parent in rules["twins"].items():
        spec = tier_specs[parent]
        twin = Twin(tw_id, parent, spec, twins_state.get(tw_id), rules)
        if twin.last_session and twin.last_session >= session:
            print(f"  {tw_id}: already at {twin.last_session} — skipped")
            new_state[tw_id] = twin.state()
            continue
        if any(t.get("tier") == tw_id and t.get("session") == session for t in existing_trades):
            raise SystemExit(f"trades_exist_for_session: {trades_p.name} already carries {tw_id} trades for {session} "
                             f"while the state is at {twin.last_session} — state and log disagree; not reprocessing")
        twin._ids = set()                                       # ids minted this session (repeat = suffix)
        ranked = book.ranking(parent)
        need = set(twin.positions) | set(ranked["ticker"].head(twin.K2))
        prices = {t: store.close(t, session) for t in need}
        ctx = {"prices": prices, "book": book, "R": R, "label": label, "effr": effr, "store": store, "registry": registry}
        res = twin.run_session(session, ctx)
        for n in res["notes"]:
            print(f"    note {tw_id}: {n}")
        dup = [t["trade_id"] for t in twin.trades if t["trade_id"] in existing_ids]
        if dup:
            raise SystemExit(f"trade_id_collision: {dup[:3]} already in {trades_p.name}")
        existing_ids |= {t["trade_id"] for t in twin.trades}
        new_trades += twin.trades
        new_spells += twin.spell_events
        new_state[tw_id] = twin.state()
        served[tw_id] = twin.served(prices, res["cp"], res["rank_of"], res["comp_of"], pnavs.get(parent))
        r = res["row"]
        by_reason = {}
        for t in twin.trades:
            by_reason[t["reason"]] = by_reason.get(t["reason"], 0) + 1
        print(f"  {tw_id} ({spec.get('short')}): NAV {r['nav']:,.2f}  cash {r['actual_cash_pct']}% vs target {r['target_cash_pct']}%  "
              f"{r['n_positions']} pos  trades {len(twin.trades)} {by_reason if by_reason else ''}")

    # follow-ups for every closed spell in the file (twins and monthly tiers alike)
    fu = followup_events(existing_spells + new_spells, session, store, registry)
    new_spells += fu
    if fu:
        print(f"  follow-up events appended: {len(fu)}")

    start_dates = [s.get("start_date") for s in new_state.values() if s.get("start_date")]
    out = {
        "cadence": "daily", "session_date": session, "computed_at": now_et_iso(),
        "order": rules.get("order"), "label": rules.get("label"),
        "start_date": min(start_dates) if start_dates else None,
        "rules_file": str(rules_path.relative_to(REPO)) if str(rules_path).startswith(str(REPO)) else str(rules_path),
        "rules_sha256": rules_sha,
        "rules": {k: rules[k] for k in RULE_KEYS},
        "reason_codes": list(REASONS),
        "cost_model": rules.get("cost_model"),
        "regime": {"R_full": round(R, 4), "label": label, "label_source": label_src},
        "logs": {"trades": str(trades_p.relative_to(REPO)) if str(trades_p).startswith(str(REPO)) else str(trades_p),
                 "spells": str(spells_p.relative_to(REPO)) if str(spells_p).startswith(str(REPO)) else str(spells_p),
                 "trades_this_session": len(new_trades), "spell_events_this_session": len(new_spells)},
        "twins": served,
    }
    if args.dry_run:
        print("  dry run — nothing written")
        for t in new_trades:
            print(f"    {t['tier']} {t['action']:4s} {t['ticker']:6s} {t['shares']:>12.4f} @ {t['price']:>9.2f}  {t['reason']:12s} {t['detail'] or ''}")
        return 0

    tdir.mkdir(parents=True, exist_ok=True)
    append_jsonl(trades_p, new_trades)
    append_jsonl(spells_p, new_spells)
    state_out = {"cadence": "daily", "session_date": session, "rules_sha256": rules_sha, "twins": new_state,
                 "updated": now_et_iso()}
    with open(state_p, "w") as f:
        json.dump(state_out, f, indent=1, default=str)
    with open(out_p, "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(f"  wrote {out_p.name}, {state_p.name}; +{len(new_trades)} trades, +{len(new_spells)} spell events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
